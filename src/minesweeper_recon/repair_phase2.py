from __future__ import annotations

import heapq

import numpy as np

from .core import compute_N
from .models import RepairContext, RepairResult, SolveResult
from .parallel_eval import ParallelSolveEvaluator
from .repair_prefilter import forcing_potential_score
from .runtime import BudgetExceeded, check_deadline, now_s


def _candidate_key(edits: list[tuple[int, int, int]] | tuple[tuple[int, int, int], ...]) -> tuple[tuple[int, int, int], ...]:
    return tuple(sorted((int(y), int(x), int(delta)) for y, x, delta in edits))


def _check_swap_valid(N_cur, H, W, my, mx, ty, tx):
    delta = {}
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            if dy == 0 and dx == 0:
                continue
            ny, nx = my + dy, mx + dx
            if 0 <= ny < H and 0 <= nx < W:
                delta[(ny, nx)] = delta.get((ny, nx), 0) - 1
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            if dy == 0 and dx == 0:
                continue
            ny, nx = ty + dy, tx + dx
            if 0 <= ny < H and 0 <= nx < W:
                delta[(ny, nx)] = delta.get((ny, nx), 0) + 1
    for (ny, nx), d in delta.items():
        nv = N_cur[ny, nx] + d
        if nv < 0 or nv > 8:
            return False
    return True


def _swap_asymmetry_score(my, mx, ty, tx, unknown_set, H, W):
    nbrs_m = set((my + dy, mx + dx) for dy in range(-2, 3) for dx in range(-2, 3) if 0 <= my + dy < H and 0 <= mx + dx < W and (dy, dx) != (0, 0))
    nbrs_t = set((ty + dy, tx + dx) for dy in range(-2, 3) for dx in range(-2, 3) if 0 <= ty + dy < H and 0 <= tx + dx < W and (dy, dx) != (0, 0))
    unkn_near_m = nbrs_m & unknown_set
    unkn_near_t = nbrs_t & unknown_set
    exclusive = len(unkn_near_t - unkn_near_m) + len(unkn_near_m - unkn_near_t)
    shared = len(unkn_near_t & unkn_near_m)
    return exclusive - shared * 0.5


def _target_pass_rate_from_pressure(pressure: float) -> float:
    if pressure < 0.35:
        return 0.25
    if pressure <= 0.70:
        return 0.35
    return 0.45


def _quantile_threshold(scores: list[float], pass_rate: float) -> float:
    if not scores:
        return float("inf")
    q = max(0.0, min(1.0, 1.0 - pass_rate))
    return float(np.quantile(np.array(scores, dtype=np.float32), q))


def _pct(part: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * part / total, 2)


def _local_loss_delta_estimate(
    N_cur: np.ndarray,
    target: np.ndarray,
    weights: np.ndarray,
    edits: tuple[tuple[int, int, int], ...],
    H: int,
    W: int,
) -> float:
    delta_map: dict[tuple[int, int], int] = {}
    for y, x, mine_delta in edits:
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                if dy == 0 and dx == 0:
                    continue
                ny, nx = y + dy, x + dx
                if 0 <= ny < H and 0 <= nx < W:
                    delta_map[(ny, nx)] = delta_map.get((ny, nx), 0) + int(mine_delta)
    d_loss = 0.0
    for (ny, nx), delta in delta_map.items():
        n0 = float(N_cur[ny, nx])
        n1 = n0 + float(delta)
        if n1 < 0.0 or n1 > 8.0:
            return float("inf")
        diff0 = n0 - float(target[ny, nx])
        diff1 = n1 - float(target[ny, nx])
        d_loss += float(weights[ny, nx]) * (diff1 * diff1 - diff0 * diff0)
    return float(d_loss)


def _select_hotspot_unknowns(
    unknown_list: list[tuple[int, int]],
    *,
    top_k: int,
    radius: int,
    cap: int,
) -> tuple[list[tuple[int, int]], int]:
    if not unknown_list:
        return [], 0
    top_k = max(1, int(top_k))
    radius = max(1, int(radius))
    cap = max(1, int(cap))
    unknown_set = set(unknown_list)
    scores: list[tuple[int, int, int]] = []
    for y, x in unknown_list:
        score = 0
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if (y + dy, x + dx) in unknown_set:
                    score += 1
        scores.append((score, y, x))
    anchors = sorted(scores, key=lambda t: (-t[0], t[1], t[2]))[:top_k]
    selected: set[tuple[int, int]] = set()
    for _, ay, ax in anchors:
        for y, x in unknown_list:
            if abs(y - ay) <= radius and abs(x - ax) <= radius:
                selected.add((y, x))
    if not selected:
        selected = set(unknown_list[:cap])
    out = sorted(selected)
    if len(out) > cap:
        out = out[:cap]
    return out, len(selected)


def _build_beam_keys(
    actions: list[tuple[float, tuple[tuple[int, int, int], ...], tuple[tuple[int, int], ...]]],
    *,
    depth: int,
    width: int,
    branch: int,
    shortlist: int,
) -> tuple[list[tuple[tuple[int, int, int], ...]], int]:
    if not actions:
        return [], 0
    depth = max(1, int(depth))
    width = max(1, int(width))
    branch = max(1, int(branch))
    shortlist = max(1, int(shortlist))
    sorted_actions = sorted(actions, key=lambda t: (-float(t[0]), t[1]))

    frontier: list[tuple[float, tuple[tuple[int, int, int], ...], frozenset[tuple[int, int]]]] = [
        (0.0, tuple(), frozenset())
    ]
    scored_keys: dict[tuple[tuple[int, int, int], ...], float] = {}

    for action_score, action_key, _ in sorted_actions:
        scored_keys.setdefault(action_key, float(action_score))

    for _ in range(depth):
        next_nodes: list[tuple[float, tuple[tuple[int, int, int], ...], frozenset[tuple[int, int]]]] = []
        for node_score, node_key, node_used in frontier:
            expansions = 0
            for action_score, action_key, action_cells in sorted_actions:
                if expansions >= branch:
                    break
                action_cell_set = frozenset(action_cells)
                if node_used & action_cell_set:
                    continue
                merged_key = _candidate_key(node_key + action_key)
                merged_score = float(node_score) + float(action_score)
                merged_used = frozenset(set(node_used) | set(action_cell_set))
                prior = scored_keys.get(merged_key)
                if prior is None or merged_score > prior:
                    scored_keys[merged_key] = merged_score
                next_nodes.append((merged_score, merged_key, merged_used))
                expansions += 1
        if not next_nodes:
            break
        next_nodes = sorted(next_nodes, key=lambda t: (-float(t[0]), t[1]))[:width]
        frontier = next_nodes

    ranked = sorted(scored_keys.items(), key=lambda kv: (-float(kv[1]), kv[0]))
    return [key for key, _ in ranked[:shortlist]], len(scored_keys)


def run_phase2_swap_repair(context: RepairContext) -> RepairResult:
    H, W = context.grid.shape
    t_start = now_s()
    deadline_s = context.deadline_s

    best = context.grid.copy()
    best_sr = context.initial_solve_result
    solve_calls = 0
    solve_time_s = 0.0
    no_improve_outer = 0
    prefilter_total = 0
    prefilter_passed = 0
    prefilter_rejected = 0
    full_evals = 0
    full_eval_time_s = 0.0
    cache_hits = 0
    cache_misses = 0
    duplicate_eval_skipped = 0
    fallback_skipped_already_evaluated = 0
    forcing_checks = 0
    forcing_passes = 0
    adaptive_threshold_sum = 0.0
    target_pass_rate_sum = 0.0
    effective_pass_rate_sum = 0.0
    adaptive_rounds = 0
    mine_scan_s = 0.0
    target_scan_s = 0.0
    swap_scoring_s = 0.0
    prefilter_s = 0.0
    selection_s = 0.0
    parallel_eval_batches = 0
    parallel_eval_submitted = 0
    parallel_eval_completed = 0
    parallel_eval_cancelled = 0
    parallel_eval_failed = 0
    parallel_eval_wall_s = 0.0
    parallel_eval_cpu_s = 0.0
    batch_timeout_count = 0
    deadline_preemptions = 0
    hotspot_unknown_scanned = 0
    beam_candidates = 0
    heuristic_shortlist = 0
    fullsolve_finalists = 0

    max_outer = context.max_outer or 200
    max_mines = 16
    max_targets = 96
    max_scored_swaps = 160
    max_swap_eval = 12
    max_remove_eval = 8
    scan_unknown_cap = 256
    hotspot_top_k = max(1, int(getattr(context, "phase2_hotspot_top_k", 6)))
    hotspot_radius = max(1, int(getattr(context, "phase2_hotspot_radius", 6)))
    delta_shortlist_cap = max(1, int(getattr(context, "phase2_delta_shortlist", 24)))
    beam_width = max(1, int(getattr(context, "phase2_beam_width", 6)))
    beam_depth = max(1, int(getattr(context, "phase2_beam_depth", 2)))
    beam_branch = max(1, int(getattr(context, "phase2_beam_branch", 8)))
    fullsolve_cap_cfg = max(1, int(getattr(context, "phase2_fullsolve_cap", 8)))
    solve_cache: dict[tuple[tuple[int, int, int], ...], SolveResult] = {}
    parallel_jobs = max(1, int(context.parallel_eval_jobs or 1))
    parallel_batch_size = max(1, int(context.parallel_eval_batch_size or parallel_jobs))
    evaluator: ParallelSolveEvaluator | None = None

    def deadline_reached() -> bool:
        return deadline_s is not None and now_s() >= deadline_s

    def solve_with_budget(board: np.ndarray) -> SolveResult:
        nonlocal solve_calls, solve_time_s
        check_deadline(deadline_s, "phase2_repair")
        ts = now_s()
        sr_local = context.solve_fn(board, deadline_s)
        solve_calls += 1
        solve_time_s += now_s() - ts
        return sr_local

    def evaluate_edits(edits: list[tuple[int, int, int]]) -> SolveResult:
        nonlocal cache_hits, cache_misses, full_evals, full_eval_time_s
        key = _candidate_key(edits)
        cached = solve_cache.get(key)
        if cached is not None:
            cache_hits += 1
            return cached
        cache_misses += 1
        candidate = best.copy()
        for y, x, delta in edits:
            candidate[y, x] = 1 if delta > 0 else 0
        t_eval = now_s()
        sr_local = solve_with_budget(candidate)
        dt = now_s() - t_eval
        full_eval_time_s += dt
        full_evals += 1
        solve_cache[key] = sr_local
        return sr_local

    def evaluate_edits_batch(
        keys: list[tuple[tuple[int, int, int], ...]]
    ) -> dict[tuple[tuple[int, int, int], ...], SolveResult]:
        nonlocal cache_hits, cache_misses, full_evals, full_eval_time_s, solve_time_s, solve_calls
        nonlocal parallel_eval_batches, parallel_eval_submitted, parallel_eval_completed
        nonlocal parallel_eval_cancelled, parallel_eval_failed, parallel_eval_wall_s, parallel_eval_cpu_s
        out: dict[tuple[tuple[int, int, int], ...], SolveResult] = {}
        misses: list[tuple[tuple[int, int, int], ...]] = []
        for key in keys:
            cached = solve_cache.get(key)
            if cached is not None:
                cache_hits += 1
                out[key] = cached
            else:
                cache_misses += 1
                misses.append(key)
        if not misses:
            return out

        if evaluator is None or len(misses) == 1:
            for key in misses:
                sr_local = evaluate_edits(list(key))
                out[key] = sr_local
            return out

        check_deadline(deadline_s, "phase2_repair_parallel_batch")
        batch_results, batch_stats = evaluator.evaluate_batch(best, misses, deadline_s=deadline_s)
        parallel_eval_batches += 1
        parallel_eval_submitted += int(batch_stats.get("submitted", 0))
        parallel_eval_completed += int(batch_stats.get("completed", 0))
        parallel_eval_cancelled += int(batch_stats.get("cancelled", 0))
        parallel_eval_failed += int(batch_stats.get("failed", 0))
        parallel_eval_wall_s += float(batch_stats.get("wall_s", 0.0))
        parallel_eval_cpu_s += float(batch_stats.get("cpu_s", 0.0))

        wall = float(batch_stats.get("wall_s", 0.0))
        solve_time_s += wall
        full_eval_time_s += wall
        completed = int(batch_stats.get("completed", 0))
        full_evals += completed
        solve_calls += completed

        for key, sr_local in batch_results.items():
            solve_cache[key] = sr_local
            out[key] = sr_local
        return out

    try:
        if best_sr is None:
            best_sr = solve_with_budget(best)
    except BudgetExceeded:
        fallback_unknown = set(map(tuple, np.argwhere(best == 0)))
        fallback_sr = SolveResult(
            solvable=False,
            revealed=set(),
            flagged=set(),
            unknown=fallback_unknown,
            coverage=0.0,
            mine_accuracy=0.0,
            n_unknown=len(fallback_unknown),
        )
        return RepairResult(
            grid=best,
            solve_result=fallback_sr,
            reason=f"timeout ({now_s()-t_start:.0f}s)",
            telemetry={
                "solve_calls": solve_calls,
                "solve_time_s": round(solve_time_s, 4),
                "elapsed_s": round(now_s() - t_start, 3),
                "prefilter_total": prefilter_total,
                "prefilter_passed": prefilter_passed,
                "prefilter_rejected": prefilter_rejected,
                "full_evals": full_evals,
                "full_eval_time_s": round(full_eval_time_s, 4),
            },
        )

    best_unk = best_sr.n_unknown
    best_cov = best_sr.coverage

    if best_unk == 0:
        return RepairResult(
            grid=best,
            solve_result=best_sr,
            reason="already_solvable",
            telemetry={"solve_calls": solve_calls, "solve_time_s": round(solve_time_s, 4), "elapsed_s": 0.0},
        )

    if context.verbose:
        print(f"  [Swap repair]  {best_unk} unknowns, budget={context.time_budget_s:.0f}s")

    stop_reason = "budget"
    N_cur = compute_N(best)
    if parallel_jobs > 1:
        evaluator = ParallelSolveEvaluator(
            jobs=parallel_jobs,
            solver_mode=context.solver_mode,
            deterministic=bool(context.deterministic_solver),
            failure_policy=context.failure_policy,
        )

    try:
        for outer in range(max_outer):
            elapsed = now_s() - t_start
            if elapsed >= context.time_budget_s:
                stop_reason = f"timeout ({elapsed:.0f}s)"
                break
            if best_unk == 0:
                stop_reason = "solved"
                break

            unknown_set = {(int(y), int(x)) for y, x in best_sr.unknown}
            unknown_list = sorted(unknown_set)
            scan_unknown, selected_hotspot_total = _select_hotspot_unknowns(
                unknown_list,
                top_k=hotspot_top_k,
                radius=hotspot_radius,
                cap=scan_unknown_cap,
            )
            hotspot_unknown_scanned += len(scan_unknown)

            t_stage = now_s()
            mine_scores = {}
            for u_i, (uy, ux) in enumerate(scan_unknown):
                if u_i % 32 == 0 and deadline_reached():
                    deadline_preemptions += 1
                    stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                    break
                for r in range(1, 6):
                    for dy in range(-r, r + 1):
                        for dx in range(-r, r + 1):
                            if abs(dy) != r and abs(dx) != r:
                                continue
                            ny, nx = uy + dy, ux + dx
                            if 0 <= ny < H and 0 <= nx < W and best[ny, nx] == 1 and context.forbidden[ny, nx] == 0:
                                mine_scores[(ny, nx)] = mine_scores.get((ny, nx), 0) + 1
            mine_scan_s += now_s() - t_stage
            if stop_reason.startswith("timeout"):
                break

            if not mine_scores:
                stop_reason = "no_candidate_mines"
                break
            sorted_mines = sorted(mine_scores.items(), key=lambda x: -x[1])

            t_stage = now_s()
            target_set = {}
            for u_i, (uy, ux) in enumerate(scan_unknown):
                if u_i % 32 == 0 and deadline_reached():
                    deadline_preemptions += 1
                    stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                    break
                for dy in range(-3, 4):
                    for dx in range(-3, 4):
                        ty, tx = uy + dy, ux + dx
                        if 0 <= ty < H and 0 <= tx < W and best[ty, tx] == 0 and context.forbidden[ty, tx] == 0:
                            if (ty, tx) not in target_set:
                                target_set[(ty, tx)] = []
                            target_set[(ty, tx)].append((uy, ux))
            target_scan_s += now_s() - t_stage
            if stop_reason.startswith("timeout"):
                break

            ranked_targets = sorted(target_set.items(), key=lambda kv: -len(kv[1]))[:max_targets]
            if not ranked_targets:
                stop_reason = "no_swap_targets"
                break

            t_stage = now_s()
            scored_heap = []
            for mi, ((my, mx), _) in enumerate(sorted_mines[:max_mines]):
                if mi % 4 == 0 and deadline_reached():
                    deadline_preemptions += 1
                    stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                    break
                for t_i, ((ty, tx), supporters) in enumerate(ranked_targets):
                    if t_i % 32 == 0 and deadline_reached():
                        deadline_preemptions += 1
                        stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                        break
                    if (ty, tx) == (my, mx):
                        continue
                    if not _check_swap_valid(N_cur, H, W, my, mx, ty, tx):
                        continue
                    score = _swap_asymmetry_score(my, mx, ty, tx, unknown_set, H, W) + min(len(supporters), 8) * 0.25
                    item = (score, my, mx, ty, tx)
                    if len(scored_heap) < max_scored_swaps:
                        heapq.heappush(scored_heap, item)
                    elif score > scored_heap[0][0]:
                        heapq.heapreplace(scored_heap, item)
                if stop_reason.startswith("timeout"):
                    break
            swap_scoring_s += now_s() - t_stage
            if stop_reason.startswith("timeout"):
                break

            if not scored_heap:
                stop_reason = "no_valid_swaps"
                break
            scored_swaps = sorted(scored_heap, key=lambda x: -x[0])

            improved = False
            avg_solve_s = solve_time_s / max(solve_calls, 1)
            remaining_s = max(0.0, deadline_s - now_s()) if deadline_s is not None else 10.0
            affordable_solves = max(1, int(remaining_s / max(avg_solve_s, 0.05)))
            swap_eval_cap = min(max_swap_eval, max(1, affordable_solves - 2))
            remove_eval_cap = min(max_remove_eval, max(1, affordable_solves - swap_eval_cap - 1))

            t_stage = now_s()
            fallback_swaps = {(my, mx, ty, tx) for _, my, mx, ty, tx in scored_swaps[:3]}
            prefilter_scan_cap = min(len(scored_swaps), max(24, swap_eval_cap * 6))
            scored_subset = scored_swaps[:prefilter_scan_cap]
            pressure = remaining_s / max(context.time_budget_s, 1e-9)
            target_pass_rate = _target_pass_rate_from_pressure(pressure)
            adaptive_threshold = _quantile_threshold([float(s) for s, *_ in scored_subset], target_pass_rate)
            adaptive_threshold_sum += adaptive_threshold if np.isfinite(adaptive_threshold) else 0.0
            target_pass_rate_sum += target_pass_rate
            adaptive_rounds += 1

            gated_swaps: list[tuple[float, int, int, int, int]] = []
            gated_keys: set[tuple[int, int, int, int]] = set()
            for score, my, mx, ty, tx in scored_subset:
                pass_gate = (my, mx, ty, tx) in fallback_swaps or score >= adaptive_threshold
                if not pass_gate:
                    forcing_checks += 1
                    forcing_score = forcing_potential_score(
                        N_cur=N_cur,
                        edits=[(my, mx, -1), (ty, tx, 1)],
                        revealed=best_sr.revealed,
                        flagged=best_sr.flagged,
                        H=H,
                        W=W,
                        frontier_radius=context.frontier_radius,
                    )
                    if forcing_score >= 2:
                        forcing_passes += 1
                        pass_gate = True
                if pass_gate:
                    key4 = (my, mx, ty, tx)
                    if key4 not in gated_keys:
                        gated_keys.add(key4)
                        gated_swaps.append((score, my, mx, ty, tx))

            min_pass = max(3, swap_eval_cap)
            max_pass = max(8, swap_eval_cap * 3)
            if len(gated_swaps) < min_pass:
                for score, my, mx, ty, tx in scored_subset:
                    key4 = (my, mx, ty, tx)
                    if key4 not in gated_keys:
                        gated_keys.add(key4)
                        gated_swaps.append((score, my, mx, ty, tx))
                    if len(gated_swaps) >= min_pass:
                        break
            if len(gated_swaps) > max_pass:
                gated_swaps = gated_swaps[:max_pass]

            considered = len(scored_subset)
            passed = len(gated_swaps)
            prefilter_total += considered
            prefilter_passed += passed
            prefilter_rejected += max(0, considered - passed)
            effective_pass_rate_sum += float(passed) / max(1, considered)
            prefilter_s += now_s() - t_stage

            eval_seen: set[tuple[tuple[int, int, int], ...]] = set()

            t_stage = now_s()
            action_limit = max(swap_eval_cap * 3, beam_branch * beam_width)
            actions: list[tuple[float, tuple[tuple[int, int, int], ...], tuple[tuple[int, int], ...]]] = []
            for score, my, mx, ty, tx in gated_swaps[:action_limit]:
                if context.forbidden[ty, tx] == 1:
                    continue
                key = _candidate_key(((my, mx, -1), (ty, tx, 1)))
                if key in eval_seen:
                    duplicate_eval_skipped += 1
                    continue
                eval_seen.add(key)
                d_est = _local_loss_delta_estimate(N_cur, context.target, context.weights, key, H, W)
                if not np.isfinite(d_est):
                    continue
                heuristic = float(score) - 0.10 * float(d_est)
                actions.append((heuristic, key, ((my, mx), (ty, tx))))

            remove_limit = max(remove_eval_cap * 2, beam_branch)
            for (my, mx), mine_score in sorted_mines[:remove_limit]:
                key = _candidate_key(((my, mx, -1),))
                if key in eval_seen:
                    duplicate_eval_skipped += 1
                    continue
                eval_seen.add(key)
                d_est = _local_loss_delta_estimate(N_cur, context.target, context.weights, key, H, W)
                if not np.isfinite(d_est):
                    continue
                heuristic = float(mine_score) * 0.25 - 0.08 * float(d_est)
                actions.append((heuristic, key, ((my, mx),)))

            if not actions:
                fallback_skipped_already_evaluated += 1
            else:
                shortlist_cap = min(max(4, delta_shortlist_cap), max(4, affordable_solves * 3))
                beam_keys, beam_total = _build_beam_keys(
                    actions,
                    depth=beam_depth,
                    width=beam_width,
                    branch=beam_branch,
                    shortlist=shortlist_cap,
                )
                beam_candidates += int(beam_total)
                heuristic_shortlist += len(beam_keys)

                budget_limited_cap = max(1, int(max(1.0, remaining_s) / max(avg_solve_s, 0.05) * 0.25))
                finalist_cap = min(len(beam_keys), fullsolve_cap_cfg, budget_limited_cap)
                finalist_keys = beam_keys[:finalist_cap]
                fullsolve_finalists += len(finalist_keys)

                if finalist_keys:
                    try:
                        batch_results = evaluate_edits_batch(finalist_keys)
                    except BudgetExceeded:
                        batch_timeout_count += 1
                        stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                        batch_results = {}

                    best_key = None
                    best_candidate_sr = None
                    for key in finalist_keys:
                        new_sr = batch_results.get(key)
                        if new_sr is None:
                            continue
                        if best_candidate_sr is None:
                            best_candidate_sr = new_sr
                            best_key = key
                            continue
                        if int(new_sr.n_unknown) < int(best_candidate_sr.n_unknown):
                            best_candidate_sr = new_sr
                            best_key = key
                            continue
                        if (
                            int(new_sr.n_unknown) == int(best_candidate_sr.n_unknown)
                            and float(new_sr.coverage) > float(best_candidate_sr.coverage) + 0.001
                        ):
                            best_candidate_sr = new_sr
                            best_key = key

                    if (
                        best_key is not None
                        and best_candidate_sr is not None
                        and (
                            int(best_candidate_sr.n_unknown) < int(best_unk)
                            or (
                                int(best_candidate_sr.n_unknown) == int(best_unk)
                                and float(best_candidate_sr.coverage) > float(best_cov) + 0.001
                            )
                        )
                    ):
                        for y, x, delta in best_key:
                            best[y, x] = 1 if int(delta) > 0 else 0
                        solve_cache.clear()
                        best_sr = best_candidate_sr
                        best_unk = int(best_candidate_sr.n_unknown)
                        best_cov = float(best_candidate_sr.coverage)
                        N_cur = compute_N(best)
                        improved = True
                        if context.verbose:
                            print(
                                f"  Beam {outer+1:>3d}: edits={len(best_key)}"
                                f"  unknown={best_unk}  cov={best_cov:.4f}"
                                f"  finalists={len(finalist_keys)}"
                                f"  t={now_s()-t_start:.0f}s"
                            )
            selection_s += now_s() - t_stage
            if stop_reason.startswith("timeout"):
                break

            if not improved:
                no_improve_outer += 1
                if no_improve_outer >= 4:
                    stop_reason = "stagnated"
                    if context.verbose:
                        print(f"  Swap repair stagnated after {outer+1} outer iterations")
                    break
            else:
                no_improve_outer = 0
    finally:
        if evaluator is not None:
            evaluator.close()

    elapsed = now_s() - t_start
    if context.verbose:
        print(
            f"  Swap repair done: cov={best_cov:.4f}  unknown={best_unk}"
            f"  reason={stop_reason}  t={elapsed:.1f}s"
            f"  solve_calls={solve_calls}"
        )

    speedup_est = 0.0
    if parallel_eval_wall_s > 1e-9:
        speedup_est = parallel_eval_cpu_s / parallel_eval_wall_s

    telemetry = {
        "solve_calls": solve_calls,
        "solve_time_s": round(solve_time_s, 4),
        "elapsed_s": round(elapsed, 3),
        "prefilter_total": prefilter_total,
        "prefilter_passed": prefilter_passed,
        "prefilter_rejected": prefilter_rejected,
        "full_evals": full_evals,
        "full_eval_time_s": round(full_eval_time_s, 4),
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "duplicate_eval_skipped": duplicate_eval_skipped,
        "fallback_skipped_already_evaluated": fallback_skipped_already_evaluated,
        "adaptive_threshold": round(adaptive_threshold_sum / max(1, adaptive_rounds), 4),
        "target_pass_rate": round(target_pass_rate_sum / max(1, adaptive_rounds), 4),
        "effective_pass_rate": round(effective_pass_rate_sum / max(1, adaptive_rounds), 4),
        "forcing_checks": forcing_checks,
        "forcing_passes": forcing_passes,
        "mine_scan_s": round(mine_scan_s, 4),
        "target_scan_s": round(target_scan_s, 4),
        "swap_scoring_s": round(swap_scoring_s, 4),
        "prefilter_s": round(prefilter_s, 4),
        "full_eval_s": round(full_eval_time_s, 4),
        "selection_s": round(selection_s, 4),
        "solve_wait_s": round(solve_time_s, 4),
        "parallel_eval_batches": int(parallel_eval_batches),
        "parallel_eval_submitted": int(parallel_eval_submitted),
        "parallel_eval_completed": int(parallel_eval_completed),
        "parallel_eval_cancelled": int(parallel_eval_cancelled),
        "parallel_eval_failed": int(parallel_eval_failed),
        "parallel_eval_wall_s": round(parallel_eval_wall_s, 4),
        "parallel_eval_cpu_s": round(parallel_eval_cpu_s, 4),
        "parallel_effective_speedup_est": round(speedup_est, 4),
        "parallel_queue_wait_s": round(max(0.0, parallel_eval_wall_s - parallel_eval_cpu_s / max(1, parallel_jobs)), 4),
        "batch_size_mean": float(parallel_batch_size),
        "batch_timeout_count": int(batch_timeout_count),
        "worker_failures": int(parallel_eval_failed),
        "deadline_preemptions": int(deadline_preemptions),
        "deadline_abort_batches": int(batch_timeout_count),
        "hotspot_unknown_scanned": int(hotspot_unknown_scanned),
        "beam_candidates": int(beam_candidates),
        "heuristic_shortlist": int(heuristic_shortlist),
        "fullsolve_finalists": int(fullsolve_finalists),
        "total_s": round(elapsed, 4),
        "mine_scan_pct": _pct(mine_scan_s, elapsed),
        "target_scan_pct": _pct(target_scan_s, elapsed),
        "swap_scoring_pct": _pct(swap_scoring_s, elapsed),
        "prefilter_pct": _pct(prefilter_s, elapsed),
        "full_eval_pct": _pct(full_eval_time_s, elapsed),
        "selection_pct": _pct(selection_s, elapsed),
        "solve_wait_pct": _pct(solve_time_s, elapsed),
    }
    return RepairResult(grid=best, solve_result=best_sr, reason=stop_reason, telemetry=telemetry)

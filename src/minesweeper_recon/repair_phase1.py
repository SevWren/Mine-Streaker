from __future__ import annotations

import os

import numpy as np

from .core import compute_N
from .models import RepairContext, RepairResult, SolveResult
from .repair_prefilter import forcing_potential_score
from .runtime import BudgetExceeded, check_deadline, now_s


def _candidate_key(edits: list[tuple[int, int, int]] | tuple[tuple[int, int, int], ...]) -> tuple[tuple[int, int, int], ...]:
    return tuple(sorted((int(y), int(x), int(delta)) for y, x, delta in edits))


def _pct(part: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * part / total, 2)


def run_phase1_repair(context: RepairContext) -> RepairResult:
    grid = context.grid
    forbidden = context.forbidden
    H, W = grid.shape
    best = grid.copy()
    t_start = now_s()
    stop_reason = "max_rounds"
    solve_calls = 0
    solve_time_s = 0.0
    no_improve_rounds = 0
    prefilter_total = 0
    prefilter_passed = 0
    prefilter_rejected = 0
    full_evals = 0
    full_eval_time_s = 0.0
    cache_hits = 0
    cache_misses = 0
    duplicate_eval_skipped = 0
    fallback_skipped_already_evaluated = 0
    candidate_gen_s = 0.0
    prefilter_s = 0.0
    selection_s = 0.0

    max_rounds = context.max_rounds or 200
    search_radius = context.search_radius or 6
    checkpoint_every = context.checkpoint_every or 5
    deadline_s = context.deadline_s
    solve_cache: dict[tuple[tuple[int, int, int], ...], SolveResult] = {}

    def deadline_reached() -> bool:
        return deadline_s is not None and now_s() >= deadline_s

    def solve_with_budget(board: np.ndarray) -> SolveResult:
        nonlocal solve_calls, solve_time_s
        check_deadline(deadline_s, "phase1_repair")
        ts = now_s()
        sr_local = context.solve_fn(board, deadline_s)
        solve_calls += 1
        solve_time_s += now_s() - ts
        return sr_local

    best_unk_history: list[int] = []

    def trailing_unknown_rate() -> float | None:
        if not context.enable_low_yield_handoff:
            return None
        window = max(1, context.handoff_window or 4)
        if solve_calls < (context.handoff_min_solves or 6):
            return None
        if len(best_unk_history) < window + 1:
            return None
        delta = best_unk_history[-(window + 1)] - best_unk_history[-1]
        return float(delta) / float(window)

    def should_handoff_low_yield() -> bool:
        rate = trailing_unknown_rate()
        if rate is None:
            return False
        return rate < float(context.handoff_min_rate or 0.75)

    def evaluate_candidate_remove(cy: int, cx: int) -> SolveResult:
        nonlocal cache_hits, cache_misses, full_evals, full_eval_time_s
        key = _candidate_key(((cy, cx, -1),))
        cached = solve_cache.get(key)
        if cached is not None:
            cache_hits += 1
            return cached
        cache_misses += 1
        cand = best.copy()
        cand[cy, cx] = 0
        t_eval = now_s()
        sr_local = solve_with_budget(cand)
        dt = now_s() - t_eval
        full_eval_time_s += dt
        full_evals += 1
        solve_cache[key] = sr_local
        return sr_local

    try:
        if context.initial_solve_result is not None:
            sr = context.initial_solve_result
        else:
            sr = solve_with_budget(best)
    except BudgetExceeded:
        fallback_unknown = (
            context.initial_solve_result.unknown
            if context.initial_solve_result is not None
            else set(map(tuple, np.argwhere(best == 0)))
        )
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
                "prefilter_total": prefilter_total,
                "prefilter_passed": prefilter_passed,
                "prefilter_rejected": prefilter_rejected,
                "full_evals": full_evals,
                "full_eval_time_s": round(full_eval_time_s, 4),
                "cache_hits": cache_hits,
                "cache_misses": cache_misses,
                "duplicate_eval_skipped": duplicate_eval_skipped,
                "fallback_skipped_already_evaluated": fallback_skipped_already_evaluated,
            },
        )

    best_sr = sr
    best_cov = sr.coverage
    best_unk = sr.n_unknown
    best_unk_history.append(best_unk)

    ckpt_path = None
    if context.output_dir:
        ckpt_path = os.path.join(context.output_dir, f"repair_ckpt_{context.label}.npy")

    if context.verbose:
        print(f"  Pre-repair: cov={best_cov:.4f}  unknown={best_unk}  budget={context.time_budget_s:.0f}s")

    for rnd in range(max_rounds):
        elapsed = now_s() - t_start
        if elapsed >= context.time_budget_s:
            stop_reason = f"timeout ({elapsed:.0f}s)"
            break
        if best_cov >= 0.9999:
            stop_reason = "converged"
            break

        sr = best_sr
        unknown_list = sorted(sr.unknown)
        if not unknown_list:
            stop_reason = "no_unknowns"
            break

        t_stage = now_s()
        cand_score: dict[tuple[int, int], int] = {}
        for u_i, (uy, ux) in enumerate(unknown_list):
            if u_i % 32 == 0 and deadline_reached():
                stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                break
            for dy in range(-search_radius, search_radius + 1):
                for dx in range(-search_radius, search_radius + 1):
                    ny, nx = uy + dy, ux + dx
                    if 0 <= ny < H and 0 <= nx < W and best[ny, nx] == 1 and forbidden[ny, nx] == 0:
                        cand_score[(ny, nx)] = cand_score.get((ny, nx), 0) + 1
        candidate_gen_s += now_s() - t_stage
        if stop_reason.startswith("timeout"):
            break

        if not cand_score:
            stop_reason = "no_candidates"
            break

        avg_solve_s = solve_time_s / max(solve_calls, 1)
        remaining_s = max(0.0, deadline_s - now_s()) if deadline_s is not None else 10.0
        affordable_solves = max(1, int(remaining_s / max(avg_solve_s, 0.05)))
        eval_cap = min(10, max(1, affordable_solves - 1))
        top_cap = min(120, max(30, eval_cap * 8))
        top = sorted(cand_score.items(), key=lambda x: -x[1])[:top_cap]
        if not top:
            stop_reason = "no_candidates"
            break

        t_stage = now_s()
        fallback_cells = {cell for cell, _ in top[:3]}
        N_cur = compute_N(best)
        gated: list[tuple[tuple[int, int], int]] = []
        for (cy, cx), score in top:
            prefilter_total += 1
            pass_gate = (cy, cx) in fallback_cells
            if not pass_gate:
                forcing_score = forcing_potential_score(
                    N_cur=N_cur,
                    edits=[(cy, cx, -1)],
                    revealed=sr.revealed,
                    flagged=sr.flagged,
                    H=H,
                    W=W,
                    frontier_radius=context.frontier_radius,
                )
                pass_gate = forcing_score >= 1
            if pass_gate:
                prefilter_passed += 1
                gated.append(((cy, cx), score))
            else:
                prefilter_rejected += 1
        prefilter_s += now_s() - t_stage

        accepted = None
        evaluated_keys: set[tuple[tuple[int, int, int], ...]] = set()

        t_stage = now_s()
        for (cy, cx), _ in gated[:eval_cap]:
            key = _candidate_key(((cy, cx, -1),))
            if key in evaluated_keys:
                duplicate_eval_skipped += 1
                continue
            evaluated_keys.add(key)

            try:
                new_sr = evaluate_candidate_remove(cy, cx)
            except BudgetExceeded:
                stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                break

            if new_sr.coverage >= best_cov - 0.0001:
                if new_sr.n_unknown < best_unk or new_sr.coverage > best_cov + 0.0001:
                    accepted = (cy, cx, new_sr)
                    break
            best_unk_history.append(best_unk)
            if should_handoff_low_yield():
                stop_reason = "handoff_low_yield"
                break
        if stop_reason.startswith("timeout"):
            selection_s += now_s() - t_stage
            break
        if stop_reason == "handoff_low_yield":
            selection_s += now_s() - t_stage
            break

        if accepted is None and gated:
            fallback_cell = None
            for (cy, cx), _ in gated:
                key = _candidate_key(((cy, cx, -1),))
                if key not in evaluated_keys:
                    fallback_cell = (cy, cx)
                    break

            if fallback_cell is None:
                fallback_skipped_already_evaluated += 1
            else:
                cy, cx = fallback_cell
                try:
                    new_sr = evaluate_candidate_remove(cy, cx)
                except BudgetExceeded:
                    stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                    selection_s += now_s() - t_stage
                    break
                if new_sr.coverage >= best_cov - 0.0001:
                    accepted = (cy, cx, new_sr)
                if accepted is None:
                    best_unk_history.append(best_unk)
                    if should_handoff_low_yield():
                        stop_reason = "handoff_low_yield"
                        selection_s += now_s() - t_stage
                        break
        selection_s += now_s() - t_stage
        if stop_reason == "handoff_low_yield":
            break

        if accepted:
            cy, cx, new_sr = accepted
            best[cy, cx] = 0
            solve_cache.clear()
            best_sr = new_sr
            best_cov = new_sr.coverage
            best_unk = new_sr.n_unknown
            best_unk_history.append(best_unk)
            no_improve_rounds = 0
            if ckpt_path and (rnd + 1) % checkpoint_every == 0:
                np.save(ckpt_path, best)
                if context.verbose:
                    print(
                        f"  Round {rnd+1:>4d}: cov={best_cov:.4f}"
                        f"  unknown={best_unk:>5d}"
                        f"  t={now_s()-t_start:.0f}s"
                    )
        else:
            no_improve_rounds += 1
            if no_improve_rounds >= 6:
                stop_reason = "stagnated"
                break

    if stop_reason in ("converged", "no_unknowns") and ckpt_path and os.path.exists(ckpt_path):
        os.remove(ckpt_path)

    elapsed_total = now_s() - t_start
    if context.verbose:
        print(
            f"  Repair done: cov={best_cov:.4f}  unknown={best_unk}"
            f"  reason={stop_reason}  t={elapsed_total:.1f}s"
            f"  solve_calls={solve_calls}"
        )

    telemetry = {
        "solve_calls": solve_calls,
        "solve_time_s": round(solve_time_s, 4),
        "elapsed_s": round(elapsed_total, 3),
        "prefilter_total": prefilter_total,
        "prefilter_passed": prefilter_passed,
        "prefilter_rejected": prefilter_rejected,
        "full_evals": full_evals,
        "full_eval_time_s": round(full_eval_time_s, 4),
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "duplicate_eval_skipped": duplicate_eval_skipped,
        "fallback_skipped_already_evaluated": fallback_skipped_already_evaluated,
        "candidate_gen_s": round(candidate_gen_s, 4),
        "prefilter_s": round(prefilter_s, 4),
        "full_eval_s": round(full_eval_time_s, 4),
        "selection_s": round(selection_s, 4),
        "solve_wait_s": round(solve_time_s, 4),
        "total_s": round(elapsed_total, 4),
        "candidate_gen_pct": _pct(candidate_gen_s, elapsed_total),
        "prefilter_pct": _pct(prefilter_s, elapsed_total),
        "full_eval_pct": _pct(full_eval_time_s, elapsed_total),
        "selection_pct": _pct(selection_s, elapsed_total),
        "solve_wait_pct": _pct(solve_time_s, elapsed_total),
    }
    return RepairResult(grid=best, solve_result=best_sr, reason=stop_reason, telemetry=telemetry)

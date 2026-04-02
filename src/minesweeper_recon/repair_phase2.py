from __future__ import annotations

import heapq

from .core import compute_N
from .models import RepairContext, RepairResult
from .runtime import BudgetExceeded, check_deadline, now_s


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


def run_phase2_swap_repair(context: RepairContext) -> RepairResult:
    H, W = context.grid.shape
    t_start = now_s()
    deadline_s = context.deadline_s

    best = context.grid.copy()
    best_sr = context.initial_solve_result
    if best_sr is None:
        best_sr = context.solve_fn(best, deadline_s)

    best_unk = best_sr.n_unknown
    best_cov = best_sr.coverage

    solve_calls = 0
    solve_time_s = 0.0
    no_improve_outer = 0

    max_outer = context.max_outer or 200
    max_mines = 24
    max_targets = 180
    max_scored_swaps = 320
    max_swap_eval = 20
    max_remove_eval = 12

    def solve_with_budget(board):
        nonlocal solve_calls, solve_time_s
        check_deadline(deadline_s, "phase2_repair")
        ts = now_s()
        sr_local = context.solve_fn(board, deadline_s)
        solve_calls += 1
        solve_time_s += now_s() - ts
        return sr_local

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

    for outer in range(max_outer):
        elapsed = now_s() - t_start
        if elapsed >= context.time_budget_s:
            stop_reason = f"timeout ({elapsed:.0f}s)"
            break
        if best_unk == 0:
            stop_reason = "solved"
            break

        unknown_set = best_sr.unknown
        unknown_list = list(unknown_set)

        mine_scores = {}
        for u_i, (uy, ux) in enumerate(unknown_list):
            if u_i % 32 == 0 and now_s() >= deadline_s:
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
        if stop_reason.startswith("timeout"):
            break

        if not mine_scores:
            stop_reason = "no_candidate_mines"
            break

        sorted_mines = sorted(mine_scores.items(), key=lambda x: -x[1])

        target_set = {}
        for u_i, (uy, ux) in enumerate(unknown_list):
            if u_i % 32 == 0 and now_s() >= deadline_s:
                stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                break
            for dy in range(-3, 4):
                for dx in range(-3, 4):
                    ty, tx = uy + dy, ux + dx
                    if 0 <= ty < H and 0 <= tx < W and best[ty, tx] == 0 and context.forbidden[ty, tx] == 0:
                        if (ty, tx) not in target_set:
                            target_set[(ty, tx)] = []
                        target_set[(ty, tx)].append((uy, ux))
        if stop_reason.startswith("timeout"):
            break

        ranked_targets = sorted(target_set.items(), key=lambda kv: -len(kv[1]))[:max_targets]
        if not ranked_targets:
            stop_reason = "no_swap_targets"
            break

        scored_heap = []
        for mi, ((my, mx), _) in enumerate(sorted_mines[:max_mines]):
            if mi % 4 == 0 and now_s() >= deadline_s:
                stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                break
            for t_i, ((ty, tx), supporters) in enumerate(ranked_targets):
                if t_i % 32 == 0 and now_s() >= deadline_s:
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
        if stop_reason.startswith("timeout"):
            break

        if not scored_heap:
            stop_reason = "no_valid_swaps"
            break
        scored_swaps = sorted(scored_heap, key=lambda x: -x[0])

        improved = False
        avg_solve_s = solve_time_s / max(solve_calls, 1)
        remaining_s = max(0.0, deadline_s - now_s())
        affordable_solves = max(1, int(remaining_s / max(avg_solve_s, 0.05)))
        swap_eval_cap = min(max_swap_eval, max(1, affordable_solves - 2))
        remove_eval_cap = min(max_remove_eval, max(1, affordable_solves - swap_eval_cap - 1))

        for score, my, mx, ty, tx in scored_swaps[:swap_eval_cap]:
            if now_s() >= deadline_s:
                stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                break
            candidate = best.copy()
            candidate[my, mx] = 0
            candidate[ty, tx] = 1
            if context.forbidden[ty, tx] == 1:
                continue
            try:
                new_sr = solve_with_budget(candidate)
            except BudgetExceeded:
                stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                break

            if new_sr.n_unknown < best_unk or (new_sr.n_unknown == best_unk and new_sr.coverage > best_cov + 0.001):
                best = candidate
                best_sr = new_sr
                best_unk = new_sr.n_unknown
                best_cov = new_sr.coverage
                N_cur = compute_N(best)
                improved = True
                if context.verbose:
                    print(
                        f"  Swap {outer+1:>3d}: ({my},{mx})({ty},{tx})"
                        f"  score={score:.1f}"
                        f"  unknown={best_unk}  cov={best_cov:.4f}"
                        f"  t={now_s()-t_start:.0f}s"
                    )
                break
        if stop_reason.startswith("timeout"):
            break

        if not improved:
            for (my, mx), _ in sorted_mines[:remove_eval_cap]:
                if now_s() >= deadline_s:
                    stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                    break
                candidate = best.copy()
                candidate[my, mx] = 0
                N_c = compute_N(candidate)
                if N_c.min() < 0:
                    continue
                try:
                    new_sr = solve_with_budget(candidate)
                except BudgetExceeded:
                    stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                    break
                if new_sr.n_unknown < best_unk or new_sr.coverage > best_cov + 0.001:
                    best = candidate
                    best_sr = new_sr
                    best_unk = new_sr.n_unknown
                    best_cov = new_sr.coverage
                    N_cur = compute_N(best)
                    improved = True
                    if context.verbose:
                        print(f"  Remove {outer+1:>3d}: ({my},{mx})  unknown={best_unk}  cov={best_cov:.4f}")
                    break
        if stop_reason.startswith("timeout"):
            break

        if not improved:
            no_improve_outer += 1
            if no_improve_outer >= 6:
                stop_reason = "stagnated"
                if context.verbose:
                    print(f"  Swap repair stagnated after {outer+1} outer iterations")
                break
        else:
            no_improve_outer = 0

    elapsed = now_s() - t_start
    if context.verbose:
        print(
            f"  Swap repair done: cov={best_cov:.4f}  unknown={best_unk}"
            f"  reason={stop_reason}  t={elapsed:.1f}s"
            f"  solve_calls={solve_calls}"
        )

    telemetry = {
        "solve_calls": solve_calls,
        "solve_time_s": round(solve_time_s, 4),
        "elapsed_s": round(elapsed, 3),
    }
    return RepairResult(grid=best, solve_result=best_sr, reason=stop_reason, telemetry=telemetry)

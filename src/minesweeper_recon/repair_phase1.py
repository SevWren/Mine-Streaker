from __future__ import annotations

import os

import numpy as np

from .models import RepairContext, RepairResult, SolveResult
from .runtime import BudgetExceeded, check_deadline, now_s


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

    max_rounds = context.max_rounds or 200
    search_radius = context.search_radius or 6
    checkpoint_every = context.checkpoint_every or 5
    deadline_s = context.deadline_s

    def solve_with_budget(board: np.ndarray) -> SolveResult:
        nonlocal solve_calls, solve_time_s
        check_deadline(deadline_s, "phase1_repair")
        ts = now_s()
        sr_local = context.solve_fn(board, deadline_s)
        solve_calls += 1
        solve_time_s += now_s() - ts
        return sr_local

    try:
        sr = solve_with_budget(best)
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
            reason="timeout (0s)",
            telemetry={"solve_calls": solve_calls, "solve_time_s": round(solve_time_s, 4)},
        )

    best_sr = sr
    best_cov = sr.coverage
    best_unk = sr.n_unknown

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

        try:
            sr = solve_with_budget(best)
        except BudgetExceeded:
            stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
            break

        unknown_list = list(sr.unknown)
        if not unknown_list:
            stop_reason = "no_unknowns"
            break

        cand_score: dict[tuple[int, int], int] = {}
        for u_i, (uy, ux) in enumerate(unknown_list):
            if u_i % 32 == 0:
                if now_s() >= deadline_s:
                    stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                    break
            for dy in range(-search_radius, search_radius + 1):
                for dx in range(-search_radius, search_radius + 1):
                    ny, nx = uy + dy, ux + dx
                    if 0 <= ny < H and 0 <= nx < W and best[ny, nx] == 1 and forbidden[ny, nx] == 0:
                        cand_score[(ny, nx)] = cand_score.get((ny, nx), 0) + 1
        if stop_reason.startswith("timeout"):
            break

        if not cand_score:
            stop_reason = "no_candidates"
            break

        avg_solve_s = solve_time_s / max(solve_calls, 1)
        remaining_s = max(0.0, deadline_s - now_s())
        affordable_solves = max(1, int(remaining_s / max(avg_solve_s, 0.05)))
        eval_cap = min(12, max(1, affordable_solves - 2))
        top_cap = min(160, max(40, eval_cap * 10))

        top = sorted(cand_score.items(), key=lambda x: -x[1])[:top_cap]
        scored = []
        for t_i, ((cy, cx), _) in enumerate(top):
            if t_i % 16 == 0 and now_s() >= deadline_s:
                stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                break
            n_unk_near = sum(1 for (uy, ux) in unknown_list if abs(uy - cy) <= 2 and abs(ux - cx) <= 2)
            scored.append(((cy, cx), best_cov + n_unk_near / (H * W)))
        if stop_reason.startswith("timeout"):
            break

        scored.sort(key=lambda x: -x[1])

        accepted = None
        for (cy, cx), _ in scored[:eval_cap]:
            cand = best.copy()
            cand[cy, cx] = 0
            try:
                new_sr = solve_with_budget(cand)
            except BudgetExceeded:
                stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                break
            if new_sr.coverage >= best_cov - 0.0001:
                if new_sr.n_unknown < best_unk or new_sr.coverage > best_cov + 0.0001:
                    accepted = (cand, new_sr)
                    break
        if stop_reason.startswith("timeout"):
            break

        if accepted is None and scored:
            (cy, cx), _ = scored[0]
            cand = best.copy()
            cand[cy, cx] = 0
            try:
                new_sr = solve_with_budget(cand)
            except BudgetExceeded:
                stop_reason = f"timeout ({now_s()-t_start:.0f}s)"
                break
            if new_sr.coverage >= best_cov - 0.0001:
                accepted = (cand, new_sr)

        if accepted:
            best, new_sr = accepted
            best_sr = new_sr
            best_cov = new_sr.coverage
            best_unk = new_sr.n_unknown
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

    if context.verbose:
        print(
            f"  Repair done: cov={best_cov:.4f}  unknown={best_unk}"
            f"  reason={stop_reason}  t={now_s()-t_start:.1f}s"
            f"  solve_calls={solve_calls}"
        )

    telemetry = {
        "solve_calls": solve_calls,
        "solve_time_s": round(solve_time_s, 4),
        "elapsed_s": round(now_s() - t_start, 3),
    }
    return RepairResult(grid=best, solve_result=best_sr, reason=stop_reason, telemetry=telemetry)

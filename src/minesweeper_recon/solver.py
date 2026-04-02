from __future__ import annotations

import time

import numpy as np

from .core import compute_N, get_neighbor_table, nbrs
from .models import SolveResult
from .runtime import check_deadline


def _init_sort_stats() -> dict[str, float | int]:
    return {"sort_calls": 0, "sort_items": 0, "sort_time_s": 0.0}


def _sorted_timed(values, stats: dict[str, float | int]):
    t0 = time.perf_counter()
    out = sorted(values)
    stats["sort_calls"] = int(stats["sort_calls"]) + 1
    stats["sort_items"] = int(stats["sort_items"]) + len(out)
    stats["sort_time_s"] = float(stats["sort_time_s"]) + (time.perf_counter() - t0)
    return out


def _ordered_cells(cells, deterministic: bool, stats: dict[str, float | int]):
    if deterministic:
        return _sorted_timed(cells, stats)
    return list(cells)


def _iter_diff(diff, deterministic: bool, stats: dict[str, float | int]):
    if deterministic:
        return _sorted_timed(diff, stats)
    return diff


def _solve_board_legacy(
    grid: np.ndarray,
    max_rounds: int = 300,
    verbose: bool = False,
    deadline_s=None,
    deterministic: bool = False,
) -> SolveResult:
    check_deadline(deadline_s, "solve_board")
    sort_stats = _init_sort_stats()
    H, W = grid.shape
    N = compute_N(grid)
    mines_set = set(map(tuple, np.argwhere(grid == 1)))
    safe_set = set(map(tuple, np.argwhere(grid == 0)))

    revealed: set[tuple[int, int]] = set()
    flagged: set[tuple[int, int]] = set()

    def reveal_bfs(y0, x0):
        if (y0, x0) in revealed or grid[y0, x0] == 1:
            return
        q = [(y0, x0)]
        q_steps = 0
        while q:
            q_steps += 1
            if q_steps % 64 == 0:
                check_deadline(deadline_s, "solve_board_bfs")
            cy, cx = q.pop()
            if (cy, cx) in revealed:
                continue
            revealed.add((cy, cx))
            if N[cy, cx] == 0:
                for ny, nx in nbrs(cy, cx, H, W):
                    if (ny, nx) not in revealed and grid[ny, nx] == 0:
                        q.append((ny, nx))

    zeros = np.argwhere((grid == 0) & (N == 0))
    for zi, (y, x) in enumerate(zeros):
        if zi % 64 == 0:
            check_deadline(deadline_s, "solve_board_zero_seed")
        reveal_bfs(int(y), int(x))

    for rnd in range(max_rounds):
        check_deadline(deadline_s, "solve_board_round")
        changed = False
        constraints = []

        for r_i, (ry, rx) in enumerate(_ordered_cells(revealed, deterministic, sort_stats)):
            if r_i % 64 == 0:
                check_deadline(deadline_s, "solve_board_revealed_scan")
            if grid[ry, rx] == 1:
                continue
            num = int(N[ry, rx])
            unkn = [(ny, nx) for ny, nx in nbrs(ry, rx, H, W) if (ny, nx) not in revealed and (ny, nx) not in flagged]
            flgd = [(ny, nx) for ny, nx in nbrs(ry, rx, H, W) if (ny, nx) in flagged]
            rem = num - len(flgd)

            if rem == len(unkn) and rem > 0:
                for c in unkn:
                    if c not in flagged:
                        flagged.add(c)
                        changed = True
            if rem == 0 and unkn:
                for c in unkn:
                    if grid[c[0], c[1]] == 0:
                        reveal_bfs(c[0], c[1])
                        changed = True

            if unkn and 0 <= rem <= len(unkn):
                constraints.append((frozenset(unkn), rem))

        if len(constraints) < 5000:
            for i, (si, ri) in enumerate(constraints):
                if i % 16 == 0:
                    check_deadline(deadline_s, "solve_board_subset")
                for j, (sj, rj) in enumerate(constraints):
                    if i >= j:
                        continue
                    if si < sj:
                        diff = sj - si
                        rdiff = rj - ri
                        if len(diff) > 0:
                            if rdiff == len(diff):
                                for c in _iter_diff(diff, deterministic, sort_stats):
                                    if c not in flagged:
                                        flagged.add(c)
                                        changed = True
                            elif rdiff == 0:
                                for c in _iter_diff(diff, deterministic, sort_stats):
                                    if grid[c[0], c[1]] == 0:
                                        reveal_bfs(c[0], c[1])
                                        changed = True

        if verbose:
            print(f"  Solver round {rnd}: revealed={len(revealed)}, flagged={len(flagged)}")
        if not changed:
            break

    unknown = safe_set - revealed
    cov = len(revealed & safe_set) / max(len(safe_set), 1)
    solvable = cov >= 0.999 and flagged >= mines_set
    return SolveResult(
        solvable=solvable,
        revealed=revealed,
        flagged=flagged,
        unknown=unknown,
        coverage=round(cov, 4),
        mine_accuracy=round(len(flagged & mines_set) / max(len(mines_set), 1), 4),
        n_unknown=len(unknown),
        sort_calls=int(sort_stats["sort_calls"]),
        sort_items=int(sort_stats["sort_items"]),
        sort_time_s=round(float(sort_stats["sort_time_s"]), 6),
    )


def _solve_board_fast(
    grid: np.ndarray,
    max_rounds: int = 300,
    verbose: bool = False,
    deadline_s=None,
    deterministic: bool = False,
) -> SolveResult:
    check_deadline(deadline_s, "solve_board")
    sort_stats = _init_sort_stats()
    H, W = grid.shape
    N = compute_N(grid)
    neighbors = get_neighbor_table(H, W)
    mines_set = set(map(tuple, np.argwhere(grid == 1)))
    safe_set = set(map(tuple, np.argwhere(grid == 0)))

    revealed: set[tuple[int, int]] = set()
    flagged: set[tuple[int, int]] = set()

    def reveal_bfs(y0, x0):
        if (y0, x0) in revealed or grid[y0, x0] == 1:
            return
        q = [(y0, x0)]
        q_steps = 0
        while q:
            q_steps += 1
            if q_steps % 64 == 0:
                check_deadline(deadline_s, "solve_board_bfs")
            cy, cx = q.pop()
            if (cy, cx) in revealed:
                continue
            revealed.add((cy, cx))
            if N[cy, cx] == 0:
                for ny, nx in neighbors[cy][cx]:
                    if (ny, nx) not in revealed and grid[ny, nx] == 0:
                        q.append((ny, nx))

    zeros = np.argwhere((grid == 0) & (N == 0))
    for zi, (y, x) in enumerate(zeros):
        if zi % 64 == 0:
            check_deadline(deadline_s, "solve_board_zero_seed")
        reveal_bfs(int(y), int(x))

    for rnd in range(max_rounds):
        check_deadline(deadline_s, "solve_board_round")
        changed = False
        constraints_map: dict[frozenset[tuple[int, int]], int] = {}

        for r_i, (ry, rx) in enumerate(_ordered_cells(revealed, deterministic, sort_stats)):
            if r_i % 64 == 0:
                check_deadline(deadline_s, "solve_board_revealed_scan")
            if grid[ry, rx] == 1:
                continue
            num = int(N[ry, rx])
            unkn = []
            flg_count = 0
            for ny, nx in neighbors[ry][rx]:
                if (ny, nx) in flagged:
                    flg_count += 1
                elif (ny, nx) not in revealed:
                    unkn.append((ny, nx))
            rem = num - flg_count

            if rem == len(unkn) and rem > 0:
                for c in unkn:
                    if c not in flagged:
                        flagged.add(c)
                        changed = True
            if rem == 0 and unkn:
                for c in unkn:
                    if grid[c[0], c[1]] == 0:
                        reveal_bfs(c[0], c[1])
                        changed = True

            if unkn and 0 <= rem <= len(unkn):
                key = frozenset(unkn)
                if key not in constraints_map:
                    constraints_map[key] = rem

        constraints = list(constraints_map.items())
        if constraints:
            constraints.sort(key=lambda item: len(item[0]))
            subset_cap = 2400 if deadline_s is None else 1200
            if len(constraints) > subset_cap:
                constraints = constraints[:subset_cap]

            sizes = [len(si) for si, _ in constraints]
            n_constraints = len(constraints)
            for i in range(n_constraints):
                if i % 16 == 0:
                    check_deadline(deadline_s, "solve_board_subset")
                si, ri = constraints[i]
                si_len = sizes[i]
                if si_len == 0:
                    continue
                for j in range(i + 1, n_constraints):
                    if sizes[j] == si_len:
                        continue
                    sj, rj = constraints[j]
                    if si.issubset(sj):
                        diff = sj - si
                        rdiff = rj - ri
                        if len(diff) > 0:
                            if rdiff == len(diff):
                                for c in _iter_diff(diff, deterministic, sort_stats):
                                    if c not in flagged:
                                        flagged.add(c)
                                        changed = True
                            elif rdiff == 0:
                                for c in _iter_diff(diff, deterministic, sort_stats):
                                    if grid[c[0], c[1]] == 0:
                                        reveal_bfs(c[0], c[1])
                                        changed = True

        if verbose:
            print(f"  Solver round {rnd}: revealed={len(revealed)}, flagged={len(flagged)}")
        if not changed:
            break

    unknown = safe_set - revealed
    cov = len(revealed & safe_set) / max(len(safe_set), 1)
    solvable = cov >= 0.999 and flagged >= mines_set
    return SolveResult(
        solvable=solvable,
        revealed=revealed,
        flagged=flagged,
        unknown=unknown,
        coverage=round(cov, 4),
        mine_accuracy=round(len(flagged & mines_set) / max(len(mines_set), 1), 4),
        n_unknown=len(unknown),
        sort_calls=int(sort_stats["sort_calls"]),
        sort_items=int(sort_stats["sort_items"]),
        sort_time_s=round(float(sort_stats["sort_time_s"]), 6),
    )


def solve_board(
    grid: np.ndarray,
    max_rounds: int = 300,
    verbose: bool = False,
    deadline_s=None,
    mode: str = "fast",
    deterministic: bool = False,
) -> SolveResult:
    if mode == "legacy":
        return _solve_board_legacy(
            grid=grid,
            max_rounds=max_rounds,
            verbose=verbose,
            deadline_s=deadline_s,
            deterministic=deterministic,
        )
    return _solve_board_fast(
        grid=grid,
        max_rounds=max_rounds,
        verbose=verbose,
        deadline_s=deadline_s,
        deterministic=deterministic,
    )

from __future__ import annotations

import numpy as np

from .core import compute_N, nbrs
from .models import SolveResult
from .runtime import check_deadline


def solve_board(grid: np.ndarray, max_rounds: int = 300, verbose: bool = False, deadline_s=None) -> SolveResult:
    """
    Full CSP Minesweeper solver:
      1. Flood-fill BFS from all zero-N cells
      2. Basic constraint propagation (count matching)
      3. Subset propagation (A < B -> mines(B\\A) = mines(B)-mines(A))
    """
    check_deadline(deadline_s, "solve_board")
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

        for r_i, (ry, rx) in enumerate(list(revealed)):
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
                                for c in diff:
                                    if c not in flagged:
                                        flagged.add(c)
                                        changed = True
                            elif rdiff == 0:
                                for c in diff:
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
    )

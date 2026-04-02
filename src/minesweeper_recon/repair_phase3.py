from __future__ import annotations

import time
from itertools import product as iproduct

from .core import compute_N, nbrs
from .models import RepairContext, RepairResult


def run_phase3_enumeration(context: RepairContext) -> RepairResult:
    grid = context.grid
    sr = context.initial_solve_result
    if sr is None:
        sr = context.solve_fn(grid, context.deadline_s)

    unknown_list = list(sr.unknown)
    n_unk = len(unknown_list)

    max_unknown = context.max_unknown or 25

    if n_unk == 0:
        return RepairResult(grid=grid, solve_result=sr, reason="already_solved")
    if n_unk > max_unknown:
        return RepairResult(grid=grid, solve_result=sr, reason=f"too_many_unknowns ({n_unk})")

    if context.verbose:
        print(f"\n  [Enumeration]  {n_unk} unknown cells  enumerating {2**n_unk:,} configs")

    H, W = grid.shape
    N_grid = compute_N(grid)
    unknown_set = set(unknown_list)
    revealed = sr.revealed
    flagged = sr.flagged

    cell_to_idx = {cell: i for i, cell in enumerate(unknown_list)}
    constraints = []
    for (ry, rx) in revealed:
        if grid[ry, rx] == 1:
            continue
        num = int(N_grid[ry, rx])
        unk_nbrs = [(ny, nx) for ny, nx in nbrs(ry, rx, H, W) if (ny, nx) in unknown_set]
        if not unk_nbrs:
            continue
        flg_nbrs = sum(1 for ny, nx in nbrs(ry, rx, H, W) if (ny, nx) in flagged)
        remaining = num - flg_nbrs
        constraints.append((unk_nbrs, remaining))

    valid_configs = []
    t_enum = time.time()
    for cfg in iproduct([0, 1], repeat=n_unk):
        valid = True
        for (unk_nbrs, remaining) in constraints:
            mines = sum(cfg[cell_to_idx[c]] for c in unk_nbrs)
            if mines != remaining:
                valid = False
                break
        if valid:
            valid_configs.append(cfg)
        if time.time() - t_enum > 30:
            if context.verbose:
                print(f"  Enumeration timed out at {2**n_unk} configs")
            return RepairResult(grid=grid, solve_result=sr, reason="enum_timeout")

    if context.verbose:
        print(f"  Found {len(valid_configs)} valid configurations for {n_unk} unknowns")

    if len(valid_configs) == 0:
        return RepairResult(grid=grid, solve_result=sr, reason="no_valid_config")

    if len(valid_configs) == 1:
        if context.verbose:
            print("  Unique config found! Forcing it onto board.")
        new_grid = grid.copy()
        for i, (uy, ux) in enumerate(unknown_list):
            new_grid[uy, ux] = valid_configs[0][i]
        new_sr = context.solve_fn(new_grid, context.deadline_s)
        return RepairResult(grid=new_grid, solve_result=new_sr, reason="forced_unique")

    ambiguous_cells = []
    for i in range(n_unk):
        vals = set(cfg[i] for cfg in valid_configs)
        if len(vals) > 1:
            ambiguous_cells.append(i)

    if context.verbose:
        print(f"  {len(ambiguous_cells)}/{n_unk} cells are genuinely ambiguous")
        print(f"  Ambiguous cells: {[unknown_list[i] for i in ambiguous_cells]}")

    best = grid.copy()
    best_sr = sr
    best_unk = n_unk

    for amb_idx in ambiguous_cells:
        uy, ux = unknown_list[amb_idx]
        if context.verbose:
            print(f"  Trying to resolve ambiguous cell ({uy},{ux}) ...")

        for dy in range(-2, 3):
            for dx in range(-2, 3):
                ty, tx = uy + dy, ux + dx
                if not (0 <= ty < H and 0 <= tx < W):
                    continue
                if best[ty, tx] == 1:
                    continue
                if context.forbidden[ty, tx] == 1:
                    continue
                if (ty, tx) in unknown_set:
                    continue

                N_c = compute_N(best)
                for ny, nx in nbrs(ty, tx, H, W):
                    if N_c[ny, nx] + 1 > 8:
                        break
                else:
                    candidate = best.copy()
                    candidate[ty, tx] = 1
                    new_sr = context.solve_fn(candidate, context.deadline_s)
                    if new_sr.n_unknown < best_unk:
                        best = candidate
                        best_sr = new_sr
                        best_unk = new_sr.n_unknown
                        if context.verbose:
                            print(f"    Added mine at ({ty},{tx})  unknown={best_unk}")
                        break
        if best_unk == 0:
            break

    new_reason = f"enum_resolved_{n_unk - best_unk}_of_{n_unk}"
    return RepairResult(grid=best, solve_result=best_sr, reason=new_reason)

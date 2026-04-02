from __future__ import annotations

import numpy as np

from .core import compute_N
from .models import SolveResult


def analyze_unknowns(grid, sr: SolveResult, target, label=""):
    unknown_list = list(sr.unknown)
    n_unk = len(unknown_list)
    if n_unk == 0:
        print(f"  [{label}] No unknowns  board is SOLVABLE!")
        return

    H, W = grid.shape
    N = compute_N(grid)

    unknown_set = set(unknown_list)
    visited = set()
    clusters = []
    for start in unknown_list:
        if start in visited:
            continue
        cluster = []
        q = [start]
        while q:
            cell = q.pop()
            if cell in visited:
                continue
            visited.add(cell)
            cluster.append(cell)
            y, x = cell
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    nb = (y + dy, x + dx)
                    if nb in unknown_set and nb not in visited:
                        q.append(nb)
        clusters.append(cluster)

    print(f"\n  [{label}] Unknown cell analysis:")
    print(f"    Total unknowns: {n_unk}")
    print(f"    Clusters: {len(clusters)}")
    for i, cl in enumerate(clusters[:8]):
        n_vals = [float(N[y, x]) for y, x in cl]
        t_vals = [float(target[y, x]) for y, x in cl]
        mines_in_cluster = sum(int(grid[y, x]) for y, x in cl)
        print(
            f"    Cluster {i+1}: size={len(cl)}"
            f"  mines={mines_in_cluster}"
            f"  N_mean={np.mean(n_vals):.1f}"
            f"  T_mean={np.mean(t_vals):.1f}"
            f"  cells={cl[:3]}{'...' if len(cl)>3 else ''}"
        )
    if len(clusters) > 8:
        print(f"    ... and {len(clusters)-8} more clusters")

from __future__ import annotations

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import minimum_spanning_tree


def build_adaptive_corridors(target, border=3, corridor_width=0, low_target_bias=5.0):
    H, W = target.shape
    spacing = max(5, int(np.sqrt(H * W) // 10))
    ys = list(range(border, H - border, spacing))
    xs = list(range(border, W - border, spacing))
    if H - border - 1 not in ys:
        ys.append(H - border - 1)
    if W - border - 1 not in xs:
        xs.append(W - border - 1)
    seeds = [(y, x) for y in ys for x in xs]
    n = len(seeds)

    def path_cost(y0, x0, y1, x1):
        length = max(abs(y1 - y0), abs(x1 - x0), 1)
        yp = np.clip(np.round(np.linspace(y0, y1, length + 1)).astype(int), 0, H - 1)
        xp = np.clip(np.round(np.linspace(x0, x1, length + 1)).astype(int), 0, W - 1)
        return float(target[yp, xp].mean())

    rows, cols, data = [], [], []
    for i in range(n):
        for j in range(i + 1, n):
            y0, x0 = seeds[i]
            y1, x1 = seeds[j]
            dist = np.sqrt((y1 - y0) ** 2 + (x1 - x0) ** 2)
            if dist <= 2.5 * spacing:
                w = path_cost(y0, x0, y1, x1) ** low_target_bias + dist * 0.01
                rows.append(i)
                cols.append(j)
                data.append(w)

    if not data:
        for i in range(n):
            for j in range(i + 1, n):
                y0, x0 = seeds[i]
                y1, x1 = seeds[j]
                dist = np.sqrt((y1 - y0) ** 2 + (x1 - x0) ** 2)
                w = path_cost(y0, x0, y1, x1) ** low_target_bias + dist * 0.01
                rows.append(i)
                cols.append(j)
                data.append(w)

    G = csr_matrix((data, (rows, cols)), shape=(n, n))
    mst = minimum_spanning_tree(G).tocoo()

    mask = np.zeros((H, W), dtype=bool)
    mask[:border, :] = True
    mask[-border:, :] = True
    mask[:, :border] = True
    mask[:, -border:] = True

    for i, j in zip(mst.row, mst.col):
        y0, x0 = seeds[i]
        y1, x1 = seeds[j]
        length = max(abs(y1 - y0), abs(x1 - x0), 1)
        yp = np.clip(np.round(np.linspace(y0, y1, length + 1)).astype(int), 0, H - 1)
        xp = np.clip(np.round(np.linspace(x0, x1, length + 1)).astype(int), 0, W - 1)
        for yc, xc in zip(yp, xp):
            for dy in range(-corridor_width, corridor_width + 1):
                for dx in range(-corridor_width, corridor_width + 1):
                    ny, nx = yc + dy, xc + dx
                    if 0 <= ny < H and 0 <= nx < W:
                        mask[ny, nx] = True

    return mask.astype(np.int8), round(100 * mask.mean(), 2), seeds, mst

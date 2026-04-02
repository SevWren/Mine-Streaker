from __future__ import annotations

import time

import numpy as np


def compile_sa_kernel():
    from numba import njit

    @njit(cache=False, fastmath=True)
    def _sa_masked(grid, N, target, weights, forbidden, T, alpha, T_min, max_iter, border, H, W, seed):
        np.random.seed(seed)
        best_grid = grid.copy()
        best_loss = 0.0
        for y in range(H):
            for x in range(W):
                d = N[y, x] - target[y, x]
                best_loss += weights[y, x] * d * d
        current_loss = best_loss

        hist_size = max_iter // 50000 + 4
        history = np.zeros(hist_size, dtype=np.float64)
        hi = 0
        history[hi] = best_loss
        hi += 1

        for i in range(max_iter):
            y = np.random.randint(0, H)
            x = np.random.randint(0, W)

            if forbidden[y, x] == 1 and grid[y, x] == 0:
                continue
            if y < border or y >= H - border or x < border or x >= W - border:
                if grid[y, x] == 0:
                    continue

            sign = 1 - 2 * int(grid[y, x])
            d_loss = 0.0
            valid = True

            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    if dy == 0 and dx == 0:
                        continue
                    ny = y + dy
                    nx = x + dx
                    if 0 <= ny < H and 0 <= nx < W:
                        n_new = N[ny, nx] + sign
                        if n_new < 0.0 or n_new > 8.0:
                            valid = False
                            break
                        diff_new = n_new - target[ny, nx]
                        diff_cur = N[ny, nx] - target[ny, nx]
                        d_loss += weights[ny, nx] * (diff_new * diff_new - diff_cur * diff_cur)
                if not valid:
                    break

            if not valid:
                continue
            if sign > 0 and forbidden[y, x] == 1:
                continue

            accept = d_loss < 0.0 or np.random.random() < np.exp(-d_loss / (T + 1e-12))
            if accept:
                grid[y, x] = 1 if sign > 0 else 0
                for dy in range(-1, 2):
                    for dx in range(-1, 2):
                        if dy == 0 and dx == 0:
                            continue
                        ny = y + dy
                        nx = x + dx
                        if 0 <= ny < H and 0 <= nx < W:
                            N[ny, nx] += sign
                current_loss += d_loss
                if current_loss < best_loss:
                    best_loss = current_loss
                    for yy in range(H):
                        for xx in range(W):
                            best_grid[yy, xx] = grid[yy, xx]

            T = T * alpha
            if T < T_min:
                T = T_min
            if i % 50000 == 0 and i > 0 and hi < hist_size:
                history[hi] = best_loss
                hi += 1

        return best_grid, best_loss, history[:hi]

    print("  Compiling SA kernel ", end=" ", flush=True)
    t0 = time.time()
    _g = np.zeros((8, 8), dtype=np.int8)
    _z = np.zeros((8, 8), dtype=np.float32)
    _f = np.zeros((8, 8), dtype=np.int8)
    _w = np.ones((8, 8), dtype=np.float32)
    r = _sa_masked(_g.copy(), _z.copy(), _z, _w, _f, 1.0, 0.999, 0.01, 200, 1, 8, 8, 0)
    assert r[0].shape == (8, 8)
    print(f"OK ({time.time()-t0:.1f}s)")
    return _sa_masked

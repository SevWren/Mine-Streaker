from __future__ import annotations

import multiprocessing as mp
import os
import threading
import time

import numpy as np


def _compile_heartbeat_process(stop_evt, started_at: float, interval_s: float) -> None:
    """
    Out-of-process heartbeat so progress messages still print when the main
    process is blocked inside numba/LLVM compilation.
    """
    while not stop_evt.wait(interval_s):
        elapsed = max(0.0, time.time() - started_at)
        print(
            f"    ... SA kernel still compiling ({elapsed:.0f}s elapsed, parent pid={os.getppid()})",
            flush=True,
        )


def _start_compile_heartbeat(started_at: float, interval_s: float = 10.0):
    """
    Returns a stop callback. Uses a subprocess heartbeat on Windows to avoid
    GIL starvation; falls back to thread heartbeat if process startup fails.
    """
    try:
        stop_evt = mp.Event()
        proc = mp.Process(
            target=_compile_heartbeat_process,
            args=(stop_evt, started_at, interval_s),
            daemon=True,
        )
        proc.start()

        def _stop() -> None:
            stop_evt.set()
            proc.join(timeout=0.5)
            if proc.is_alive():
                proc.terminate()

        return _stop
    except Exception:
        stop_evt = threading.Event()

        def _heartbeat_thread() -> None:
            while not stop_evt.wait(interval_s):
                elapsed = max(0.0, time.time() - started_at)
                print(f"    ... SA kernel still compiling ({elapsed:.0f}s elapsed)", flush=True)

        hb = threading.Thread(target=_heartbeat_thread, daemon=True)
        hb.start()

        def _stop() -> None:
            stop_evt.set()
            hb.join(timeout=0.1)

        return _stop


def compile_sa_kernel():
    t_start = time.time()
    print("  SA kernel: importing numba ...", flush=True)
    t_numba = time.time()
    from numba import __version__ as numba_version
    from numba import njit
    numba_import_s = time.time() - t_numba

    print(
        f"  SA kernel: numba import OK ({numba_import_s:.2f}s, version={numba_version})",
        flush=True,
    )

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

    print("  SA kernel: preparing warmup buffers", flush=True)
    t0 = time.time()
    _g = np.zeros((8, 8), dtype=np.int8)
    _z = np.zeros((8, 8), dtype=np.float32)
    _f = np.zeros((8, 8), dtype=np.int8)
    _w = np.ones((8, 8), dtype=np.float32)
    print(
        "  Compiling SA kernel (first warmup call may take 1-5 min on some systems)",
        flush=True,
    )
    print("  SA kernel: JIT warmup call start", flush=True)

    stop_heartbeat = _start_compile_heartbeat(started_at=t0, interval_s=10.0)
    try:
        r = _sa_masked(_g.copy(), _z.copy(), _z, _w, _f, 1.0, 0.999, 0.01, 200, 1, 8, 8, 0)
    finally:
        stop_heartbeat()
    assert r[0].shape == (8, 8)
    print(f"  SA kernel: JIT warmup call OK ({time.time() - t0:.1f}s)", flush=True)
    print(f"  SA kernel compile OK (total {time.time() - t_start:.1f}s)", flush=True)
    return _sa_masked

"""
ITERATION 10 — Mine-Swap Repair for Solvability
================================================
Central goal: achieve solvable=True for the first time in the project.

Root cause of persistent solvable=False (from Iter 9 analysis):
  - Remaining unknown cells form symmetric 50/50 configurations
  - Standard repair (remove-only) cannot break these symmetries
  - To break a 50/50: you must CHANGE which mine creates the asymmetric
    constraint, not just remove it. Like unscrambling a combination lock
    by turning digits, not removing them.

New component — Mine-Swap Repair (Phase 2 repair):
  Instead of: remove mine near unknown → re-solve
  Now:        remove mine A near unknown + add mine B at position that
              neighbors the unknown cluster asymmetrically → re-solve
              Accept if n_unknown decreases.

Also new:
  - Ambiguity cluster enumeration: for small unknown sets (≤30 cells),
    enumerate all valid mine assignments and determine which cells can
    be uniquely resolved.
  - Dynamic repair budget: budget_s = n_unknown_at_start × 0.15 + 30
  - Detailed unknown-cell diagnostics after each repair phase
"""

import sys
sys.path.insert(0, '/home/claude/minesweeper')

import numpy as np
import scipy.ndimage as ndi
from scipy.ndimage import convolve, gaussian_filter, sobel
from scipy.sparse.csgraph import minimum_spanning_tree
from scipy.sparse import csr_matrix
from PIL import Image as PILImage
import time, json, os, shutil
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from collections import deque
from itertools import product as iproduct

OUT  = '/home/claude/minesweeper/results'
IMG  = '/mnt/user-data/uploads/input_source_image-left.png'
os.makedirs(OUT, exist_ok=True)

print("=" * 68)
print("ITERATION 10  —  Mine-Swap Repair for Solvability")
print("=" * 68)

# ═══════════════════════════════════════════════════════════════════════════════
# CORE MATH
# ═══════════════════════════════════════════════════════════════════════════════

KERNEL = np.array([[1,1,1],[1,0,1],[1,1,1]], dtype=np.float32)

def compute_N(grid: np.ndarray) -> np.ndarray:
    """Count mines in 3×3 neighborhood of each cell (excluding center)."""
    return convolve(grid.astype(np.float32), KERNEL, mode='constant', cval=0)

def load_image_smart(path, board_w, board_h, panel='full', invert=True):
    img = PILImage.open(path).convert("L")
    W, H = img.size
    if panel == "left":
        img = img.crop((0, 0, W // 2, H))
    elif panel == "right":
        img = img.crop((W // 2, 0, W, H))
    from PIL import ImageEnhance
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.resize((board_w, board_h), PILImage.LANCZOS)
    arr = np.array(img, dtype=np.float32)
    if invert:
        arr = 255.0 - arr
    lo, hi = np.percentile(arr, 2), np.percentile(arr, 98)
    arr = np.clip((arr - lo) / (hi - lo + 1e-8), 0, 1) * 8.0
    return arr.astype(np.float32)

def compute_edge_weights(target, boost=4.0, sigma=1.0):
    blurred = gaussian_filter(target, sigma=sigma)
    sx = sobel(blurred, axis=1)
    sy = sobel(blurred, axis=0)
    mag = np.hypot(sx, sy)
    mag /= mag.max() + 1e-8
    return (1.0 + boost * mag).astype(np.float32)

def _nbrs(y, x, H, W):
    """Yield valid 8-neighbors of (y,x)."""
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            if dy == 0 and dx == 0: continue
            ny, nx = y+dy, x+dx
            if 0 <= ny < H and 0 <= nx < W:
                yield ny, nx


# ═══════════════════════════════════════════════════════════════════════════════
# SOLVER  (with subset constraint propagation)
# ═══════════════════════════════════════════════════════════════════════════════

def solve_board(grid: np.ndarray, max_rounds: int = 300,
                verbose: bool = False) -> dict:
    """
    Full CSP Minesweeper solver:
      1. Flood-fill BFS from all zero-N cells
      2. Basic constraint propagation (count matching)
      3. Subset propagation (A ⊂ B → mines(B\A) = mines(B)-mines(A))
    Returns dict with: solvable, revealed, flagged, unknown, coverage,
                       mine_accuracy, n_unknown
    """
    H, W = grid.shape
    N = compute_N(grid)
    mines_set = set(map(tuple, np.argwhere(grid == 1)))
    safe_set  = set(map(tuple, np.argwhere(grid == 0)))

    revealed: set = set()
    flagged:  set = set()

    def reveal_bfs(y0, x0):
        if (y0,x0) in revealed or grid[y0,x0] == 1:
            return
        q = [(y0, x0)]
        while q:
            cy, cx = q.pop()
            if (cy,cx) in revealed:
                continue
            revealed.add((cy, cx))
            if N[cy, cx] == 0:
                for ny, nx in _nbrs(cy, cx, H, W):
                    if (ny,nx) not in revealed and grid[ny,nx] == 0:
                        q.append((ny, nx))

    # Seed: ALL zero-N safe cells (generous — solver finds any reachable zero)
    zeros = np.argwhere((grid == 0) & (N == 0))
    for y, x in zeros:
        reveal_bfs(int(y), int(x))

    for rnd in range(max_rounds):
        changed = False
        constraints = []

        for (ry, rx) in list(revealed):
            if grid[ry, rx] == 1:
                continue
            num = int(N[ry, rx])
            unkn = [(ny, nx) for ny, nx in _nbrs(ry, rx, H, W)
                    if (ny,nx) not in revealed and (ny,nx) not in flagged]
            flgd = [(ny, nx) for ny, nx in _nbrs(ry, rx, H, W)
                    if (ny,nx) in flagged]
            rem = num - len(flgd)

            if rem == len(unkn) and rem > 0:
                for c in unkn:
                    if c not in flagged:
                        flagged.add(c); changed = True
            if rem == 0 and unkn:
                for c in unkn:
                    if grid[c[0],c[1]] == 0:
                        reveal_bfs(c[0], c[1]); changed = True

            if unkn and 0 <= rem <= len(unkn):
                constraints.append((frozenset(unkn), rem))

        # Subset propagation
        if len(constraints) < 5000:
            for i, (si, ri) in enumerate(constraints):
                for j, (sj, rj) in enumerate(constraints):
                    if i >= j: continue
                    if si < sj:
                        diff = sj - si; rdiff = rj - ri
                        if len(diff) > 0:
                            if rdiff == len(diff):
                                for c in diff:
                                    if c not in flagged:
                                        flagged.add(c); changed = True
                            elif rdiff == 0:
                                for c in diff:
                                    if grid[c[0],c[1]] == 0:
                                        reveal_bfs(c[0], c[1]); changed = True

        if verbose:
            print(f"  Solver round {rnd}: revealed={len(revealed)}, flagged={len(flagged)}")
        if not changed:
            break

    unknown = safe_set - revealed
    cov = len(revealed & safe_set) / max(len(safe_set), 1)
    solvable = cov >= 0.999 and flagged >= mines_set
    return {
        "solvable":      solvable,
        "revealed":      revealed,
        "flagged":       flagged,
        "unknown":       unknown,
        "coverage":      round(cov, 4),
        "mine_accuracy": round(len(flagged & mines_set) / max(len(mines_set), 1), 4),
        "n_unknown":     len(unknown),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# NUMBA SA KERNEL (masked — from iter9)
# ═══════════════════════════════════════════════════════════════════════════════

def compile_sa_kernel():
    from numba import njit

    @njit(cache=False, fastmath=True)
    def _sa_masked(grid, N, target, weights, forbidden,
                   T, alpha, T_min, max_iter, border, H, W, seed):
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
        hi = 0; history[hi] = best_loss; hi += 1

        for i in range(max_iter):
            y = np.random.randint(0, H)
            x = np.random.randint(0, W)

            if forbidden[y, x] == 1 and grid[y, x] == 0:
                continue
            if y < border or y >= H-border or x < border or x >= W-border:
                if grid[y, x] == 0:
                    continue

            sign = 1 - 2 * int(grid[y, x])
            d_loss = 0.0; valid = True

            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    if dy == 0 and dx == 0: continue
                    ny = y+dy; nx = x+dx
                    if 0 <= ny < H and 0 <= nx < W:
                        n_new = N[ny, nx] + sign
                        if n_new < 0.0 or n_new > 8.0:
                            valid = False; break
                        diff_new = n_new - target[ny, nx]
                        diff_cur = N[ny, nx] - target[ny, nx]
                        d_loss += weights[ny, nx] * (diff_new*diff_new - diff_cur*diff_cur)
                if not valid: break

            if not valid: continue
            if sign > 0 and forbidden[y, x] == 1: continue

            accept = d_loss < 0.0 or np.random.random() < np.exp(-d_loss / (T + 1e-12))
            if accept:
                grid[y, x] = 1 if sign > 0 else 0
                for dy in range(-1, 2):
                    for dx in range(-1, 2):
                        if dy == 0 and dx == 0: continue
                        ny = y+dy; nx = x+dx
                        if 0 <= ny < H and 0 <= nx < W:
                            N[ny, nx] += sign
                current_loss += d_loss
                if current_loss < best_loss:
                    best_loss = current_loss
                    for yy in range(H):
                        for xx in range(W):
                            best_grid[yy, xx] = grid[yy, xx]

            T = T * alpha
            if T < T_min: T = T_min
            if i % 50000 == 0 and i > 0 and hi < hist_size:
                history[hi] = best_loss; hi += 1

        return best_grid, best_loss, history[:hi]

    print("  Compiling SA kernel …", end=" ", flush=True)
    t0 = time.time()
    _g = np.zeros((8, 8), dtype=np.int8)
    _z = np.zeros((8, 8), dtype=np.float32)
    _f = np.zeros((8, 8), dtype=np.int8)
    _w = np.ones((8, 8), dtype=np.float32)
    r = _sa_masked(_g.copy(), _z.copy(), _z, _w, _f, 1.0, 0.999, 0.01, 200, 1, 8, 8, 0)
    assert r[0].shape == (8, 8)
    print(f"OK ({time.time()-t0:.1f}s)")
    return _sa_masked


# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTIVE CORRIDORS (from iter9)
# ═══════════════════════════════════════════════════════════════════════════════

def build_adaptive_corridors(target, border=3, corridor_width=0, low_target_bias=5.5):
    H, W = target.shape
    spacing = max(5, int(np.sqrt(H * W) // 10))
    ys = list(range(border, H-border, spacing))
    xs = list(range(border, W-border, spacing))
    if H-border-1 not in ys: ys.append(H-border-1)
    if W-border-1 not in xs: xs.append(W-border-1)
    seeds = [(y, x) for y in ys for x in xs]
    n = len(seeds)

    def path_cost(y0, x0, y1, x1):
        length = max(abs(y1-y0), abs(x1-x0), 1)
        yp = np.clip(np.round(np.linspace(y0,y1,length+1)).astype(int), 0, H-1)
        xp = np.clip(np.round(np.linspace(x0,x1,length+1)).astype(int), 0, W-1)
        return float(target[yp, xp].mean())

    rows, cols, data = [], [], []
    for i in range(n):
        for j in range(i+1, n):
            y0,x0=seeds[i]; y1,x1=seeds[j]
            dist = np.sqrt((y1-y0)**2+(x1-x0)**2)
            if dist <= 2.5 * spacing:
                w = path_cost(y0,x0,y1,x1)**low_target_bias + dist*0.01
                rows.append(i); cols.append(j); data.append(w)

    if not data:
        for i in range(n):
            for j in range(i+1, n):
                y0,x0=seeds[i]; y1,x1=seeds[j]
                dist=np.sqrt((y1-y0)**2+(x1-x0)**2)
                w=path_cost(y0,x0,y1,x1)**low_target_bias+dist*0.01
                rows.append(i); cols.append(j); data.append(w)

    G = csr_matrix((data,(rows,cols)), shape=(n,n))
    mst = minimum_spanning_tree(G).tocoo()

    mask = np.zeros((H,W), dtype=bool)
    mask[:border,:]=True; mask[-border:,:]=True
    mask[:,:border]=True; mask[:,-border:]=True

    for i, j in zip(mst.row, mst.col):
        y0,x0=seeds[i]; y1,x1=seeds[j]
        length = max(abs(y1-y0),abs(x1-x0),1)
        yp = np.clip(np.round(np.linspace(y0,y1,length+1)).astype(int),0,H-1)
        xp = np.clip(np.round(np.linspace(x0,x1,length+1)).astype(int),0,W-1)
        for yc, xc in zip(yp, xp):
            for dy in range(-corridor_width, corridor_width+1):
                for dx in range(-corridor_width, corridor_width+1):
                    ny, nx = yc+dy, xc+dx
                    if 0 <= ny < H and 0 <= nx < W:
                        mask[ny, nx] = True

    return mask.astype(np.int8), round(100*mask.mean(), 2), seeds, mst


# ═══════════════════════════════════════════════════════════════════════════════
# BOARD VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

def assert_board_valid(grid, forbidden, label=""):
    tag = f"[{label}] " if label else ""
    N = compute_N(grid)
    assert set(np.unique(grid)).issubset({0,1}), f"{tag}grid values outside {{0,1}}"
    assert int(np.sum((grid==1)&(forbidden==1))) == 0, \
        f"{tag}{np.sum((grid==1)&(forbidden==1))} mines in forbidden cells"
    assert int(np.sum((N<0)|(N>8))) == 0, \
        f"{tag}N out of [0,8]: min={N.min()}, max={N.max()}"


# ═══════════════════════════════════════════════════════════════════════════════
# ATOMIC SAVES
# ═══════════════════════════════════════════════════════════════════════════════

def atomic_save_json(data, path):
    tmp = path + ".tmp"
    with open(tmp, 'w') as f: json.dump(data, f, indent=2)
    os.replace(tmp, path)

def atomic_save_npy(arr, path):
    tmp = path + ".tmp.npy"
    np.save(tmp, arr)
    os.replace(tmp, path)


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1 REPAIR: Bounded mine-removal repair (from iter9)
# ═══════════════════════════════════════════════════════════════════════════════

def bounded_repair(grid, target, weights, forbidden, label,
                   max_rounds=200, batch_size=10, search_radius=6,
                   time_budget_s=90.0, checkpoint_every=5,
                   verbose=True):
    H, W = grid.shape
    best = grid.copy()
    t_start = time.time()
    stop_reason = "max_rounds"

    sr = solve_board(best)
    best_cov  = sr['coverage']
    best_unk  = sr['n_unknown']

    ckpt_path = f"{OUT}/repair_ckpt_{label}.npy"
    if verbose:
        print(f"  Pre-repair: cov={best_cov:.4f}  unknown={best_unk}"
              f"  budget={time_budget_s:.0f}s")

    for rnd in range(max_rounds):
        elapsed = time.time() - t_start
        if elapsed >= time_budget_s:
            stop_reason = f"timeout ({elapsed:.0f}s)"; break
        if best_cov >= 0.9999:
            stop_reason = "converged"; break

        sr = solve_board(best)
        unknown_list = list(sr['unknown'])
        if not unknown_list:
            stop_reason = "no_unknowns"; break

        # Score candidate mines by proximity to unknowns
        cand_score = {}
        for (uy, ux) in unknown_list:
            for dy in range(-search_radius, search_radius+1):
                for dx in range(-search_radius, search_radius+1):
                    ny, nx = uy+dy, ux+dx
                    if (0<=ny<H and 0<=nx<W and best[ny,nx]==1
                            and forbidden[ny,nx]==0):
                        cand_score[(ny,nx)] = cand_score.get((ny,nx),0)+1

        if not cand_score: stop_reason = "no_candidates"; break

        top = sorted(cand_score.items(), key=lambda x: -x[1])[:300]
        scored = []
        for (cy,cx), _ in top:
            # Cheap estimate: count unknowns within 2 cells
            n_unk_near = sum(1 for (uy,ux) in unknown_list
                             if abs(uy-cy)<=2 and abs(ux-cx)<=2)
            scored.append(((cy,cx), best_cov + n_unk_near/(H*W)))
        scored.sort(key=lambda x: -x[1])

        # Full solve for top candidates
        accepted = None
        for (cy,cx), _ in scored[:30]:
            cand = best.copy(); cand[cy,cx] = 0
            new_sr = solve_board(cand)
            if new_sr['coverage'] >= best_cov - 0.0001:
                if new_sr['n_unknown'] < best_unk or new_sr['coverage'] > best_cov + 0.0001:
                    accepted = (cand, new_sr)
                    break

        if accepted is None:
            # Nothing improves — try first scored candidate
            (cy,cx), _ = scored[0]
            cand = best.copy(); cand[cy,cx] = 0
            new_sr = solve_board(cand)
            if new_sr['coverage'] >= best_cov - 0.0001:
                accepted = (cand, new_sr)

        if accepted:
            best, new_sr = accepted
            best_cov = new_sr['coverage']
            best_unk = new_sr['n_unknown']
            if (rnd+1) % checkpoint_every == 0:
                np.save(ckpt_path, best)
                if verbose:
                    print(f"  Round {rnd+1:>4d}: cov={best_cov:.4f}"
                          f"  unknown={best_unk:>5d}"
                          f"  t={time.time()-t_start:.0f}s")
        else:
            stop_reason = "stagnated"; break

    if stop_reason in ("converged","no_unknowns") and os.path.exists(ckpt_path):
        os.remove(ckpt_path)
    if verbose:
        print(f"  Repair done: cov={best_cov:.4f}  unknown={best_unk}"
              f"  reason={stop_reason}  t={time.time()-t_start:.1f}s")

    return best, solve_board(best), stop_reason


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2 REPAIR: Mine-Swap Repair (NEW — the key innovation of Iter 10)
# ═══════════════════════════════════════════════════════════════════════════════

def _check_swap_valid(N_cur, H, W, my, mx, ty, tx):
    """
    Fast O(16) check: does the swap (remove mine at my,mx; add at ty,tx)
    keep all N values in [0,8]?
    """
    # Net delta for each cell in the affected 3×3 neighborhoods
    delta = {}
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            if dy==0 and dx==0: continue
            ny, nx = my+dy, mx+dx
            if 0 <= ny < H and 0 <= nx < W:
                delta[(ny,nx)] = delta.get((ny,nx),0) - 1
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            if dy==0 and dx==0: continue
            ny, nx = ty+dy, tx+dx
            if 0 <= ny < H and 0 <= nx < W:
                delta[(ny,nx)] = delta.get((ny,nx),0) + 1
    for (ny,nx), d in delta.items():
        nv = N_cur[ny,nx] + d
        if nv < 0 or nv > 8:
            return False
    return True

def _swap_asymmetry_score(my, mx, ty, tx, unknown_set, H, W):
    """
    Score a swap by how asymmetrically it affects the unknown neighborhood.
    Higher score = more likely to break a 50/50 symmetry.
    
    Analogy: if two suspects share identical alibis (symmetric constraints),
    finding new evidence that distinguishes one from the other (asymmetric
    new info) is how you solve the case. This score measures how much new
    asymmetric information the swap adds.
    """
    nbrs_m = set((my+dy, mx+dx) for dy in range(-2,3) for dx in range(-2,3)
                 if 0<=my+dy<H and 0<=mx+dx<W and (dy,dx)!=(0,0))
    nbrs_t = set((ty+dy, tx+dx) for dy in range(-2,3) for dx in range(-2,3)
                 if 0<=ty+dy<H and 0<=tx+dx<W and (dy,dx)!=(0,0))
    unkn_near_m = nbrs_m & unknown_set
    unkn_near_t = nbrs_t & unknown_set
    # Exclusive neighborhoods → asymmetry
    exclusive = len(unkn_near_t - unkn_near_m) + len(unkn_near_m - unkn_near_t)
    # Shared neighborhoods → symmetry (bad)
    shared = len(unkn_near_t & unkn_near_m)
    return exclusive - shared * 0.5

def mine_swap_repair(grid, target, weights, forbidden, sr_initial,
                     time_budget_s=120.0, max_outer=200, verbose=True):
    """
    Phase 2 repair: break 50/50 ambiguities by SWAPPING mine positions.

    For each unknown cell, finds a (mine_to_remove, position_to_add) pair
    that creates an asymmetric constraint, potentially resolving the ambiguity.

    The search is guided by an asymmetry score so we don't waste time on
    swaps that preserve the very symmetry causing the problem.
    """
    H, W = grid.shape
    t_start = time.time()

    best = grid.copy()
    best_sr = sr_initial
    best_unk = best_sr['n_unknown']
    best_cov = best_sr['coverage']

    if best_unk == 0:
        return best, best_sr, "already_solvable"

    if verbose:
        print(f"  [Swap repair]  {best_unk} unknowns, budget={time_budget_s:.0f}s")

    stop_reason = "budget"
    N_cur = compute_N(best)

    for outer in range(max_outer):
        elapsed = time.time() - t_start
        if elapsed >= time_budget_s:
            stop_reason = f"timeout ({elapsed:.0f}s)"; break
        if best_unk == 0:
            stop_reason = "solved"; break

        unknown_set = best_sr['unknown']
        unknown_list = list(unknown_set)

        # ── Find candidate mines ──────────────────────────────────────────────
        mine_scores = {}
        for (uy, ux) in unknown_list:
            for r in range(1, 6):
                for dy in range(-r, r+1):
                    for dx in range(-r, r+1):
                        if abs(dy) != r and abs(dx) != r: continue
                        ny, nx = uy+dy, ux+dx
                        if (0<=ny<H and 0<=nx<W and
                                best[ny,nx]==1 and forbidden[ny,nx]==0):
                            mine_scores[(ny,nx)] = mine_scores.get((ny,nx),0)+1

        if not mine_scores:
            stop_reason = "no_candidate_mines"; break

        sorted_mines = sorted(mine_scores.items(), key=lambda x: -x[1])

        # ── Find candidate swap targets ───────────────────────────────────────
        # Empty, non-forbidden cells near unknown cells
        target_set = {}
        for (uy, ux) in unknown_list:
            for dy in range(-3, 4):
                for dx in range(-3, 4):
                    ty, tx = uy+dy, ux+dx
                    if (0<=ty<H and 0<=tx<W and
                            best[ty,tx]==0 and forbidden[ty,tx]==0):
                        if (ty,tx) not in target_set:
                            target_set[(ty,tx)] = []
                        target_set[(ty,tx)].append((uy,ux))

        # ── Score and rank swap pairs ─────────────────────────────────────────
        scored_swaps = []
        for (my, mx), _ in sorted_mines[:40]:
            for (ty, tx) in target_set:
                if (ty, tx) == (my, mx): continue
                # Fast validity check
                if not _check_swap_valid(N_cur, H, W, my, mx, ty, tx):
                    continue
                score = _swap_asymmetry_score(my, mx, ty, tx, unknown_set, H, W)
                scored_swaps.append((score, (my, mx), (ty, tx)))

        scored_swaps.sort(key=lambda x: -x[0])

        # ── Full solve for top swap candidates ────────────────────────────────
        improved = False
        for score, (my, mx), (ty, tx) in scored_swaps[:50]:
            candidate = best.copy()
            candidate[my, mx] = 0
            candidate[ty, tx] = 1

            # Double-check forbidden
            if forbidden[ty, tx] == 1:
                continue

            new_sr = solve_board(candidate)
            new_unk = new_sr['n_unknown']
            new_cov = new_sr['coverage']

            # Accept if unknowns decrease (primary) OR coverage improves (secondary)
            if new_unk < best_unk or (new_unk == best_unk and new_cov > best_cov + 0.001):
                best = candidate
                best_sr = new_sr
                best_unk = new_unk
                best_cov = new_cov
                N_cur = compute_N(best)
                improved = True
                if verbose:
                    print(f"  Swap {outer+1:>3d}: ({my},{mx})→({ty},{tx})"
                          f"  score={score:.1f}"
                          f"  unknown={best_unk}  cov={best_cov:.4f}"
                          f"  t={time.time()-t_start:.0f}s")
                break

        # ── Also try pure removal (no swap) ──────────────────────────────────
        if not improved:
            for (my, mx), _ in sorted_mines[:30]:
                candidate = best.copy()
                candidate[my, mx] = 0
                N_c = compute_N(candidate)
                if N_c.min() < 0: continue
                new_sr = solve_board(candidate)
                if new_sr['n_unknown'] < best_unk or new_sr['coverage'] > best_cov + 0.001:
                    best = candidate
                    best_sr = new_sr
                    best_unk = new_sr['n_unknown']
                    best_cov = new_sr['coverage']
                    N_cur = compute_N(best)
                    improved = True
                    if verbose:
                        print(f"  Remove {outer+1:>3d}: ({my},{mx})"
                              f"  unknown={best_unk}  cov={best_cov:.4f}")
                    break

        if not improved:
            stop_reason = "stagnated"
            if verbose:
                print(f"  Swap repair stagnated after {outer+1} outer iterations")
            break

    elapsed = time.time() - t_start
    if verbose:
        print(f"  Swap repair done: cov={best_cov:.4f}  unknown={best_unk}"
              f"  reason={stop_reason}  t={elapsed:.1f}s")

    return best, best_sr, stop_reason


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3 REPAIR: Ambiguity Enumeration (NEW — for small unknown sets)
# ═══════════════════════════════════════════════════════════════════════════════

def enumerate_and_resolve(grid, target, forbidden, sr, max_unknown=25, verbose=True):
    """
    For small unknown sets (≤ max_unknown cells), enumerate ALL valid mine
    configurations for those cells and determine which are truly ambiguous.

    If the configuration is uniquely determined: the board IS solvable
    (we just need to verify our solver is complete enough).

    If multiple configurations exist: for each ambiguous cell pair,
    try adding a mine to a position that creates asymmetric constraint
    to force uniqueness.
    """
    H, W = grid.shape
    unknown_list = list(sr['unknown'])
    n_unk = len(unknown_list)

    if n_unk == 0:
        return grid, sr, "already_solved"
    if n_unk > max_unknown:
        return grid, sr, f"too_many_unknowns ({n_unk})"

    if verbose:
        print(f"\n  [Enumeration]  {n_unk} unknown cells — enumerating {2**n_unk:,} configs")

    N_grid = compute_N(grid)
    unknown_set = set(unknown_list)
    revealed = sr['revealed']
    flagged  = sr['flagged']

    # Build constraints: revealed cells that neighbor unknowns
    cell_to_idx = {cell: i for i, cell in enumerate(unknown_list)}
    constraints = []
    for (ry, rx) in revealed:
        if grid[ry, rx] == 1: continue
        num = int(N_grid[ry, rx])
        unk_nbrs = [(ny,nx) for ny,nx in _nbrs(ry, rx, H, W)
                    if (ny,nx) in unknown_set]
        if not unk_nbrs: continue
        flg_nbrs = sum(1 for ny,nx in _nbrs(ry,rx,H,W) if (ny,nx) in flagged)
        remaining = num - flg_nbrs
        constraints.append((unk_nbrs, remaining))

    # Enumerate valid configurations
    valid_configs = []
    t_enum = time.time()
    for cfg in iproduct([0,1], repeat=n_unk):
        valid = True
        for (unk_nbrs, remaining) in constraints:
            mines = sum(cfg[cell_to_idx[c]] for c in unk_nbrs)
            if mines != remaining:
                valid = False; break
        if valid:
            valid_configs.append(cfg)
        if time.time() - t_enum > 30:
            if verbose: print(f"  Enumeration timed out at {2**n_unk} configs")
            return grid, sr, "enum_timeout"

    if verbose:
        print(f"  Found {len(valid_configs)} valid configurations for {n_unk} unknowns")

    if len(valid_configs) == 0:
        return grid, sr, "no_valid_config"

    if len(valid_configs) == 1:
        # Unique solution — but our solver missed it. Force it.
        if verbose: print(f"  Unique config found! Forcing it onto board.")
        new_grid = grid.copy()
        for i, (uy, ux) in enumerate(unknown_list):
            new_grid[uy, ux] = valid_configs[0][i]
        new_sr = solve_board(new_grid)
        return new_grid, new_sr, "forced_unique"

    # Multiple configs: identify which cells differ between configurations
    n_configs = len(valid_configs)
    ambiguous_cells = []
    for i in range(n_unk):
        vals = set(cfg[i] for cfg in valid_configs)
        if len(vals) > 1:
            ambiguous_cells.append(i)

    if verbose:
        print(f"  {len(ambiguous_cells)}/{n_unk} cells are genuinely ambiguous")
        print(f"  Ambiguous cells: {[unknown_list[i] for i in ambiguous_cells]}")

    # For each ambiguous cell, try to add a mine that breaks the symmetry
    best = grid.copy()
    best_sr = sr
    best_unk = n_unk

    for amb_idx in ambiguous_cells:
        uy, ux = unknown_list[amb_idx]
        if verbose:
            print(f"  Trying to resolve ambiguous cell ({uy},{ux}) ...")

        # Try adding a mine adjacent to (uy,ux) that's NOT adjacent to other ambiguous cells
        other_ambiguous = set(unknown_list[i] for i in ambiguous_cells if i != amb_idx)

        for dy in range(-2, 3):
            for dx in range(-2, 3):
                ty, tx = uy+dy, ux+dx
                if not (0<=ty<H and 0<=tx<W): continue
                if best[ty, tx] == 1: continue  # already a mine
                if forbidden[ty, tx] == 1: continue
                if (ty, tx) in unknown_set: continue  # can't mine unknown cells

                # Check N validity
                N_c = compute_N(best)
                for ny, nx in _nbrs(ty, tx, H, W):
                    if N_c[ny, nx] + 1 > 8:
                        break
                else:
                    # Try adding mine at (ty,tx) (no swap, just add)
                    candidate = best.copy()
                    candidate[ty, tx] = 1
                    new_sr = solve_board(candidate)
                    if new_sr['n_unknown'] < best_unk:
                        best = candidate
                        best_sr = new_sr
                        best_unk = new_sr['n_unknown']
                        if verbose:
                            print(f"    Added mine at ({ty},{tx}) → unknown={best_unk}")
                        break

        if best_unk == 0:
            break

    new_reason = f"enum_resolved_{n_unk - best_unk}_of_{n_unk}"
    return best, best_sr, new_reason


# ═══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTICS
# ═══════════════════════════════════════════════════════════════════════════════

def analyze_unknowns(grid, sr, target, label=""):
    """
    Detailed analysis of remaining unknown cells:
    - How many clusters?
    - What is the average cluster size?
    - What is the N-field pattern around each unknown?
    """
    unknown_list = list(sr['unknown'])
    n_unk = len(unknown_list)
    if n_unk == 0:
        print(f"  [{label}] No unknowns — board is SOLVABLE! ✓")
        return

    H, W = grid.shape
    N = compute_N(grid)

    # Find connected clusters of unknowns (8-connectivity)
    unknown_set = set(unknown_list)
    visited = set()
    clusters = []
    for start in unknown_list:
        if start in visited: continue
        cluster = []
        q = [start]
        while q:
            cell = q.pop()
            if cell in visited: continue
            visited.add(cell)
            cluster.append(cell)
            y, x = cell
            for dy in range(-1,2):
                for dx in range(-1,2):
                    nb = (y+dy, x+dx)
                    if nb in unknown_set and nb not in visited:
                        q.append(nb)
        clusters.append(cluster)

    print(f"\n  [{label}] Unknown cell analysis:")
    print(f"    Total unknowns: {n_unk}")
    print(f"    Clusters: {len(clusters)}")
    for i, cl in enumerate(clusters[:8]):
        n_vals = [float(N[y,x]) for y,x in cl]
        t_vals = [float(target[y,x]) for y,x in cl]
        mines_in_cluster = sum(int(grid[y,x]) for y,x in cl)
        print(f"    Cluster {i+1}: size={len(cl)}"
              f"  mines={mines_in_cluster}"
              f"  N_mean={np.mean(n_vals):.1f}"
              f"  T_mean={np.mean(t_vals):.1f}"
              f"  cells={cl[:3]}{'...' if len(cl)>3 else ''}")
    if len(clusters) > 8:
        print(f"    ... and {len(clusters)-8} more clusters")


# ═══════════════════════════════════════════════════════════════════════════════
# VISUALISATION
# ═══════════════════════════════════════════════════════════════════════════════

def render_report(target, grid, sr, history, title, save_path, dpi=120):
    N = compute_N(grid)
    H, W = grid.shape
    err = np.abs(N - target)

    fig = plt.figure(figsize=(24, 16))
    gs = fig.add_gridspec(3, 3, hspace=0.35, wspace=0.3)

    ax = fig.add_subplot(gs[0,0])
    im = ax.imshow(target, cmap='inferno', vmin=0, vmax=8, interpolation='nearest')
    ax.set_title("Target [0-8]", fontweight='bold'); plt.colorbar(im, ax=ax, fraction=0.046); ax.axis('off')

    ax = fig.add_subplot(gs[0,1])
    ax.imshow(grid, cmap='binary', vmin=0, vmax=1, interpolation='nearest')
    ax.set_title(f"Mine Grid (ρ={grid.mean():.3f})", fontweight='bold'); ax.axis('off')

    ax = fig.add_subplot(gs[0,2])
    im = ax.imshow(N, cmap='inferno', vmin=0, vmax=8, interpolation='nearest')
    ax.set_title("Number Field N(x,y)", fontweight='bold'); plt.colorbar(im, ax=ax, fraction=0.046); ax.axis('off')

    ax = fig.add_subplot(gs[1,0])
    im = ax.imshow(err, cmap='hot', vmin=0, vmax=4, interpolation='nearest')
    ax.set_title(f"|N-T| (mean={err.mean():.2f})", fontweight='bold'); plt.colorbar(im, ax=ax, fraction=0.046); ax.axis('off')

    ax = fig.add_subplot(gs[1,1])
    board_img = np.ones((H, W, 3), dtype=np.float32)
    for (y,x) in sr["revealed"]: board_img[y,x] = [0.82,0.82,0.82]
    for (y,x) in sr["flagged"]:  board_img[y,x] = [1.0,0.4,0.0]
    for (y,x) in sr["unknown"]:  board_img[y,x] = [0.3,0.3,0.9]
    ax.imshow(board_img, interpolation='nearest')
    solvable_str = "SOLVABLE ✓" if sr['solvable'] else f"unknown={sr['n_unknown']}"
    ax.set_title(f"Solve Map (cov={sr['coverage']:.1%})\n{solvable_str}", fontweight='bold'); ax.axis('off')

    ax = fig.add_subplot(gs[1,2])
    if len(history) > 1:
        ax.plot(history, color='steelblue', lw=1.5)
        ax.set_yscale('log')
    ax.set_xlabel("Checkpoint"); ax.set_ylabel("Loss")
    ax.set_title("Optimization Loss Curve", fontweight='bold'); ax.grid(True, alpha=0.3)

    ax = fig.add_subplot(gs[2,0])
    bins = np.arange(0,10)
    ax.bar(bins[:-1]-0.2, np.histogram(target.ravel(),bins=bins)[0], width=0.4, label='Target', color='steelblue', alpha=0.7)
    ax.bar(bins[:-1]+0.2, np.histogram(N.ravel(),bins=bins)[0], width=0.4, label='N field', color='tomato', alpha=0.7)
    ax.legend(); ax.set_xlabel("Value"); ax.set_ylabel("Count")
    ax.set_title("Distribution: Target vs N field", fontweight='bold')

    ax = fig.add_subplot(gs[2,1:])
    ax.axis('off')
    text = (
        f"{'METRIC':<22} {'VALUE':>14}\n{'─'*38}\n"
        f"{'Board size':<22} {W}×{H} = {W*H:,} cells\n"
        f"{'Loss/cell':<22} {float(np.sum((N-target)**2))/(W*H):>14.4f}\n"
        f"{'Mean |N-T|':<22} {err.mean():>14.4f}\n"
        f"{'Mine density':<22} {grid.mean():>14.4f}\n"
        f"{'Solver coverage':<22} {sr['coverage']:>14.4f}\n"
        f"{'Solvable':<22} {str(sr['solvable']):>14}\n"
        f"{'Unknown cells':<22} {sr['n_unknown']:>14}\n"
        f"{'Mine accuracy':<22} {sr['mine_accuracy']:>14.4f}\n"
        f"{'Max N':<22} {int(N.max()):>14}\n"
    )
    ax.text(0.02, 0.97, text, transform=ax.transAxes, fontsize=10,
            va='top', fontfamily='monospace',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='#f8f8e8', edgecolor='gray', alpha=0.9))

    fig.suptitle(title, fontsize=15, fontweight='bold', y=0.98)
    plt.savefig(save_path, dpi=dpi, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved → {save_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# FULL PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def pipeline(board_w, board_h, label, sa_fn,
             density=0.22, border=3, seed=0,
             coarse_iters=1_500_000, fine_iters=4_000_000, refine_iters=5_000_000,
             T_fine=2.5, T_refine=1.5,
             repair1_budget_s=None,  # None = dynamic (n_unknown * 0.15 + 30)
             repair2_budget_s=120.0,
             repair3_max_unknown=25) -> dict:

    H, W = board_h, board_w
    t_total = time.time()
    slug = label.lower().replace(" ","_").replace("×","x")
    print(f"\n{'═'*68}")
    print(f"  {label}  [{W}×{H} = {W*H:,} cells]")
    print(f"{'═'*68}")

    # ── Image ──────────────────────────────────────────────────────────────────
    target  = load_image_smart(IMG, W, H, panel='full', invert=True)
    weights = compute_edge_weights(target, boost=4.0, sigma=0.8)
    print(f"  Target: [{target.min():.1f},{target.max():.1f}]  mean={target.mean():.2f}")

    # ── Corridors ──────────────────────────────────────────────────────────────
    forbidden, pct, seeds, mst_coo = build_adaptive_corridors(
        target, border=border, corridor_width=0, low_target_bias=5.5)
    hi_blocked = int(np.sum((target>3)&(forbidden==1)))
    print(f"  Corridors: {pct:.1f}%  seeds={len(seeds)}  hi-blocked={hi_blocked}")

    # ── SA ─────────────────────────────────────────────────────────────────────
    Hc, Wc = max(8, H//2), max(8, W//2)
    t_c = np.array(PILImage.fromarray(target).resize((Wc,Hc),PILImage.LANCZOS), dtype=np.float32)
    w_c = np.array(PILImage.fromarray(weights).resize((Wc,Hc),PILImage.BILINEAR), dtype=np.float32)
    f_c = (np.array(PILImage.fromarray((forbidden.astype(np.uint8)*255)).resize((Wc,Hc),PILImage.NEAREST))>127).astype(np.int8)

    rng = np.random.default_rng(seed)
    prob = np.clip(t_c/8.0*density*3.0, 0, density); prob[f_c==1]=0
    g_c = (rng.random((Hc,Wc)) < prob).astype(np.int8); g_c[f_c==1]=0
    N_c = compute_N(g_c).astype(np.float32)

    print(f"  [Coarse {Wc}×{Hc}]  {coarse_iters:,} iters …")
    t0=time.time()
    gc, lc, _ = sa_fn(g_c.copy(),N_c.copy(),t_c,w_c,f_c,8.0,0.99998,0.001,coarse_iters,border,Hc,Wc,seed)
    print(f"  {time.time()-t0:.1f}s  loss={lc:.0f}")

    gc_img = PILImage.fromarray(gc.astype(np.float32)).resize((W,H),PILImage.NEAREST)
    grid = (np.array(gc_img)>0.5).astype(np.int8); grid[forbidden==1]=0
    N_f = compute_N(grid).astype(np.float32)

    print(f"  [Fine {W}×{H}]  {fine_iters:,} iters …")
    t0=time.time()
    grid, lf, _ = sa_fn(grid.copy(),N_f.copy(),target,weights,forbidden,T_fine,0.999995,0.001,fine_iters,border,H,W,seed+1)
    grid[forbidden==1]=0
    print(f"  {time.time()-t0:.1f}s  density={grid.mean():.3f}")

    # Refine with underfill-augmented weights
    N_cur = compute_N(grid)
    underfill = np.clip(target-N_cur,0,8)/8.0
    w_aug = (weights*(1.0+1.5*underfill)).astype(np.float32)

    print(f"  [Refine]  {refine_iters:,} iters …")
    t0=time.time()
    grid, lr, hist_r = sa_fn(grid.copy(),compute_N(grid).astype(np.float32),target,w_aug,forbidden,T_refine,0.999996,0.001,refine_iters,border,H,W,seed+2)
    grid[forbidden==1]=0
    print(f"  {time.time()-t0:.1f}s  density={grid.mean():.3f}")
    assert_board_valid(grid, forbidden, f"{label} post-SA")

    # ── Phase 1 Repair: remove mines ──────────────────────────────────────────
    sr_pre = solve_board(grid)
    n_unk_pre = sr_pre['n_unknown']
    budget1 = repair1_budget_s if repair1_budget_s is not None \
              else max(60.0, n_unk_pre * 0.15 + 30)
    print(f"\n  [Phase 1 Repair]  budget={budget1:.0f}s  (n_unk={n_unk_pre})")
    grid, sr, reason1 = bounded_repair(
        grid, target, weights, forbidden, slug,
        time_budget_s=budget1, max_rounds=300,
        batch_size=10, search_radius=6,
        checkpoint_every=10, verbose=True)
    assert_board_valid(grid, forbidden, f"{label} post-repair1")
    analyze_unknowns(grid, sr, target, f"{label} after Phase 1")

    # ── Phase 2 Repair: mine swap ─────────────────────────────────────────────
    if sr['n_unknown'] > 0:
        print(f"\n  [Phase 2 Swap Repair]  budget={repair2_budget_s:.0f}s")
        grid, sr, reason2 = mine_swap_repair(
            grid, target, weights, forbidden, sr,
            time_budget_s=repair2_budget_s, max_outer=300, verbose=True)
        assert_board_valid(grid, forbidden, f"{label} post-repair2")
        analyze_unknowns(grid, sr, target, f"{label} after Phase 2")
    else:
        reason2 = "skipped_already_solved"

    # ── Phase 3 Repair: enumeration ───────────────────────────────────────────
    if 0 < sr['n_unknown'] <= repair3_max_unknown:
        print(f"\n  [Phase 3 Enumeration]  n_unk={sr['n_unknown']}")
        grid, sr, reason3 = enumerate_and_resolve(
            grid, target, forbidden, sr,
            max_unknown=repair3_max_unknown, verbose=True)
        assert_board_valid(grid, forbidden, f"{label} post-repair3")
        analyze_unknowns(grid, sr, target, f"{label} after Phase 3")
    else:
        reason3 = f"skipped (n_unk={sr['n_unknown']})"

    # ── Final metrics ──────────────────────────────────────────────────────────
    N_fin = compute_N(grid)
    err   = np.abs(N_fin - target)
    metrics = {
        "label":          label,
        "board":          f"{W}x{H}",
        "cells":          W * H,
        "loss_per_cell":  round(float(np.sum((N_fin-target)**2))/(W*H), 4),
        "mean_abs_error": round(float(err.mean()), 4),
        "pct_within_1":   round(float(np.mean(err<=1.0))*100, 2),
        "pct_within_2":   round(float(np.mean(err<=2.0))*100, 2),
        "mine_density":   round(float(grid.mean()), 4),
        "corridor_pct":   pct,
        "coverage":       sr["coverage"],
        "solvable":       sr["solvable"],
        "mine_accuracy":  sr["mine_accuracy"],
        "n_unknown":      sr["n_unknown"],
        "repair1_reason": reason1,
        "repair2_reason": reason2,
        "repair3_reason": reason3,
        "total_time_s":   round(time.time()-t_total, 1),
    }

    print(f"\n  METRICS [{label}]:")
    for k, v in metrics.items():
        print(f"    {k:<22}: {v}")

    # ── Render ─────────────────────────────────────────────────────────────────
    render_report(target, grid, sr, hist_r.tolist(),
                  title=f"Iter 10 — {label}  corridor={pct:.0f}%  density={grid.mean():.3f}",
                  save_path=f"{OUT}/iter10_{slug}_FINAL.png", dpi=120)

    # ── Atomic saves ───────────────────────────────────────────────────────────
    atomic_save_npy(grid,    f"{OUT}/grid_iter10_{slug}_FINAL.npy")
    atomic_save_npy(target,  f"{OUT}/target_iter10_{slug}_FINAL.npy")
    atomic_save_json(metrics, f"{OUT}/metrics_iter10_{slug}_FINAL.json")
    print(f"  ✓ Saved atomically")

    return metrics


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":

    print("\n[Step 1] Kernel compilation")
    sa_fn = compile_sa_kernel()

    all_metrics = []

    # ── Board 1: 200×125 — primary solvability target ─────────────────────────
    print("\n[Step 2] 200×125  — Primary solvability target")
    m1 = pipeline(
        200, 125, "200x125", sa_fn,
        density=0.22, border=3, seed=300,
        coarse_iters=1_500_000, fine_iters=4_000_000,
        refine_iters=5_000_000, T_fine=2.5, T_refine=1.5,
        repair1_budget_s=None,   # dynamic
        repair2_budget_s=150.0,  # generous for swap repair
        repair3_max_unknown=25,
    )
    all_metrics.append(m1)

    # ── Board 2: 300×187 — scale test (only if board 1 informs us well) ───────
    print("\n[Step 3] 300×187  — Scale test")
    m2 = pipeline(
        300, 187, "300x187", sa_fn,
        density=0.21, border=3, seed=301,
        coarse_iters=1_500_000, fine_iters=4_000_000,
        refine_iters=5_000_000, T_fine=2.5, T_refine=1.5,
        repair1_budget_s=None,
        repair2_budget_s=180.0,
        repair3_max_unknown=25,
    )
    all_metrics.append(m2)

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n" + "="*68)
    print("ITERATION 10 — FINAL SUMMARY")
    print("="*68)
    keys = ["cells","loss_per_cell","mean_abs_error","mine_density","corridor_pct",
            "coverage","solvable","n_unknown","repair1_reason","repair2_reason",
            "repair3_reason","total_time_s"]
    labels = [m["label"] for m in all_metrics]
    col_w = 18
    print(f"\n{'Metric':<22}" + "".join(f" {str(l)[:col_w-1]:>{col_w}}" for l in labels))
    print("─"*(22+(col_w+1)*len(labels)))
    for k in keys:
        print(f"{k:<22}" + "".join(f" {str(m.get(k,'—'))[:col_w-1]:>{col_w}}" for m in all_metrics))

    print("\nIteration 10 complete ✓")

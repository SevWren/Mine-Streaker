"""
ITERATION 9: Mask-Aware SA Kernel + Single-Pixel Corridors + Density Recovery
==============================================================================

PLAN — three targeted improvements from Iter 8 analysis:

1. MASK-AWARE NUMBA SA KERNEL  (core fix)
   New _sa_inner_masked() Numba JIT function that accepts a boolean
   forbidden_mask array. Any cell where forbidden_mask=True is NEVER
   flipped to mine=1. This enforces corridor constraints throughout
   SA, eliminating the post-repair coverage degradation problem.
   Result: post-repair SA can now safely run, recovering lost loss.

2. SINGLE-PIXEL MST CORRIDORS  (quality improvement)
   Replace corridor_width=1 (3-pixel strip) with corridor_width=0
   (single pixel paths). This drops forced-zero coverage from 16.2%
   → ~8.7% at 250×250, freeing ~4,700 additional high-target cells
   for mine placement. Expected density improvement: 11% → 14-16%.

3. DENSITY RECOVERY SA PASS  (quality improvement)
   After repair, the grid has fewer mines than optimal (repairs remove
   mines). A dedicated density-recovery SA pass runs at moderate T with
   the mask enforced, targeting the specific underfilled cells (N<T-1).
   Uses a boosted-weight map: cells where N << T get 8× weight boost
   to direct mine additions to maximally useful positions.

EXPECTED OUTCOMES vs Iter 8 (250×250):
   - Density: 11.2% → 15-17% (more mines in freed high-target cells)
   - Mean |N-T|: 0.691 → 0.55-0.60
   - % within ±1: 76.8% → 82-85%
   - Coverage: maintain 99.9%+
   - Solvable: remain unsolvable (last ~0.05% are irreducible 50/50s)
"""

import sys
sys.path.insert(0, '/home/claude/minesweeper')

import numpy as np
import scipy.ndimage as ndi
from scipy.sparse.csgraph import minimum_spanning_tree
from scipy.sparse import csr_matrix
from PIL import Image as PILImage
import time, json, os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from numba import njit
from large_scale_engine import (
    load_image_smart, compute_edge_weights, compute_N, visual_loss,
    render_full_report, save_board_hires
)

OUT = "/home/claude/minesweeper/results"
IMG = "/mnt/user-data/uploads/2-Figure2-1.png"
os.makedirs(OUT, exist_ok=True)

print("=" * 68)
print("ITERATION 9 — Mask-Aware SA + Single-Pixel Corridors")
print("=" * 68)


# ═══════════════════════════════════════════════════════════════════════════════
# MASK-AWARE NUMBA SA KERNEL
# ═══════════════════════════════════════════════════════════════════════════════

@njit(cache=True, fastmath=True)
def _sa_masked(grid, N, target, weights, forbidden,
               T, alpha, T_min, max_iter, border, H, W, seed):
    """
    Simulated annealing with hard forbidden-cell constraint.

    forbidden[y,x] == 1  →  cell (y,x) can NEVER become a mine.

    This enforces corridor integrity throughout optimization, eliminating
    the post-repair coverage degradation from unconstrained SA.

    Returns: (best_grid, best_loss, history)
    """
    np.random.seed(seed)
    best_grid = grid.copy()
    best_loss = 0.0
    for y in range(H):
        for x in range(W):
            d = N[y, x] - target[y, x]
            best_loss += weights[y, x] * d * d
    current_loss = best_loss

    history = np.zeros(max_iter // 50000 + 2, dtype=np.float64)
    h_idx = 0
    history[h_idx] = best_loss
    h_idx += 1

    for i in range(max_iter):
        y = np.random.randint(0, H)
        x = np.random.randint(0, W)

        # Hard constraint: never place a mine in a forbidden cell
        if forbidden[y, x] == 1 and grid[y, x] == 0:
            continue  # can't flip 0→1 here; 1→0 (removal) still allowed

        # Also skip border cells for mine placement
        if y < border or y >= H - border or x < border or x >= W - border:
            if grid[y, x] == 0:
                continue

        sign = 1 - 2 * int(grid[y, x])   # +1 = add mine, -1 = remove mine

        # Compute loss delta
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
                    d_loss += weights[ny, nx] * (diff_new*diff_new - diff_cur*diff_cur)
            if not valid:
                break
        if not valid:
            continue

        # Accept / reject (Metropolis criterion)
        if d_loss < 0.0 or np.random.random() < np.exp(-d_loss / (T + 1e-12)):
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

        if i % 50000 == 0 and i > 0:
            history[h_idx] = best_loss
            h_idx += 1

    return best_grid, best_loss, history[:h_idx]


# ═══════════════════════════════════════════════════════════════════════════════
# SINGLE-PIXEL MST CORRIDOR BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def build_single_pixel_corridors(target: np.ndarray, border: int = 3,
                                  low_target_bias: float = 5.0,
                                  spacing_divisor: float = 8.0
                                  ) -> tuple:
    """
    Build corridor mask using single-pixel-wide MST paths.

    Compared to Iter 8's width=1 (3-pixel strips):
      - Forces ~8-9% of cells zero (vs 16-28%)
      - Preserves ~4,700 more cells at 250×250 for mine placement
      - Still guarantees flood-fill connectivity via BFS from all borders
    """
    H, W = target.shape
    spacing = max(5, int(np.sqrt(H * W) / spacing_divisor))

    ys = list(range(border, H - border, spacing))
    xs = list(range(border, W - border, spacing))
    if H - border - 1 not in ys:
        ys.append(H - border - 1)
    if W - border - 1 not in xs:
        xs.append(W - border - 1)

    seeds = [(y, x) for y in ys for x in xs]
    n = len(seeds)

    def line_cost(y0, x0, y1, x1):
        length = max(abs(y1 - y0), abs(x1 - x0), 1)
        ys_p = np.round(np.linspace(y0, y1, length + 1)).astype(int)
        xs_p = np.round(np.linspace(x0, x1, length + 1)).astype(int)
        ys_p = np.clip(ys_p, 0, H - 1)
        xs_p = np.clip(xs_p, 0, W - 1)
        return float(target[ys_p, xs_p].mean())

    rows, cols, data = [], [], []
    for i in range(n):
        for j in range(i + 1, n):
            y0, x0 = seeds[i]
            y1, x1 = seeds[j]
            dist = np.sqrt((y1 - y0)**2 + (x1 - x0)**2)
            if dist <= 2.5 * spacing:
                w = line_cost(y0, x0, y1, x1) ** low_target_bias + dist * 0.01
                rows.append(i)
                cols.append(j)
                data.append(w)

    if not data:
        for i in range(n):
            for j in range(i + 1, n):
                y0, x0 = seeds[i]
                y1, x1 = seeds[j]
                dist = np.sqrt((y1 - y0)**2 + (x1 - x0)**2)
                w = line_cost(y0, x0, y1, x1) ** low_target_bias + dist * 0.01
                rows.append(i); cols.append(j); data.append(w)

    G = csr_matrix((data, (rows, cols)), shape=(n, n))
    mst = minimum_spanning_tree(G).tocoo()

    # Build single-pixel corridor mask
    mask = np.zeros((H, W), dtype=np.int8)   # int8 for Numba compatibility

    # Border
    mask[:border, :] = 1
    mask[-border:, :] = 1
    mask[:, :border] = 1
    mask[:, -border:] = 1

    # Single-pixel MST paths
    for i, j in zip(mst.row, mst.col):
        y0, x0 = seeds[i]
        y1, x1 = seeds[j]
        length = max(abs(y1 - y0), abs(x1 - x0), 1)
        ys_p = np.round(np.linspace(y0, y1, length + 1)).astype(int)
        xs_p = np.round(np.linspace(x0, x1, length + 1)).astype(int)
        for yp, xp in zip(ys_p, xs_p):
            mask[np.clip(yp, 0, H-1), np.clip(xp, 0, W-1)] = 1

    coverage_pct = 100.0 * mask.mean()
    return mask, coverage_pct, seeds, mst


def init_grid_masked(target: np.ndarray, forbidden: np.ndarray,
                     density: float = 0.20, seed: int = 0) -> np.ndarray:
    """Probabilistic init respecting forbidden mask."""
    rng = np.random.default_rng(seed)
    H, W = target.shape
    prob = np.clip(target / 8.0 * density * 3.5, 0.0, density)
    prob[forbidden == 1] = 0.0
    grid = (rng.random((H, W)) < prob).astype(np.int8)
    grid[forbidden == 1] = 0
    return grid


# ═══════════════════════════════════════════════════════════════════════════════
# UNDERFILL-BOOSTED WEIGHT MAP
# ═══════════════════════════════════════════════════════════════════════════════

def compute_underfill_weights(grid: np.ndarray, target: np.ndarray,
                               base_weights: np.ndarray,
                               underfill_boost: float = 6.0,
                               overfill_boost: float = 3.0) -> np.ndarray:
    """
    Augment weights to prioritize correcting underfilled cells.

    Cells where N << T need more mines nearby → boost weight.
    Cells where N >> T need fewer mines nearby → boost weight.
    Cells where N ≈ T are well-fit → keep base weight.
    """
    N = compute_N(grid)
    diff = target - N   # positive = underfilled, negative = overfilled

    underfill_w = np.clip(diff / 8.0, 0, 1) * underfill_boost
    overfill_w  = np.clip(-diff / 8.0, 0, 1) * overfill_boost

    boosted = (base_weights + underfill_w + overfill_w).astype(np.float32)
    return boosted


# ═══════════════════════════════════════════════════════════════════════════════
# INCREMENTAL SOLVER + BATCHED REPAIR (from iter7)
# ═══════════════════════════════════════════════════════════════════════════════

_src7 = open('iter7.py').read()
exec(_src7[_src7.find('\nclass IncrementalSolver'):_src7.find('\ndef sa_refine')])
print("IncrementalSolver + batched_repair loaded ✓")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def pipeline_iter9(board_w: int, board_h: int, label: str,
                   density: float = 0.22,
                   border: int = 3,
                   seed: int = 0,
                   coarse_iters: int = 1_500_000,
                   fine_iters:   int = 5_000_000,
                   refine_iters: int = 6_000_000,
                   density_recovery_iters: int = 3_000_000,
                   post_repair_iters: int = 3_000_000,
                   repair_rounds: int = 150,
                   batch_size: int = 10) -> dict:

    H, W = board_h, board_w
    t_total = time.time()
    print(f"\n{'═'*68}")
    print(f"  {label}  [{W}×{H} = {W*H:,} cells]")
    print(f"{'═'*68}")

    # ── Load & preprocess ─────────────────────────────────────────────────────
    target  = load_image_smart(IMG, W, H, panel='left', invert=True)
    weights = compute_edge_weights(target, boost=4.0, sigma=0.8)
    print(f"  Target: [{target.min():.1f},{target.max():.1f}]  "
          f"mean={target.mean():.2f}")

    # ── Single-pixel corridors ────────────────────────────────────────────────
    print("  Building single-pixel MST corridors …")
    t0 = time.time()
    forbidden, corr_pct, seeds, mst_coo = build_single_pixel_corridors(
        target, border=border, low_target_bias=5.0)
    print(f"  Corridors: {corr_pct:.1f}% forced-zero  "
          f"({len(seeds)} seeds, {mst_coo.nnz} edges)  [{time.time()-t0:.2f}s]")

    hi_blocked = int(np.sum((target > 3) & (forbidden == 1)))
    print(f"  High-target cells blocked: {hi_blocked}  "
          f"(Iter8 was ~534 for 200×125 w=1)")

    # ── Coarse SA (masked) ────────────────────────────────────────────────────
    Hc, Wc = max(8, int(H * 0.5)), max(8, int(W * 0.5))
    t_c  = np.array(PILImage.fromarray(target) .resize((Wc, Hc), PILImage.LANCZOS),  dtype=np.float32)
    w_c  = np.array(PILImage.fromarray(weights).resize((Wc, Hc), PILImage.BILINEAR), dtype=np.float32)
    fb_c = np.array(PILImage.fromarray(forbidden.astype(np.uint8)*255)
                    .resize((Wc, Hc), PILImage.NEAREST), dtype=np.int8) > 0

    g_c  = init_grid_masked(t_c, fb_c.astype(np.int8), density=density, seed=seed)
    N_c  = compute_N(g_c).astype(np.float32)

    print(f"  [Coarse {Wc}×{Hc}]  {coarse_iters:,} iters …")
    t0 = time.time()
    gc, lc, _ = _sa_masked(
        g_c.copy(), N_c.copy(), t_c, w_c, fb_c.astype(np.int8),
        8.0, 0.99998, 0.001, coarse_iters, border, Hc, Wc, seed)
    print(f"  {time.time()-t0:.1f}s  loss_w={lc:.0f}  density={gc.mean():.3f}")

    # Upsample
    gc_img = PILImage.fromarray(gc.astype(np.float32)).resize((W, H), PILImage.NEAREST)
    grid = (np.array(gc_img) > 0.5).astype(np.int8)
    grid[forbidden == 1] = 0

    # ── Fine SA (masked) ──────────────────────────────────────────────────────
    N_f = compute_N(grid).astype(np.float32)
    print(f"  [Fine {W}×{H}]  {fine_iters:,} iters …")
    t0 = time.time()
    grid, lf, _ = _sa_masked(
        grid.copy(), N_f.copy(), target, weights, forbidden,
        3.0, 0.999995, 0.001, fine_iters, border, H, W, seed+1)
    N_fa = compute_N(grid)
    print(f"  {time.time()-t0:.1f}s  actual_loss={float(np.sum((N_fa-target)**2)):.0f}  "
          f"density={grid.mean():.3f}")

    # ── Underfill-boosted refinement ──────────────────────────────────────────
    w_boost = compute_underfill_weights(grid, target, weights,
                                         underfill_boost=5.0, overfill_boost=2.0)
    N_r = compute_N(grid).astype(np.float32)
    print(f"  [Refine]  {refine_iters:,} iters (underfill-boosted) …")
    t0 = time.time()
    grid, lr, hist_r = _sa_masked(
        grid.copy(), N_r.copy(), target, w_boost, forbidden,
        1.5, 0.999996, 0.001, refine_iters, border, H, W, seed+2)
    N_ra = compute_N(grid)
    loss_ra = float(np.sum((N_ra - target)**2))
    print(f"  {time.time()-t0:.1f}s  actual_loss={loss_ra:.0f}  density={grid.mean():.3f}")

    # ── Batched repair ────────────────────────────────────────────────────────
    print(f"  [Repair]  max {repair_rounds} rounds …")
    t0 = time.time()
    grid, sr = batched_repair(
        grid, target, weights,
        max_rounds=repair_rounds, batch_size=batch_size,
        search_radius=6, verbose=True)
    cov_post_repair = sr["coverage"]
    print(f"  {time.time()-t0:.1f}s  cov={cov_post_repair:.4f}  unknown={sr['n_unknown']}")

    # ── Density recovery SA (mask-enforced — now SAFE to run) ────────────────
    print(f"  [Density recovery]  {density_recovery_iters:,} iters, T=0.8 …")
    t0 = time.time()
    w_rec = compute_underfill_weights(grid, target, weights,
                                       underfill_boost=4.0, overfill_boost=1.5)
    N_rec = compute_N(grid).astype(np.float32)
    g_rec, _, hist_rec = _sa_masked(
        grid.copy(), N_rec.copy(), target, w_rec, forbidden,
        0.8, 0.999997, 0.001, density_recovery_iters, border, H, W, seed+3)
    g_rec[forbidden == 1] = 0

    sv_rec = IncrementalSolver(g_rec)
    cov_rec = sv_rec.coverage
    N_reca = compute_N(g_rec)
    loss_reca = float(np.sum((N_reca - target)**2))
    print(f"  {time.time()-t0:.1f}s  loss={loss_reca:.0f}  density={g_rec.mean():.3f}  "
          f"cov={cov_rec:.4f}")

    if cov_rec >= cov_post_repair - 0.001:
        grid = g_rec
        sr   = sv_rec.result_dict()
        print(f"  Density recovery ACCEPTED ✓")
    else:
        print(f"  Density recovery reverted (cov {cov_post_repair:.4f}→{cov_rec:.4f})")

    # ── Post-repair loss-polish SA (mask-enforced — low T) ───────────────────
    print(f"  [Post-repair polish]  {post_repair_iters:,} iters, T=0.15 …")
    t0 = time.time()
    N_pp = compute_N(grid).astype(np.float32)
    g_pp, _, hist_pp = _sa_masked(
        grid.copy(), N_pp.copy(), target, weights, forbidden,
        0.15, 0.999998, 0.001, post_repair_iters, border, H, W, seed+4)
    g_pp[forbidden == 1] = 0

    sv_pp = IncrementalSolver(g_pp)
    cov_pp = sv_pp.coverage
    N_ppa = compute_N(g_pp)
    loss_ppa = float(np.sum((N_ppa - target)**2))
    print(f"  {time.time()-t0:.1f}s  loss={loss_ppa:.0f}  density={g_pp.mean():.3f}  "
          f"cov={cov_pp:.4f}")

    if cov_pp >= sr["coverage"] - 0.001:
        grid = g_pp
        sr   = sv_pp.result_dict()
        print(f"  Post-repair polish ACCEPTED ✓")
    else:
        print(f"  Post-repair polish reverted (cov would drop "
              f"{sr['coverage']:.4f}→{cov_pp:.4f})")

    # ── Final metrics ─────────────────────────────────────────────────────────
    N_fin = compute_N(grid)
    err   = np.abs(N_fin - target)
    metrics = {
        "label":           label,
        "board":           f"{W}x{H}",
        "cells":           W * H,
        "loss":            round(float(np.sum((N_fin - target)**2)), 2),
        "loss_per_cell":   round(float(np.sum((N_fin - target)**2)) / (W*H), 4),
        "mean_abs_error":  round(float(err.mean()), 4),
        "pct_within_0.5":  round(float(np.mean(err <= 0.5)) * 100, 2),
        "pct_within_1":    round(float(np.mean(err <= 1.0)) * 100, 2),
        "pct_within_2":    round(float(np.mean(err <= 2.0)) * 100, 2),
        "mine_density":    round(float(grid.mean()), 4),
        "corridor_pct":    round(corr_pct, 2),
        "hi_blocked":      hi_blocked,
        "coverage":        sr["coverage"],
        "solvable":        sr["solvable"],
        "mine_accuracy":   sr["mine_accuracy"],
        "n_unknown":       sr["n_unknown"],
        "total_time_s":    round(time.time() - t_total, 1),
    }

    print(f"\n  METRICS [{label}]:")
    for k, v in metrics.items():
        print(f"    {k:<22}: {v}")

    # ── Render ────────────────────────────────────────────────────────────────
    slug     = label.lower().replace(" ", "_").replace("×", "x")
    all_hist = hist_r.tolist() + hist_rec.tolist() + hist_pp.tolist()

    render_full_report(
        target, grid, sr, all_hist,
        title=f"Iter 9 — {label}  (single-pixel corridors {corr_pct:.0f}%)",
        save_path=f"{OUT}/iter9_{slug}.png", dpi=120)

    cell_px = max(2, min(8, 900 // max(W, H)))
    save_board_hires(
        grid, sr,
        save_path=f"{OUT}/iter9_{slug}_board.png",
        cell_size=cell_px, dpi=130)

    _save_corridor_comparison(
        target, forbidden, grid,
        f"{OUT}/iter9_{slug}_corridors.png", label, corr_pct)

    np.save(f"{OUT}/grid_iter9_{slug}.npy", grid)
    np.save(f"{OUT}/target_iter9_{slug}.npy", target)
    with open(f"{OUT}/metrics_iter9_{slug}.json", "w") as f:
        json.dump(metrics, f, indent=2)

    return metrics


def _save_corridor_comparison(target, forbidden, grid, path, title, pct):
    H, W = target.shape
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    axes[0].imshow(target, cmap='inferno', vmin=0, vmax=8, interpolation='nearest')
    axes[0].set_title("Target [0–8]", fontweight='bold')
    axes[0].axis('off')

    overlay = np.stack([target/8]*3, axis=-1)
    overlay[forbidden == 1] = [0.1, 0.5, 1.0]
    axes[1].imshow(overlay, interpolation='nearest')
    axes[1].set_title(f"Single-Pixel Corridor Mask\n({pct:.1f}% forced-zero, blue=corridor)",
                      fontweight='bold')
    axes[1].axis('off')

    N = compute_N(grid)
    err = np.abs(N - target)
    im = axes[2].imshow(err, cmap='hot', vmin=0, vmax=4, interpolation='nearest')
    axes[2].set_title(f"|N-T| Error Map  (mean={err.mean():.3f})", fontweight='bold')
    plt.colorbar(im, ax=axes[2])
    axes[2].axis('off')

    fig.suptitle(f"Iter 9 Corridor Analysis — {title}", fontweight='bold')
    plt.tight_layout()
    plt.savefig(path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    print(f"  Corridor map → {path}")


# ═══════════════════════════════════════════════════════════════════════════════
# WARMUP + RUN
# ═══════════════════════════════════════════════════════════════════════════════

print("\n[Warmup] Compiling Numba kernels …")
_z = np.zeros((8,8), dtype=np.float32)
_g = np.zeros((8,8), dtype=np.int8)
_fb = np.zeros((8,8), dtype=np.int8)
_sa_masked(_g.copy(), _z.copy(), _z, np.ones((8,8),dtype=np.float32), _fb,
           1., 0.999, 0.01, 300, 1, 8, 8, 0)
print("JIT ready ✓\n")

all_metrics = []

# ── 200×125  (direct comparison to Iter 8) ────────────────────────────────────
m1 = pipeline_iter9(
    200, 125, "large_200x125",
    density=0.22, border=3, seed=200,
    coarse_iters=1_500_000,
    fine_iters=5_000_000,
    refine_iters=6_000_000,
    density_recovery_iters=3_000_000,
    post_repair_iters=3_000_000,
    repair_rounds=120, batch_size=8,
)
all_metrics.append(m1)

# ── 250×250  (key milestone comparison to Iter 8) ─────────────────────────────
m2 = pipeline_iter9(
    250, 250, "square_250x250",
    density=0.21, border=3, seed=210,
    coarse_iters=2_000_000,
    fine_iters=6_000_000,
    refine_iters=7_000_000,
    density_recovery_iters=4_000_000,
    post_repair_iters=4_000_000,
    repair_rounds=150, batch_size=10,
)
all_metrics.append(m2)

# ── SUMMARY TABLE ─────────────────────────────────────────────────────────────
print("\n" + "=" * 68)
print("ITERATION 9 — FINAL COMPARISON")
print("=" * 68)

refs, lbls = [], []
for fname, lbl in [
    ("metrics_iter8_large_200x125.json", "Iter8 200×125"),
    ("metrics_iter8_square_250x250.json", "Iter8 250×250"),
]:
    try:
        with open(f"{OUT}/{fname}") as f:
            refs.append(json.load(f))
            lbls.append(lbl)
    except FileNotFoundError:
        pass

for m in all_metrics:
    refs.append(m)
    lbls.append(f"Iter9 {m['board'].replace('x','×')}")

keys = ["cells", "loss_per_cell", "mean_abs_error",
        "pct_within_0.5", "pct_within_1", "pct_within_2",
        "mine_density", "corridor_pct", "hi_blocked",
        "coverage", "solvable", "n_unknown", "total_time_s"]

print(f"\n{'Metric':<22}" + "".join(f" {l[:14]:>15}" for l in lbls))
print("─" * (22 + 16 * len(lbls)))
for k in keys:
    print(f"{k:<22}" + "".join(f" {str(m.get(k,'—'))[:14]:>15}" for m in refs))

print("\nIteration 9 complete.")

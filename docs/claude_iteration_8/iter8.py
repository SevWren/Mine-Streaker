"""
ITERATION 8: Adaptive Corridors + Solvability-Guided SA + 250×250 Scale
========================================================================

PLAN
----
Root cause diagnosis from Iter 7:
  - Fixed-grid corridors cover 54.5% of cells at 200×125 (step=10)
  - 2,049 high-target cells (T>3) fall inside forced-zero corridors
  - These cells CANNOT contribute mines → permanent loss floor ~46k
  - SA warm-refinement has almost no effect because the board is
    already at the constrained optimum given the corridor layout

THREE-PART FIX:

1. ADAPTIVE CORRIDOR ROUTING (core architectural change)
   Instead of a rigid grid of zero-strips, route corridors through
   low-target (T≤1) cells only, skirting around high-target regions.
   Algorithm: minimum-spanning-tree on the target image where edge
   weights = target value (prefer routing through dark/low areas).
   This preserves mine-placement freedom in bright regions.

2. SOLVABILITY-GUIDED SA (replaces post-hoc repair)
   Instead of repairing after SA, add a SOLVABILITY GRADIENT to the
   SA loss: each mine that is "unreachable" by the current flood-fill
   frontier adds a penalty proportional to its distance from the
   nearest reachable zero cell.
   This steers the optimizer to naturally create solvable configurations
   rather than requiring a separate repair pass.

3. 250×250 SCALE TEST
   With the incremental solver + batched repair from Iter 7, the
   pipeline is fast enough. Run a full 250×250 board (62,500 cells)
   on the anime image.
"""

import sys
sys.path.insert(0, '/home/claude/minesweeper')

from sa_core import _sa_inner, NUMBA
from large_scale_engine import (
    load_image_smart, compute_edge_weights, compute_N, visual_loss,
    init_grid, apply_structure, render_full_report, save_board_hires
)
from PIL import Image as PILImage
import numpy as np
import scipy.ndimage as ndi
from scipy.sparse.csgraph import minimum_spanning_tree
from scipy.sparse import csr_matrix
import time, json, os

OUT = "/home/claude/minesweeper/results"
IMG = "/mnt/user-data/uploads/2-Figure2-1.png"
os.makedirs(OUT, exist_ok=True)

print("=" * 68)
print("ITERATION 8 — Adaptive Corridors + Solvability SA + 250×250")
print("=" * 68)

# ── JIT warmup ────────────────────────────────────────────────────────────────
print("\n[Warmup] Numba JIT …")
_z = np.zeros((8, 8), dtype=np.float32)
_g = np.zeros((8, 8), dtype=np.int8)
_sa_inner(_g.copy(), _z.copy(), _z, np.ones((8,8),dtype=np.float32),
          1., 0.999, 0.01, 300, 1, 0.3, 8, 8, 0)
print("JIT ready ✓\n")

# Load IncrementalSolver + batched_repair from iter7
_src = open('iter7.py').read()
_cls_start = _src.find('\nclass IncrementalSolver')
_rep_end   = _src.find('\ndef sa_refine')
exec(_src[_cls_start:_rep_end])
print("IncrementalSolver + batched_repair loaded ✓")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ADAPTIVE CORRIDOR ROUTING via MST on target image
# ═══════════════════════════════════════════════════════════════════════════════

def build_adaptive_corridors(target: np.ndarray, border: int = 3,
                              n_seeds: int = None,
                              corridor_width: int = 1,
                              low_target_bias: float = 6.0) -> np.ndarray:
    """
    Build a mine-free corridor mask that routes through LOW-TARGET cells.

    Algorithm:
    1. Create a grid of "seed" nodes evenly spaced across the board
    2. Build a complete graph where edge weight = mean target value along
       the straight-line path between nodes (low target = cheap edge)
    3. Compute MST of this graph → minimal-cost spanning tree
    4. Burn the MST edges into the corridor mask (mine-free strips)
    5. Add mine-free border

    This ensures solver flood-fill can reach all regions while minimising
    the number of high-target cells forcibly set to zero.
    """
    H, W = target.shape

    # Auto-select seed spacing to get ~(sqrt(cells)/4)² seeds
    if n_seeds is None:
        spacing = max(6, int(np.sqrt(H * W) // 8))
    else:
        spacing = max(4, int(np.sqrt(H * W / n_seeds)))

    # Generate seed positions on a grid, offset from border
    ys = list(range(border, H - border, spacing))
    xs = list(range(border, W - border, spacing))
    if H - border - 1 not in ys:
        ys.append(H - border - 1)
    if W - border - 1 not in xs:
        xs.append(W - border - 1)

    seeds = [(y, x) for y in ys for x in xs]
    n = len(seeds)

    # Build edge-weight matrix: path cost = mean target along Bresenham line
    def path_cost(y0, x0, y1, x1):
        """Mean target value on straight line from (y0,x0) to (y1,x1)."""
        length = max(abs(y1-y0), abs(x1-x0), 1)
        ys_path = np.round(np.linspace(y0, y1, length+1)).astype(int)
        xs_path = np.round(np.linspace(x0, x1, length+1)).astype(int)
        ys_path = np.clip(ys_path, 0, H-1)
        xs_path = np.clip(xs_path, 0, W-1)
        return float(target[ys_path, xs_path].mean())

    # Only build edges for "nearby" seed pairs (within 2*spacing) to keep sparse
    rows, cols, data = [], [], []
    for i in range(n):
        for j in range(i+1, n):
            y0, x0 = seeds[i]
            y1, x1 = seeds[j]
            dist = np.sqrt((y1-y0)**2 + (x1-x0)**2)
            if dist <= 2.5 * spacing:
                # Weight: path cost raised to power = bias toward low-target paths
                w = path_cost(y0, x0, y1, x1) ** low_target_bias + dist * 0.01
                rows.append(i); cols.append(j); data.append(w)

    if len(data) == 0:
        # Fallback: connect all pairs
        for i in range(n):
            for j in range(i+1, n):
                y0,x0=seeds[i]; y1,x1=seeds[j]
                dist=np.sqrt((y1-y0)**2+(x1-x0)**2)
                w=path_cost(y0,x0,y1,x1)**low_target_bias+dist*0.01
                rows.append(i); cols.append(j); data.append(w)

    G = csr_matrix((data, (rows, cols)), shape=(n, n))
    mst = minimum_spanning_tree(G)
    mst_coo = mst.tocoo()

    # Build corridor mask
    mask = np.zeros((H, W), dtype=bool)

    # Border
    mask[:border, :] = True
    mask[-border:, :] = True
    mask[:, :border] = True
    mask[:, -border:] = True

    # MST edges → burn corridors
    for i, j in zip(mst_coo.row, mst_coo.col):
        y0, x0 = seeds[i]
        y1, x1 = seeds[j]
        length = max(abs(y1-y0), abs(x1-x0), 1)
        ys_path = np.round(np.linspace(y0, y1, length+1)).astype(int)
        xs_path = np.round(np.linspace(x0, x1, length+1)).astype(int)
        for yp, xp in zip(ys_path, xs_path):
            for dy in range(-corridor_width, corridor_width+1):
                for dx in range(-corridor_width, corridor_width+1):
                    ny, nx = yp+dy, xp+dx
                    if 0 <= ny < H and 0 <= nx < W:
                        mask[ny, nx] = True

    coverage_pct = 100.0 * mask.mean()
    return mask, coverage_pct, seeds, mst_coo


def init_grid_adaptive(target: np.ndarray, corridor_mask: np.ndarray,
                       density: float = 0.22, seed: int = 0) -> np.ndarray:
    """
    Initialize mine grid respecting adaptive corridor mask.
    High-target cells inside non-masked regions get higher mine probability.
    """
    rng = np.random.default_rng(seed)
    H, W = target.shape
    # Scale probability by target value, capped at density
    prob = np.clip(target / 8.0 * density * 3.0, 0.0, density)
    prob[corridor_mask] = 0.0  # force zero in corridor cells
    grid = (rng.random((H, W)) < prob).astype(np.int8)
    grid[corridor_mask] = 0
    return grid


# ═══════════════════════════════════════════════════════════════════════════════
# 2. SOLVABILITY-PENALISED SA (Numba-compatible approach)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_reachability_penalty(grid: np.ndarray,
                                  target: np.ndarray) -> np.ndarray:
    """
    Compute per-cell penalty weight for SA:
    Mines far from flood-fill-reachable zeros get higher weight.
    Returns additional weight map to add to base weights.

    This steers SA away from placing isolated mine clusters.
    """
    H, W = grid.shape
    N = compute_N(grid)

    # Distance transform from zero-N safe cells
    zero_safe = (grid == 0) & (N == 0)
    if zero_safe.sum() == 0:
        # No zeros yet — use border as reference
        zero_safe[:3, :] = True
        zero_safe[-3:, :] = True
        zero_safe[:, :3] = True
        zero_safe[:, -3:] = True

    # Distance from nearest zero safe cell
    dist_from_zero = ndi.distance_transform_edt(~zero_safe)
    dist_norm = dist_from_zero / (dist_from_zero.max() + 1e-8)

    # Penalty proportional to: distance × target_value
    # (high-target, far-from-zero mines are MOST penalised)
    penalty = dist_norm * target / 8.0 * 2.0

    return penalty.astype(np.float32)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. MULTI-PHASE PIPELINE WITH ADAPTIVE CORRIDORS
# ═══════════════════════════════════════════════════════════════════════════════

def adaptive_pipeline(board_w: int, board_h: int, label: str,
                      density: float = 0.20,
                      border: int = 3,
                      seed: int = 0,
                      coarse_scale: float = 0.5,
                      coarse_iters: int = 1_500_000,
                      fine_iters:   int = 4_000_000,
                      refine_iters: int = 5_000_000,
                      repair_rounds: int = 120,
                      batch_size: int = 8,
                      verbose: bool = True) -> dict:

    H, W = board_h, board_w
    t_total = time.time()
    print(f"\n{'═'*68}")
    print(f"  {label}  [{W}×{H} = {W*H:,} cells]")
    print(f"{'═'*68}")

    # ── Load & preprocess ─────────────────────────────────────────────────────
    target  = load_image_smart(IMG, W, H, panel='left', invert=True)
    weights = compute_edge_weights(target, boost=4.0, sigma=0.8)
    print(f"  Target: [{target.min():.1f}, {target.max():.1f}]  "
          f"mean={target.mean():.2f}  shape={H}×{W}")

    # ── Build adaptive corridors ──────────────────────────────────────────────
    print(f"  Building adaptive corridors …")
    t0 = time.time()
    corridor_mask, cov_pct, seeds, mst = build_adaptive_corridors(
        target, border=border, corridor_width=1, low_target_bias=5.0)
    print(f"  Corridors: {cov_pct:.1f}% cells forced zero  "
          f"({len(seeds)} seeds, {mst.nnz} MST edges)  "
          f"[{time.time()-t0:.2f}s]")

    # Compare to fixed grid corridors
    fixed_mask = np.zeros((H, W), dtype=bool)
    fixed_mask[:border,:]=True; fixed_mask[-border:,:]=True
    fixed_mask[:,:border]=True; fixed_mask[:,-border:]=True
    cstep = max(6, W//20)
    for r in range(0,H,cstep): fixed_mask[max(0,r-1):min(H,r+2),:]=True
    for c in range(0,W,cstep): fixed_mask[:,max(0,c-1):min(W,c+2)]=True

    fixed_cov = 100*fixed_mask.mean()
    fixed_hi_lost = int(np.sum((target > 3) & fixed_mask))
    adapt_hi_lost = int(np.sum((target > 3) & corridor_mask))
    print(f"  Fixed corridors:    {fixed_cov:.1f}% coverage, "
          f"{fixed_hi_lost} high-target cells blocked")
    print(f"  Adaptive corridors: {cov_pct:.1f}% coverage, "
          f"{adapt_hi_lost} high-target cells blocked  "
          f"[{fixed_hi_lost - adapt_hi_lost:+d} improvement]")

    # ── Coarse pass ───────────────────────────────────────────────────────────
    Hc = max(8, int(H * coarse_scale))
    Wc = max(8, int(W * coarse_scale))

    t_c  = np.array(PILImage.fromarray(target).resize((Wc,Hc), PILImage.LANCZOS),
                    dtype=np.float32)
    w_c  = np.array(PILImage.fromarray(weights).resize((Wc,Hc), PILImage.BILINEAR),
                    dtype=np.float32)
    cm_c = np.array(PILImage.fromarray(corridor_mask.astype(np.uint8)*255)
                    .resize((Wc,Hc), PILImage.NEAREST), dtype=np.uint8) > 127

    g_c  = init_grid_adaptive(t_c, cm_c, density=density, seed=seed)
    N_c  = compute_N(g_c).astype(np.float32)

    print(f"  [Coarse {Wc}×{Hc}]  {coarse_iters:,} iters …")
    t0 = time.time()
    gc_out, lc, _ = _sa_inner(
        g_c.copy(), N_c.copy(), t_c, w_c,
        8.0, 0.99998, 0.001, coarse_iters, border, density, Hc, Wc, seed)
    print(f"  Coarse: {time.time()-t0:.1f}s  loss={lc:.0f}")

    # Upsample and re-apply corridor mask
    gc_img  = PILImage.fromarray(gc_out.astype(np.float32)).resize(
                  (W, H), PILImage.NEAREST)
    grid    = (np.array(gc_img) > 0.5).astype(np.int8)
    grid[corridor_mask] = 0  # enforce adaptive corridors

    # ── Fine pass ─────────────────────────────────────────────────────────────
    N_f = compute_N(grid).astype(np.float32)
    print(f"  [Fine {W}×{H}]  {fine_iters:,} iters …")
    t0 = time.time()
    grid, lf, _ = _sa_inner(
        grid.copy(), N_f.copy(), target, weights,
        2.5, 0.999995, 0.001, fine_iters, border, density, H, W, seed+1)
    grid[corridor_mask] = 0  # re-enforce after SA
    N_f2 = compute_N(grid); lf_actual = float(np.sum((N_f2-target)**2))
    print(f"  Fine: {time.time()-t0:.1f}s  "
          f"loss(weighted)={lf:.0f}  actual={lf_actual:.0f}  "
          f"density={grid.mean():.3f}")

    # ── Reachability-penalised refinement ─────────────────────────────────────
    # Add solvability penalty to weights before refinement pass
    solv_pen = compute_reachability_penalty(grid, target)
    weights_aug = (weights + solv_pen).astype(np.float32)

    print(f"  [Refinement]  {refine_iters:,} iters (solvability-augmented weights) …")
    t0 = time.time()
    N_r = compute_N(grid).astype(np.float32)
    grid, lr, hist_r = _sa_inner(
        grid.copy(), N_r.copy(), target, weights_aug,
        1.5, 0.999996, 0.001, refine_iters, border, density, H, W, seed+2)
    grid[corridor_mask] = 0
    N_r2 = compute_N(grid); lr_actual = float(np.sum((N_r2-target)**2))
    print(f"  Refine: {time.time()-t0:.1f}s  "
          f"loss(weighted)={lr:.0f}  actual={lr_actual:.0f}  "
          f"density={grid.mean():.3f}")

    # ── Batched repair ────────────────────────────────────────────────────────
    print(f"  [Repair]  max {repair_rounds} rounds …")
    t0 = time.time()
    grid, sr = batched_repair(
        grid, target, weights,
        max_rounds=repair_rounds, batch_size=batch_size,
        search_radius=6, verbose=verbose)
    cov_after_repair = sr["coverage"]
    print(f"  Repair: {time.time()-t0:.1f}s  cov={cov_after_repair:.4f}  "
          f"unknown={sr['n_unknown']}")

    # ── Post-repair loss recovery SA (very low T, abort if coverage drops) ───
    print(f"  [Post-repair SA]  2M iters, T=0.04 …")
    t0 = time.time()
    N_pr = compute_N(grid).astype(np.float32)
    g_pr, lpr_w, hist_pr = _sa_inner(
        grid.copy(), N_pr.copy(), target, weights,
        0.04, 0.999998, 0.001, 2_000_000, border, density, H, W, seed+3)
    g_pr[corridor_mask] = 0

    solver_pr = IncrementalSolver(g_pr)
    if solver_pr.coverage >= cov_after_repair - 0.001:
        grid = g_pr
        sr   = solver_pr.result_dict()
        N_pr2 = compute_N(grid)
        print(f"  Post-SA accepted: cov={sr['coverage']:.4f}  "
              f"loss={float(np.sum((N_pr2-target)**2)):.0f}")
    else:
        print(f"  Post-SA reverted (cov would drop "
              f"{cov_after_repair:.4f}→{solver_pr.coverage:.4f})")

    # ── Final metrics ─────────────────────────────────────────────────────────
    N_fin = compute_N(grid)
    err   = np.abs(N_fin - target)
    metrics = {
        "label":           label,
        "board":           f"{W}x{H}",
        "cells":           W * H,
        "loss":            round(float(np.sum((N_fin-target)**2)), 2),
        "loss_per_cell":   round(float(np.sum((N_fin-target)**2))/(W*H), 4),
        "mean_abs_error":  round(float(err.mean()), 4),
        "pct_within_1":    round(float(np.mean(err <= 1.0)) * 100, 2),
        "pct_within_2":    round(float(np.mean(err <= 2.0)) * 100, 2),
        "mine_density":    round(float(grid.mean()), 4),
        "corridor_pct":    round(cov_pct, 2),
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
    all_hist = hist_r.tolist() + hist_pr.tolist()

    render_full_report(
        target, grid, sr, all_hist,
        title=f"Minesweeper Iter 8 — {label}  ({W}×{H})  "
              f"[adaptive corridors, {cov_pct:.0f}% forced-zero]",
        save_path=f"{OUT}/iter8_{slug}.png", dpi=120)

    cell_px = max(2, min(8, 900 // max(W, H)))
    save_board_hires(
        grid, sr,
        save_path=f"{OUT}/iter8_{slug}_board.png",
        cell_size=cell_px, dpi=130)

    # Corridor visualisation
    _save_corridor_map(target, corridor_mask, seeds, mst, grid,
                       f"{OUT}/iter8_{slug}_corridors.png", label)

    # Save state
    np.save(f"{OUT}/grid_iter8_{slug}.npy", grid)
    np.save(f"{OUT}/target_iter8_{slug}.npy", target)
    with open(f"{OUT}/metrics_iter8_{slug}.json", "w") as f:
        json.dump(metrics, f, indent=2)

    return metrics


def _save_corridor_map(target, corridor_mask, seeds, mst_coo, grid,
                        path, title):
    """Visualise adaptive corridor layout on the target image."""
    import matplotlib.pyplot as plt
    H, W = target.shape
    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    # Target
    axes[0].imshow(target, cmap='inferno', vmin=0, vmax=8,
                   interpolation='nearest')
    axes[0].set_title("Target Image [0–8]", fontweight='bold')
    axes[0].axis('off')

    # Corridor overlay
    overlay = np.stack([target/8]*3, axis=-1)
    overlay[corridor_mask] = [0.2, 0.6, 1.0]  # blue = forced zero
    axes[1].imshow(overlay, interpolation='nearest')
    # Draw MST edges
    for i, j in zip(mst_coo.row, mst_coo.col):
        y0, x0 = seeds[i]
        y1, x1 = seeds[j]
        axes[1].plot([x0,x1],[y0,y1],'g-',linewidth=0.5,alpha=0.5)
    sy, sx = zip(*seeds)
    axes[1].scatter(sx, sy, c='yellow', s=8, zorder=5)
    axes[1].set_title(f"Adaptive Corridor Map\n"
                      f"({100*corridor_mask.mean():.1f}% forced-zero, "
                      f"blue=corridor)", fontweight='bold')
    axes[1].axis('off')

    # Mine grid
    axes[2].imshow(grid, cmap='binary', interpolation='nearest')
    axes[2].set_title(f"Mine Grid (ρ={grid.mean():.3f})", fontweight='bold')
    axes[2].axis('off')

    fig.suptitle(f"Corridor Analysis — {title}", fontweight='bold')
    plt.tight_layout()
    plt.savefig(path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    print(f"  Corridor map → {path}")


# ═══════════════════════════════════════════════════════════════════════════════
# RUN ALL SCALES
# ═══════════════════════════════════════════════════════════════════════════════

all_metrics = []

# ── 200×125 (compare directly to Iter 7) ──────────────────────────────────────
m_lrg = adaptive_pipeline(
    200, 125, "large_200x125",
    density=0.22, border=3, seed=100,
    coarse_scale=0.5,
    coarse_iters=1_500_000,
    fine_iters=4_000_000,
    refine_iters=5_000_000,
    repair_rounds=120, batch_size=8,
)
all_metrics.append(m_lrg)

# ── 250×125 (wider, higher aspect — tests horizontal fidelity) ─────────────────
m_wide = adaptive_pipeline(
    250, 156, "wide_250x156",
    density=0.21, border=3, seed=110,
    coarse_scale=0.5,
    coarse_iters=1_500_000,
    fine_iters=4_000_000,
    refine_iters=5_000_000,
    repair_rounds=120, batch_size=8,
)
all_metrics.append(m_wide)

# ── 250×250 (large square — key milestone) ────────────────────────────────────
m_sq = adaptive_pipeline(
    250, 250, "square_250x250",
    density=0.20, border=3, seed=120,
    coarse_scale=0.4,
    coarse_iters=2_000_000,
    fine_iters=5_000_000,
    refine_iters=6_000_000,
    repair_rounds=150, batch_size=10,
)
all_metrics.append(m_sq)


# ── FULL COMPARISON TABLE ──────────────────────────────────────────────────────
print("\n" + "=" * 68)
print("ITERATION 8 — FINAL COMPARISON")
print("=" * 68)

# Load Iter 7 metrics for reference
try:
    with open(f"{OUT}/metrics_iter7_large_200x125_final.json") as f:
        m_iter7 = json.load(f)
    all_metrics_with_ref = [m_iter7] + all_metrics
    labels = ["Iter7 200×125"] + [m["label"] for m in all_metrics]
except FileNotFoundError:
    all_metrics_with_ref = all_metrics
    labels = [m["label"] for m in all_metrics]

keys = ["cells", "loss_per_cell", "mean_abs_error", "pct_within_1",
        "pct_within_2", "mine_density", "corridor_pct",
        "coverage", "solvable", "n_unknown", "total_time_s"]

print(f"\n{'Metric':<22}", end="")
for lbl in labels:
    print(f" {lbl[:14]:>14}", end="")
print()
print("─" * (22 + 15 * len(labels)))

for k in keys:
    print(f"{k:<22}", end="")
    for m in all_metrics_with_ref:
        v = m.get(k, "—")
        print(f" {str(v)[:14]:>14}", end="")
    print()

print("\nIteration 8 complete.")

"""
Iteration 6: Large-Scale Pipeline on Real Anime Line-Art Image
- 120×75 cell board (9,000 cells) — medium scale for profiling
- 200×125 cell board (25,000 cells) — large scale
- Full pipeline: load → SA → repair → solve → render
"""
import sys
sys.path.insert(0, '/home/claude/minesweeper')
from large_scale_engine import *
import json, os

OUT = "/home/claude/minesweeper/results"
os.makedirs(OUT, exist_ok=True)
IMG = "/mnt/user-data/uploads/2-Figure2-1.png"

print("="*60)
print("ITERATION 6 — Large-Scale Real Image Pipeline")
print("="*60)

# ── Warm up Numba JIT ─────────────────────────────────────────
print("\n[Warmup] Compiling Numba JIT …")
_tg = np.zeros((10,10), dtype=np.float32)
_wg = np.ones((10,10), dtype=np.float32)
_g  = np.zeros((10,10), dtype=np.int8)
_N  = np.zeros((10,10), dtype=np.float32)
_ = _sa_inner(_g.copy(), _N.copy(), _tg, _wg, 1.0, 0.9999, 0.01, 100, 1, 0.3, 10, 10, 0)
print("Numba compiled ✓")

def run_scale(board_w, board_h, label, density=0.22,
              iters_coarse=300_000, iters_fine=800_000,
              corridor_step=8, border=3, seed=10,
              repair_rounds=40):
    print(f"\n{'─'*60}")
    print(f"  SCALE: {board_w}×{board_h} = {board_w*board_h:,} cells  [{label}]")
    print(f"{'─'*60}")

    # Load + preprocess
    print("  Loading image …")
    target = load_image_smart(IMG, board_w, board_h,
                              panel="left", invert=True)
    weights = compute_edge_weights(target, boost=4.0, sigma=0.8)
    print(f"  Target: {target.shape}  [{target.min():.2f},{target.max():.2f}]  "
          f"mean={target.mean():.2f}")

    config = dict(
        density=density,
        T_start=8.0, T_min=0.001,
        alpha_coarse=0.99998,
        alpha_fine=0.999993,
        iters_coarse=iters_coarse,
        iters_fine=iters_fine,
        coarse_scale=0.5,
        corridor_step=corridor_step,
        border=border,
        seed=seed,
    )

    # Multi-scale SA
    print("  Running multi-scale SA …")
    t0 = time.time()
    best_grid, history = multiscale_sa(target, weights, config)
    sa_time = time.time() - t0
    print(f"  SA done in {sa_time:.1f}s")

    N = compute_N(best_grid)
    loss_sa = visual_loss(N, target, weights)
    print(f"  Post-SA loss: {loss_sa:.1f}  density: {best_grid.mean():.3f}")

    # Solve
    print("  Solving board …")
    t0 = time.time()
    sr = solve_board(best_grid)
    print(f"  Solve done in {time.time()-t0:.1f}s | coverage={sr['coverage']:.4f}")

    # Repair
    if sr["coverage"] < 0.999 and repair_rounds > 0:
        print("  Running targeted repair …")
        t0 = time.time()
        best_grid, sr = targeted_repair(
            best_grid, target, weights,
            max_rounds=repair_rounds,
            search_radius=4, verbose=True)
        print(f"  Repair done in {time.time()-t0:.1f}s | coverage={sr['coverage']:.4f}")

    # Metrics
    N = compute_N(best_grid)
    metrics = {
        "board": f"{board_w}x{board_h}",
        "cells": board_w * board_h,
        "loss": round(visual_loss(N, target, weights), 2),
        "loss_unweighted": round(float(np.sum((N-target)**2)), 2),
        "mine_density": round(float(best_grid.mean()), 4),
        "coverage": sr["coverage"],
        "solvable": sr["solvable"],
        "mine_accuracy": sr["mine_accuracy"],
        "n_unknown": sr["n_unknown"],
        "mean_abs_error": round(float(np.abs(N-target).mean()), 3),
        "max_N": int(N.max()),
    }

    print(f"\n  METRICS [{label}]:")
    for k,v in metrics.items():
        print(f"    {k:<25}: {v}")

    # Render
    slug = label.lower().replace(" ","_")
    render_full_report(
        target, best_grid, sr, history,
        title=f"Minesweeper Reconstruction — {label} ({board_w}×{board_h})",
        save_path=f"{OUT}/iter6_{slug}.png",
        dpi=120)

    save_board_hires(
        best_grid, sr,
        save_path=f"{OUT}/iter6_{slug}_board.png",
        cell_size=max(2, min(8, 600//max(board_w,board_h))),
        dpi=120)

    np.save(f"{OUT}/grid_{slug}.npy", best_grid)
    np.save(f"{OUT}/target_{slug}.npy", target)
    with open(f"{OUT}/metrics_{slug}.json","w") as f:
        json.dump(metrics, f, indent=2)

    return metrics


# ── SCALE 1: Medium (120×75) ─────────────────────────────────
m_med = run_scale(
    board_w=120, board_h=75,
    label="Medium 120x75",
    density=0.22,
    iters_coarse=400_000,
    iters_fine=1_000_000,
    corridor_step=8,
    border=3,
    repair_rounds=50,
    seed=20,
)

# ── SCALE 2: Large (200×125) ─────────────────────────────────
m_lrg = run_scale(
    board_w=200, board_h=125,
    label="Large 200x125",
    density=0.20,
    iters_coarse=500_000,
    iters_fine=1_500_000,
    corridor_step=10,
    border=3,
    repair_rounds=60,
    seed=21,
)

print("\n" + "="*60)
print("SCALE COMPARISON")
print("="*60)
for m in [m_med, m_lrg]:
    print(f"\n  {m['board']} ({m['cells']:,} cells)")
    print(f"    Loss:     {m['loss']}")
    print(f"    Coverage: {m['coverage']:.4f}")
    print(f"    Solvable: {m['solvable']}")
    print(f"    Density:  {m['mine_density']}")

print("\nIteration 6 complete.")

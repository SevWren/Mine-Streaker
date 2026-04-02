from __future__ import annotations

import time

import numpy as np
from PIL import Image as PILImage

from .config import BoardConfig, RunConfig, RuntimeConfig
from .core import assert_board_valid, compute_N, compute_edge_weights, load_image_smart
from .corridors import build_adaptive_corridors
from .diagnostics import analyze_unknowns
from .io_utils import atomic_save_json, atomic_save_npy
from .models import PipelineMetrics, RepairContext
from .repair_phase1 import run_phase1_repair
from .repair_phase2 import run_phase2_swap_repair
from .repair_phase3 import run_phase3_enumeration
from .report import render_report
from .sa import compile_sa_kernel
from .solver import solve_board


def _solve_fn(grid: np.ndarray, deadline_s=None):
    return solve_board(grid, deadline_s=deadline_s)


def _run_board_with_kernel(config: BoardConfig, runtime: RuntimeConfig, sa_fn) -> PipelineMetrics:
    H, W = config.height, config.width
    t_total = time.time()
    slug = config.label.lower().replace(" ", "_").replace("-", "x")
    paths = runtime.paths

    print(f"\n{'=' * 68}")
    print(f"  {config.label}  [{W}x{H} = {W*H:,} cells]")
    print(f"{'=' * 68}")

    target = load_image_smart(str(paths.img), W, H, panel="full", invert=True)
    weights = compute_edge_weights(target, boost=4.0, sigma=0.8)
    print(f"  Target: [{target.min():.1f},{target.max():.1f}]  mean={target.mean():.2f}")

    forbidden, pct, seeds, mst_coo = build_adaptive_corridors(target, border=config.border, corridor_width=0, low_target_bias=5.5)
    hi_blocked = int(np.sum((target > 3) & (forbidden == 1)))
    print(f"  Corridors: {pct:.1f}%  seeds={len(seeds)}  hi-blocked={hi_blocked}")

    Hc, Wc = max(8, H // 2), max(8, W // 2)
    t_c = np.array(PILImage.fromarray(target).resize((Wc, Hc), PILImage.LANCZOS), dtype=np.float32)
    w_c = np.array(PILImage.fromarray(weights).resize((Wc, Hc), PILImage.BILINEAR), dtype=np.float32)
    f_c = (
        np.array(PILImage.fromarray((forbidden.astype(np.uint8) * 255)).resize((Wc, Hc), PILImage.NEAREST)) > 127
    ).astype(np.int8)

    rng = np.random.default_rng(config.seed)
    prob = np.clip(t_c / 8.0 * config.density * 3.0, 0, config.density)
    prob[f_c == 1] = 0
    g_c = (rng.random((Hc, Wc)) < prob).astype(np.int8)
    g_c[f_c == 1] = 0
    N_c = compute_N(g_c).astype(np.float32)

    print(f"  [Coarse {Wc}x{Hc}]  {config.coarse_iters:,} iters")
    t0 = time.time()
    gc, lc, _ = sa_fn(
        g_c.copy(),
        N_c.copy(),
        t_c,
        w_c,
        f_c,
        8.0,
        0.99998,
        0.001,
        config.coarse_iters,
        config.border,
        Hc,
        Wc,
        config.seed,
    )
    print(f"  {time.time()-t0:.1f}s  loss={lc:.0f}")

    gc_img = PILImage.fromarray(gc.astype(np.float32)).resize((W, H), PILImage.NEAREST)
    grid = (np.array(gc_img) > 0.5).astype(np.int8)
    grid[forbidden == 1] = 0
    N_f = compute_N(grid).astype(np.float32)

    print(f"  [Fine {W}x{H}]  {config.fine_iters:,} iters")
    t0 = time.time()
    grid, lf, _ = sa_fn(
        grid.copy(),
        N_f.copy(),
        target,
        weights,
        forbidden,
        config.T_fine,
        0.999995,
        0.001,
        config.fine_iters,
        config.border,
        H,
        W,
        config.seed + 1,
    )
    grid[forbidden == 1] = 0
    print(f"  {time.time()-t0:.1f}s  density={grid.mean():.3f}")

    N_cur = compute_N(grid)
    underfill = np.clip(target - N_cur, 0, 8) / 8.0
    w_aug = (weights * (1.0 + 1.5 * underfill)).astype(np.float32)

    print(f"  [Refine]  {config.refine_iters:,} iters")
    t0 = time.time()
    grid, lr, hist_r = sa_fn(
        grid.copy(),
        compute_N(grid).astype(np.float32),
        target,
        w_aug,
        forbidden,
        config.T_refine,
        0.999996,
        0.001,
        config.refine_iters,
        config.border,
        H,
        W,
        config.seed + 2,
    )
    grid[forbidden == 1] = 0
    print(f"  {time.time()-t0:.1f}s  density={grid.mean():.3f}")
    assert_board_valid(grid, forbidden, f"{config.label} post-SA")

    sr_pre = solve_board(grid)
    n_unk_pre = sr_pre.n_unknown
    budget1 = config.repair1_budget_s if config.repair1_budget_s is not None else max(60.0, n_unk_pre * 0.15 + 30)
    print(f"\n  [Phase 1 Repair]  budget={budget1:.0f}s  (n_unk={n_unk_pre})")

    phase1 = run_phase1_repair(
        RepairContext(
            grid=grid,
            target=target,
            weights=weights,
            forbidden=forbidden,
            label=slug,
            time_budget_s=budget1,
            deadline_s=time.perf_counter() + float(budget1),
            solve_fn=_solve_fn,
            output_dir=str(paths.out_dir),
            verbose=runtime.verbose,
            max_rounds=300,
            batch_size=10,
            search_radius=6,
            checkpoint_every=10,
        )
    )
    grid = phase1.grid
    sr = phase1.solve_result
    reason1 = phase1.reason
    assert_board_valid(grid, forbidden, f"{config.label} post-repair1")
    analyze_unknowns(grid, sr, target, f"{config.label} after Phase 1")

    if sr.n_unknown > 0:
        print(f"\n  [Phase 2 Swap Repair]  budget={config.repair2_budget_s:.0f}s")
        phase2 = run_phase2_swap_repair(
            RepairContext(
                grid=grid,
                target=target,
                weights=weights,
                forbidden=forbidden,
                label=slug,
                time_budget_s=config.repair2_budget_s,
                deadline_s=time.perf_counter() + float(config.repair2_budget_s),
                solve_fn=_solve_fn,
                output_dir=str(paths.out_dir),
                verbose=runtime.verbose,
                max_outer=300,
                initial_solve_result=sr,
            )
        )
        grid = phase2.grid
        sr = phase2.solve_result
        reason2 = phase2.reason
        assert_board_valid(grid, forbidden, f"{config.label} post-repair2")
        analyze_unknowns(grid, sr, target, f"{config.label} after Phase 2")
    else:
        reason2 = "skipped_already_solved"

    if 0 < sr.n_unknown <= config.repair3_max_unknown:
        print(f"\n  [Phase 3 Enumeration]  n_unk={sr.n_unknown}")
        phase3 = run_phase3_enumeration(
            RepairContext(
                grid=grid,
                target=target,
                weights=weights,
                forbidden=forbidden,
                label=slug,
                time_budget_s=0.0,
                deadline_s=None,
                solve_fn=_solve_fn,
                output_dir=str(paths.out_dir),
                verbose=runtime.verbose,
                max_unknown=config.repair3_max_unknown,
                initial_solve_result=sr,
            )
        )
        grid = phase3.grid
        sr = phase3.solve_result
        reason3 = phase3.reason
        assert_board_valid(grid, forbidden, f"{config.label} post-repair3")
        analyze_unknowns(grid, sr, target, f"{config.label} after Phase 3")
    else:
        reason3 = f"skipped (n_unk={sr.n_unknown})"

    N_fin = compute_N(grid)
    err = np.abs(N_fin - target)

    metrics = PipelineMetrics(
        label=config.label,
        board=f"{W}x{H}",
        cells=W * H,
        loss_per_cell=round(float(np.sum((N_fin - target) ** 2)) / (W * H), 4),
        mean_abs_error=round(float(err.mean()), 4),
        pct_within_1=round(float(np.mean(err <= 1.0)) * 100, 2),
        pct_within_2=round(float(np.mean(err <= 2.0)) * 100, 2),
        mine_density=round(float(grid.mean()), 4),
        corridor_pct=pct,
        coverage=sr.coverage,
        solvable=sr.solvable,
        mine_accuracy=sr.mine_accuracy,
        n_unknown=sr.n_unknown,
        repair1_reason=reason1,
        repair2_reason=reason2,
        repair3_reason=reason3,
        total_time_s=round(time.time() - t_total, 1),
    )

    print(f"\n  METRICS [{config.label}]:")
    for k, v in metrics.to_dict().items():
        print(f"    {k:<22}: {v}")

    render_report(
        target,
        grid,
        sr,
        hist_r.tolist(),
        title=f"Iter 10  {config.label}  corridor={pct:.0f}%  density={grid.mean():.3f}",
        save_path=f"{paths.out_dir}/iter10_{slug}_FINAL.png",
        dpi=120,
    )

    atomic_save_npy(grid, f"{paths.out_dir}/grid_iter10_{slug}_FINAL.npy")
    atomic_save_npy(target, f"{paths.out_dir}/target_iter10_{slug}_FINAL.npy")
    atomic_save_json(metrics.to_dict(), f"{paths.out_dir}/metrics_iter10_{slug}_FINAL.json")
    print("   Saved atomically")

    return metrics


def run_board(config: BoardConfig, runtime: RuntimeConfig) -> PipelineMetrics:
    """
    Public API: run a single board configuration.
    Compiles the SA kernel for this run.
    """
    sa_fn = compile_sa_kernel()
    return _run_board_with_kernel(config, runtime, sa_fn)


def run_experiment(config: RunConfig) -> list[PipelineMetrics]:
    print("=" * 68)
    print("ITERATION 10    Mine-Swap Repair for Solvability")
    print("=" * 68)
    print(f"Input image: {config.runtime.paths.img}")
    print(f"Output dir:  {config.runtime.paths.out_dir}")

    print("\n[Step 1] Kernel compilation")
    sa_fn = compile_sa_kernel()

    all_metrics: list[PipelineMetrics] = []
    for idx, board in enumerate(config.boards, start=2):
        step_title = "Primary solvability target" if idx == 2 else "Scale test"
        print(f"\n[Step {idx}] {board.label}   {step_title}")
        all_metrics.append(_run_board_with_kernel(board, config.runtime, sa_fn))

    print("\n" + "=" * 68)
    print("ITERATION 10  FINAL SUMMARY")
    print("=" * 68)
    keys = [
        "cells",
        "loss_per_cell",
        "mean_abs_error",
        "mine_density",
        "corridor_pct",
        "coverage",
        "solvable",
        "n_unknown",
        "repair1_reason",
        "repair2_reason",
        "repair3_reason",
        "total_time_s",
    ]
    labels = [m.label for m in all_metrics]
    col_w = 18
    print(f"\n{'Metric':<22}" + "".join(f" {str(l)[:col_w-1]:>{col_w}}" for l in labels))
    print("-" * (22 + (col_w + 1) * len(labels)))
    for k in keys:
        print(f"{k:<22}" + "".join(f" {str(m.to_dict().get(k,'-'))[:col_w-1]:>{col_w}}" for m in all_metrics))

    print("\nIteration 10 complete")
    return all_metrics

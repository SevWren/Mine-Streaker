from __future__ import annotations

import multiprocessing as mp
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

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
from .runtime import build_repro_fingerprint
from .sa import compile_sa_kernel
from .solver import solve_board

_PIPELINE_WORKER_SA_FN = None


def _clamp_int(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(value)))


def _resolve_deterministic_enabled(runtime: RuntimeConfig) -> bool:
    if runtime.deterministic_order == "on":
        return True
    if runtime.deterministic_order == "off":
        return False
    return bool(runtime.strict_repro)


def _make_solve_fn(runtime: RuntimeConfig) -> tuple[Callable[[np.ndarray, float | None], object], dict[str, float | int], bool]:
    mode = runtime.solver_mode
    deterministic = _resolve_deterministic_enabled(runtime)
    solve_stats: dict[str, float | int] = {
        "sort_calls": 0,
        "sort_items": 0,
        "sort_time_s": 0.0,
    }

    def _solve_fn(grid: np.ndarray, deadline_s=None):
        sr = solve_board(
            grid,
            deadline_s=deadline_s,
            mode=mode,
            deterministic=deterministic,
        )
        solve_stats["sort_calls"] = int(solve_stats["sort_calls"]) + int(getattr(sr, "sort_calls", 0))
        solve_stats["sort_items"] = int(solve_stats["sort_items"]) + int(getattr(sr, "sort_items", 0))
        solve_stats["sort_time_s"] = float(solve_stats["sort_time_s"]) + float(getattr(sr, "sort_time_s", 0.0))
        return sr

    return _solve_fn, solve_stats, deterministic


def _compute_adaptive_repair_budgets(
    *,
    n_unknown_pre: int,
    solve_s0: float,
    phase1_base: float,
    phase2_base: float,
    repair_global_cap_s: float,
) -> dict[str, float]:
    phase1_target_solves = _clamp_int(round(n_unknown_pre * 0.035), 8, 48)
    phase2_target_solves = _clamp_int(round(n_unknown_pre * 0.028), 8, 40)
    solve_ref = max(0.05, float(solve_s0))

    phase1_need = phase1_target_solves * solve_ref * 1.20
    phase2_need = phase2_target_solves * solve_ref * 1.35

    p1_min = max(1.2 * solve_ref, 5.0)
    p2_min = max(1.35 * solve_ref, 5.0)
    cap = max(0.0, float(repair_global_cap_s))
    need1 = 0.7 * phase1_need + 0.3 * float(phase1_base)
    need2 = 0.7 * phase2_need + 0.3 * float(phase2_base)

    if cap <= 0.0:
        phase1_budget = 0.0
        phase2_budget = 0.0
    elif cap < (p1_min + p2_min):
        phase1_budget = cap * 0.5
        phase2_budget = cap - phase1_budget
    else:
        residual = cap - p1_min - p2_min
        need_sum = need1 + need2
        if need_sum > 0:
            phase1_budget = p1_min + residual * (need1 / need_sum)
        else:
            phase1_budget = p1_min + residual * 0.5
        phase2_budget = cap - phase1_budget
    phase1_budget = max(0.0, phase1_budget)
    phase2_budget = max(0.0, phase2_budget)

    return {
        "allocator_version": "v2_nonstarve",
        "phase1_target_solves": float(phase1_target_solves),
        "phase2_target_solves": float(phase2_target_solves),
        "phase1_need_s": float(phase1_need),
        "phase2_need_s": float(phase2_need),
        "need1": float(need1),
        "need2": float(need2),
        "phase1_budget_s": float(phase1_budget),
        "phase2_budget_s": float(phase2_budget),
        "p1_min_s": float(p1_min),
        "p2_min_s": float(p2_min),
        "phase1_starved": bool(cap > 0.0 and phase1_budget <= 0.0),
        "global_cap_s": float(cap),
    }


def _pipeline_worker_init() -> None:
    global _PIPELINE_WORKER_SA_FN
    _PIPELINE_WORKER_SA_FN = compile_sa_kernel()


def _pipeline_worker_run(index: int, board: BoardConfig, runtime: RuntimeConfig) -> tuple[int, dict]:
    global _PIPELINE_WORKER_SA_FN
    if _PIPELINE_WORKER_SA_FN is None:
        _PIPELINE_WORKER_SA_FN = compile_sa_kernel()
    metrics = _run_board_with_kernel(board, runtime, _PIPELINE_WORKER_SA_FN)
    return index, metrics.to_dict()


def _run_board_with_kernel(config: BoardConfig, runtime: RuntimeConfig, sa_fn) -> PipelineMetrics:
    H, W = config.height, config.width
    t_total = time.time()
    slug = config.label.lower().replace(" ", "_").replace("-", "x")
    paths = runtime.paths
    solve_fn, solve_stats, deterministic_enabled = _make_solve_fn(runtime)
    Path(paths.out_dir).mkdir(parents=True, exist_ok=True)

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

    t_solve0 = time.perf_counter()
    sr_pre = solve_fn(grid)
    solve_s0 = max(0.001, time.perf_counter() - t_solve0)

    n_unk_pre = sr_pre.n_unknown
    phase1_base = config.repair1_budget_s if config.repair1_budget_s is not None else max(60.0, n_unk_pre * 0.15 + 30.0)
    phase2_base = float(config.repair2_budget_s)
    repair_global_cap_s = (
        float(runtime.repair_global_cap_s)
        if runtime.repair_global_cap_s is not None
        else float(phase1_base + phase2_base)
    )

    budget_plan = _compute_adaptive_repair_budgets(
        n_unknown_pre=n_unk_pre,
        solve_s0=solve_s0,
        phase1_base=phase1_base,
        phase2_base=phase2_base,
        repair_global_cap_s=repair_global_cap_s,
    )

    global_repair_start = time.perf_counter()
    global_repair_deadline = global_repair_start + repair_global_cap_s
    phase1_elapsed_s = 0.0
    phase2_elapsed_s = 0.0
    phase1_telemetry: dict[str, float | int] = {}
    phase2_telemetry: dict[str, float | int] = {}

    print(
        "\n  [Repair budget] "
        f"global_cap={repair_global_cap_s:.0f}s "
        f"solve_s0={solve_s0:.3f}s "
        f"p1_alloc={budget_plan['phase1_budget_s']:.0f}s "
        f"p2_plan={budget_plan['phase2_budget_s']:.0f}s"
    )

    p1_remaining_global = max(0.0, global_repair_deadline - time.perf_counter())
    phase1_budget = min(budget_plan["phase1_budget_s"], p1_remaining_global)

    sr = sr_pre
    reason1 = "skipped_budget_exhausted"
    if phase1_budget > 0.0:
        print(f"\n  [Phase 1 Repair]  budget={phase1_budget:.0f}s  (n_unk={n_unk_pre})")
        phase1_deadline = min(global_repair_deadline, time.perf_counter() + float(phase1_budget))
        phase1 = run_phase1_repair(
            RepairContext(
                grid=grid,
                target=target,
                weights=weights,
                forbidden=forbidden,
                label=slug,
                time_budget_s=phase1_budget,
                deadline_s=phase1_deadline,
                solve_fn=solve_fn,
                output_dir=str(paths.out_dir),
                verbose=runtime.verbose,
                max_rounds=300,
                batch_size=10,
                search_radius=6,
                checkpoint_every=10,
                initial_solve_result=sr_pre,
                frontier_radius=3,
                enable_low_yield_handoff=True,
                handoff_min_solves=6,
                handoff_window=4,
                handoff_min_rate=0.75,
            )
        )
        grid = phase1.grid
        sr = phase1.solve_result
        reason1 = phase1.reason
        phase1_telemetry = dict(phase1.telemetry)
        phase1_elapsed_s = float(phase1_telemetry.get("elapsed_s", max(0.0, time.perf_counter() - global_repair_start)))
        assert_board_valid(grid, forbidden, f"{config.label} post-repair1")
        analyze_unknowns(grid, sr, target, f"{config.label} after Phase 1")

    p2_remaining_global = max(0.0, global_repair_deadline - time.perf_counter())
    if sr.n_unknown > 0 and p2_remaining_global > 0.0:
        print(f"\n  [Phase 2 Swap Repair]  budget={p2_remaining_global:.0f}s")
        phase2 = run_phase2_swap_repair(
            RepairContext(
                grid=grid,
                target=target,
                weights=weights,
                forbidden=forbidden,
                label=slug,
                time_budget_s=p2_remaining_global,
                deadline_s=global_repair_deadline,
                solve_fn=solve_fn,
                output_dir=str(paths.out_dir),
                verbose=runtime.verbose,
                max_outer=300,
                initial_solve_result=sr,
                frontier_radius=3,
            )
        )
        grid = phase2.grid
        sr = phase2.solve_result
        reason2 = phase2.reason
        phase2_telemetry = dict(phase2.telemetry)
        phase2_elapsed_s = float(phase2_telemetry.get("elapsed_s", max(0.0, time.perf_counter() - global_repair_start - phase1_elapsed_s)))
        assert_board_valid(grid, forbidden, f"{config.label} post-repair2")
        analyze_unknowns(grid, sr, target, f"{config.label} after Phase 2")
    elif sr.n_unknown > 0:
        reason2 = "skipped_budget_exhausted"
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
                solve_fn=solve_fn,
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

    repro_fingerprint = build_repro_fingerprint(
        solver_mode=runtime.solver_mode,
        strict_repro=runtime.strict_repro,
        deterministic_order=runtime.deterministic_order,
    )

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
        solver_mode=runtime.solver_mode,
        repair_global_cap_s=round(repair_global_cap_s, 3),
        repair_phase1_elapsed_s=round(phase1_elapsed_s, 3),
        repair_phase2_elapsed_s=round(phase2_elapsed_s, 3),
        phase1_prefilter_total=int(phase1_telemetry.get("prefilter_total", 0)),
        phase1_prefilter_passed=int(phase1_telemetry.get("prefilter_passed", 0)),
        phase1_prefilter_rejected=int(phase1_telemetry.get("prefilter_rejected", 0)),
        phase1_full_evals=int(phase1_telemetry.get("full_evals", 0)),
        phase1_full_eval_time_s=round(float(phase1_telemetry.get("full_eval_time_s", 0.0)), 4),
        phase2_prefilter_total=int(phase2_telemetry.get("prefilter_total", 0)),
        phase2_prefilter_passed=int(phase2_telemetry.get("prefilter_passed", 0)),
        phase2_prefilter_rejected=int(phase2_telemetry.get("prefilter_rejected", 0)),
        phase2_full_evals=int(phase2_telemetry.get("full_evals", 0)),
        phase2_full_eval_time_s=round(float(phase2_telemetry.get("full_eval_time_s", 0.0)), 4),
        allocator_version=str(budget_plan.get("allocator_version", "")),
        phase1_alloc_s=round(float(budget_plan.get("phase1_budget_s", 0.0)), 3),
        phase2_alloc_s=round(float(budget_plan.get("phase2_budget_s", 0.0)), 3),
        phase1_starved=bool(budget_plan.get("phase1_starved", False)),
        deterministic_order="on" if deterministic_enabled else "off",
        deterministic_sort_calls_total=int(solve_stats.get("sort_calls", 0)),
        deterministic_sort_items_total=int(solve_stats.get("sort_items", 0)),
        deterministic_sort_time_s_total=round(float(solve_stats.get("sort_time_s", 0.0)), 6),
        repair_phase1_telemetry=phase1_telemetry,
        repair_phase2_telemetry=phase2_telemetry,
        parallel_jobs=max(1, int(max(getattr(runtime, "board_jobs", 1), getattr(runtime, "benchmark_jobs", 1)))),
        parallel_enabled=bool(max(getattr(runtime, "board_jobs", 1), getattr(runtime, "benchmark_jobs", 1)) > 1),
        repro_fingerprint=repro_fingerprint,
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

    all_metrics: list[PipelineMetrics] = []
    board_jobs = max(1, int(getattr(config.runtime, "board_jobs", 1)))
    tasks_submitted = len(config.boards)
    tasks_completed = 0
    tasks_cancelled = 0
    if board_jobs <= 1 or len(config.boards) <= 1:
        print("\n[Step 1] Kernel compilation")
        sa_fn = compile_sa_kernel()
        for idx, board in enumerate(config.boards, start=2):
            step_title = "Primary solvability target" if idx == 2 else "Scale test"
            print(f"\n[Step {idx}] {board.label}   {step_title}")
            all_metrics.append(_run_board_with_kernel(board, config.runtime, sa_fn))
        tasks_completed = len(all_metrics)
    else:
        workers = min(board_jobs, len(config.boards))
        print(f"\n[Step 1] Parallel board execution  workers={workers}")
        print("  Each worker compiles SA kernel once.")
        ctx = mp.get_context("spawn")
        future_map = {}
        results: dict[int, PipelineMetrics] = {}
        try:
            with ProcessPoolExecutor(
                max_workers=workers,
                mp_context=ctx,
                initializer=_pipeline_worker_init,
            ) as executor:
                for idx, board in enumerate(config.boards):
                    fut = executor.submit(_pipeline_worker_run, idx, board, config.runtime)
                    future_map[fut] = idx
                for fut in as_completed(future_map):
                    idx = future_map[fut]
                    idx_out, payload = fut.result()
                    results[idx_out] = PipelineMetrics.from_dict(payload)
                    tasks_completed += 1
                    print(f"  [Parallel boards] completed {tasks_completed}/{tasks_submitted}: {config.boards[idx].label}")
                all_metrics = [results[i] for i in range(len(config.boards))]
        except Exception:
            for fut in future_map:
                fut.cancel()
            tasks_cancelled = max(0, tasks_submitted - tasks_completed)
            raise
        tasks_cancelled = max(0, tasks_submitted - tasks_completed)

    parallel_jobs = max(1, int(max(getattr(config.runtime, "board_jobs", 1), getattr(config.runtime, "benchmark_jobs", 1))))
    parallel_enabled = bool(parallel_jobs > 1)
    for m in all_metrics:
        m.parallel_jobs = parallel_jobs
        m.parallel_enabled = parallel_enabled
        m.parallel_tasks_submitted = int(tasks_submitted)
        m.parallel_tasks_completed = int(tasks_completed)
        m.parallel_tasks_cancelled = int(tasks_cancelled)

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
        "solver_mode",
        "deterministic_order",
        "repair_global_cap_s",
        "phase1_alloc_s",
        "phase2_alloc_s",
        "phase1_starved",
        "repair1_reason",
        "repair2_reason",
        "repair3_reason",
        "repair_phase1_elapsed_s",
        "repair_phase2_elapsed_s",
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

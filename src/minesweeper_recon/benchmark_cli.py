from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .benchmark import build_standard_matrix, evaluate_acceptance_gates, run_benchmark_matrix, summarize_by_board
from .config import PathsConfig, RunConfig, RuntimeConfig
from .models import PipelineMetrics
from .preflight import (
    check_required_modules_or_raise,
    configure_mplconfigdir,
    enforce_strict_repro_or_raise,
    maybe_reexec_with_strict_repro,
    ensure_output_dir,
    validate_image_path,
)
from .runtime import ConfigError, DependencyError, OutputError

_BENCHMARK_WORKER_SA_FN = None


def _parse_args(defaults: PathsConfig, argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Iteration 10 A/B benchmark matrix and emit gate report.")
    parser.add_argument("--img", default=str(defaults.img), help="Input source image path.")
    parser.add_argument("--out", default=str(defaults.repo_root / "results" / "iter10_win10_ab"), help="Output root directory.")
    parser.add_argument("--modes", nargs="+", choices=("legacy", "fast"), default=["legacy", "fast"], help="Solver modes to benchmark.")
    parser.add_argument("--seeds", nargs="+", type=int, default=[300, 301, 302], help="Random seeds.")
    parser.add_argument(
        "--boards",
        nargs="+",
        default=["200x125", "250x156", "250x250"],
        help="Board tokens (for example 200x125 250x156 250x250).",
    )
    parser.add_argument(
        "--deterministic-order",
        choices=("auto", "on", "off"),
        default="auto",
        help="Deterministic ordering policy.",
    )
    strict_group = parser.add_mutually_exclusive_group()
    strict_group.add_argument("--strict-repro", dest="strict_repro", action="store_true", help="Enable strict reproducibility checks (default).")
    strict_group.add_argument("--no-strict-repro", dest="strict_repro", action="store_false", help="Disable strict reproducibility checks.")
    parser.set_defaults(strict_repro=True)
    parser.add_argument("--repair-global-cap-s", type=float, default=None, help="Optional global repair cap override in seconds.")
    parser.add_argument(
        "--repair-eval-jobs",
        type=int,
        default=1,
        help="Parallel worker processes for repair candidate evaluation inside each board run (default: 1).",
    )
    parser.add_argument("--jobs", type=int, default=1, help="Parallel worker processes for benchmark tasks (default: 1).")
    parser.add_argument(
        "--failure-policy",
        choices=("fail_fast", "continue"),
        default="fail_fast",
        help="Worker failure behavior in parallel mode (default: fail_fast).",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose pipeline output.")
    return parser.parse_args(argv)


def _benchmark_worker_init() -> None:
    global _BENCHMARK_WORKER_SA_FN
    from .sa import compile_sa_kernel

    _BENCHMARK_WORKER_SA_FN = compile_sa_kernel()


def _benchmark_worker_run(task_index: int, mode: str, board, runtime: RuntimeConfig) -> tuple[int, str, dict]:
    global _BENCHMARK_WORKER_SA_FN
    from .pipeline import _run_board_with_kernel
    from .sa import compile_sa_kernel

    if _BENCHMARK_WORKER_SA_FN is None:
        _BENCHMARK_WORKER_SA_FN = compile_sa_kernel()
    metrics = _run_board_with_kernel(board, runtime, _BENCHMARK_WORKER_SA_FN)
    return task_index, mode, metrics.to_dict()


def _collect_reason_counts(metrics) -> dict[str, dict[str, dict[str, int]]]:
    out: dict[str, dict[str, dict[str, int]]] = {}
    for m in metrics:
        board = m.board
        out.setdefault(board, {"repair1_reason": {}, "repair2_reason": {}})
        r1 = str(m.repair1_reason)
        r2 = str(m.repair2_reason)
        out[board]["repair1_reason"][r1] = out[board]["repair1_reason"].get(r1, 0) + 1
        out[board]["repair2_reason"][r2] = out[board]["repair2_reason"].get(r2, 0) + 1
    return out


def _write_summary_csv(path: Path, summary_by_mode: dict[str, dict[str, dict[str, dict[str, float | int]]]], gates: dict[str, object]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["section", "mode", "board", "metric", "median", "min", "max", "n", "result"])
        for mode, board_map in summary_by_mode.items():
            for board, metric_map in board_map.items():
                for metric, stats in metric_map.items():
                    writer.writerow(
                        [
                            "summary",
                            mode,
                            board,
                            metric,
                            stats.get("median"),
                            stats.get("min"),
                            stats.get("max"),
                            stats.get("n"),
                            "",
                        ]
                    )
        checks = gates.get("checks", {}) if isinstance(gates, dict) else {}
        for check, value in checks.items():
            writer.writerow(["gate", "", "", check, "", "", "", "", str(bool(value))])


def main(argv=None) -> int:
    defaults = PathsConfig()
    args = _parse_args(defaults, argv=argv)
    raw_argv = list(argv) if argv is not None else sys.argv[1:]

    img = Path(args.img).expanduser().resolve()
    out_root = Path(args.out).expanduser().resolve()

    try:
        if int(args.jobs) < 1:
            raise ConfigError(f"--jobs must be >= 1 (got {args.jobs})")
        if int(args.repair_eval_jobs) < 1:
            raise ConfigError(f"--repair-eval-jobs must be >= 1 (got {args.repair_eval_jobs})")
        script_path = Path(sys.argv[0]).resolve()
        reexec_code = maybe_reexec_with_strict_repro(
            strict_repro=bool(args.strict_repro),
            script_path=script_path,
            argv=raw_argv,
            python_executable=Path(sys.executable),
        )
        if reexec_code is not None:
            return int(reexec_code)
        enforce_strict_repro_or_raise(
            strict_repro=bool(args.strict_repro),
            script_path=script_path,
            argv=raw_argv,
            python_executable=Path(sys.executable),
        )
        check_required_modules_or_raise()
        validate_image_path(img)
        configure_mplconfigdir()
        ensure_output_dir(out_root)

        boards = build_standard_matrix(seeds=list(args.seeds), board_tokens=list(args.boards))
        metric_keys = ["coverage", "n_unknown", "mean_abs_error", "total_time_s", "loss_per_cell", "mine_accuracy"]
        metrics_by_mode = {}
        summary_by_mode = {}
        reasons_by_mode = {}
        failed_tasks: list[dict[str, str]] = []
        t_bench_start = time.perf_counter()

        print("=" * 68)
        print("ITERATION 10 A/B BENCHMARK")
        print("=" * 68)
        print(f"Input image: {img}")
        print(f"Output dir:  {out_root}")
        print(f"Modes:       {', '.join(args.modes)}")
        print(f"Boards:      {', '.join(args.boards)}")
        print(f"Seeds:       {', '.join(str(s) for s in args.seeds)}")
        print(f"Strict repro: {bool(args.strict_repro)}")
        print(f"Deterministic order: {args.deterministic_order}")
        print(f"Parallel jobs: {int(args.jobs)}")
        print(f"Failure policy: {args.failure_policy}")
        if args.repair_global_cap_s is not None:
            print(f"Repair global cap override: {args.repair_global_cap_s}s")

        jobs = int(args.jobs)
        if jobs <= 1:
            for mode in args.modes:
                mode_t0 = time.perf_counter()
                mode_out = out_root / mode
                ensure_output_dir(mode_out)
                print("\n" + "-" * 68)
                print(f"[Mode: {mode}] start  out={mode_out}")
                print("-" * 68)
                runtime = RuntimeConfig(
                    paths=PathsConfig(repo_root=defaults.repo_root, img=img, out_dir=mode_out),
                    verbose=bool(args.verbose),
                    solver_mode=mode,
                    strict_repro=bool(args.strict_repro),
                    deterministic_order=args.deterministic_order,
                repair_global_cap_s=args.repair_global_cap_s,
                benchmark_jobs=jobs,
                repair_eval_jobs=int(args.repair_eval_jobs),
                failure_policy=args.failure_policy,
            )
                run_cfg = RunConfig(runtime=runtime, boards=boards)
                metrics = run_benchmark_matrix(run_cfg, boards=boards)
                metrics_by_mode[mode] = metrics
                summary_by_mode[mode] = summarize_by_board(metrics, metric_keys)
                reasons_by_mode[mode] = _collect_reason_counts(metrics)
                print(f"[Mode: {mode}] complete in {time.perf_counter() - mode_t0:.1f}s")
        else:
            print("\n" + "-" * 68)
            print(f"[Parallel benchmark] launching {jobs} workers across mode/board/seed tasks")
            print("-" * 68)

            task_meta: list[tuple[str, str]] = []
            task_specs = []
            seen_keys = set()
            for mode in args.modes:
                mode_out = out_root / mode
                ensure_output_dir(mode_out)
                runtime = RuntimeConfig(
                    paths=PathsConfig(repo_root=defaults.repo_root, img=img, out_dir=mode_out),
                    verbose=bool(args.verbose),
                    solver_mode=mode,
                    strict_repro=bool(args.strict_repro),
                    deterministic_order=args.deterministic_order,
                    repair_global_cap_s=args.repair_global_cap_s,
                    benchmark_jobs=jobs,
                    repair_eval_jobs=int(args.repair_eval_jobs),
                    failure_policy=args.failure_policy,
                )
                for board in boards:
                    key = (mode, board.label)
                    if key in seen_keys:
                        raise ConfigError(f"Duplicate benchmark task key detected: mode={mode}, board={board.label}")
                    seen_keys.add(key)
                    task_index = len(task_specs)
                    task_meta.append((mode, board.label))
                    task_specs.append((task_index, mode, board, runtime))

            total_tasks = len(task_specs)
            print(f"[Parallel benchmark] task_count={total_tasks}")

            per_mode_results: dict[str, dict[int, PipelineMetrics]] = {mode: {} for mode in args.modes}
            completed = 0
            cancelled = 0
            ctx = mp.get_context("spawn")
            future_map = {}

            with ProcessPoolExecutor(
                max_workers=min(jobs, total_tasks),
                mp_context=ctx,
                initializer=_benchmark_worker_init,
            ) as executor:
                for spec in task_specs:
                    fut = executor.submit(_benchmark_worker_run, *spec)
                    future_map[fut] = spec[0]

                for fut in as_completed(future_map):
                    task_index = future_map[fut]
                    mode, board_label = task_meta[task_index]
                    try:
                        idx_out, mode_out, payload = fut.result()
                        per_mode_results[mode_out][idx_out] = PipelineMetrics.from_dict(payload)
                        completed += 1
                        print(
                            f"[Parallel benchmark] completed {completed}/{total_tasks}"
                            f" mode={mode_out} board={board_label}"
                        )
                    except Exception as exc:
                        failed_tasks.append(
                            {
                                "mode": mode,
                                "board": board_label,
                                "error": f"{type(exc).__name__}: {exc}",
                            }
                        )
                        if args.failure_policy == "fail_fast":
                            for pending in future_map:
                                if not pending.done():
                                    pending.cancel()
                                    cancelled += 1
                            raise ConfigError(
                                f"Parallel benchmark task failed (mode={mode}, board={board_label}): {type(exc).__name__}: {exc}"
                            ) from exc

            cancelled += max(0, total_tasks - completed - len(failed_tasks))

            for mode in args.modes:
                ordered = [per_mode_results[mode][i] for i in sorted(per_mode_results[mode])]
                for m in ordered:
                    m.parallel_jobs = jobs
                    m.parallel_enabled = jobs > 1
                    m.parallel_tasks_submitted = total_tasks
                    m.parallel_tasks_completed = completed
                    m.parallel_tasks_cancelled = cancelled
                metrics_by_mode[mode] = ordered
                summary_by_mode[mode] = summarize_by_board(ordered, metric_keys) if ordered else {}
                reasons_by_mode[mode] = _collect_reason_counts(ordered) if ordered else {}

        gates = {}
        if "fast" in summary_by_mode and "legacy" in summary_by_mode:
            gates = evaluate_acceptance_gates(
                fast_summary=summary_by_mode["fast"],
                legacy_summary=summary_by_mode["legacy"],
            )

        payload = {
            "modes": list(args.modes),
            "boards": list(args.boards),
            "seeds": list(args.seeds),
            "strict_repro": bool(args.strict_repro),
            "deterministic_order": args.deterministic_order,
            "repair_global_cap_s": args.repair_global_cap_s,
            "summary_by_mode": summary_by_mode,
            "reason_counts_by_mode": reasons_by_mode,
            "gates": gates,
            "parallel_jobs": jobs,
            "repair_eval_jobs": int(args.repair_eval_jobs),
            "failure_policy": args.failure_policy,
            "failed_tasks": failed_tasks,
        }
        summary_json = out_root / "summary_ab.json"
        summary_csv = out_root / "summary_ab.csv"
        summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _write_summary_csv(summary_csv, summary_by_mode, gates)
        print(f"Saved benchmark summary JSON: {summary_json}")
        print(f"Saved benchmark summary CSV:  {summary_csv}")
        print(f"Benchmark total elapsed: {time.perf_counter() - t_bench_start:.1f}s")
        if gates:
            print(f"Gate overall pass: {gates.get('overall_pass')}")
            if gates.get("failed_checks"):
                print(f"Failed checks: {', '.join(gates['failed_checks'])}")
        return 0
    except DependencyError as exc:
        print(f"ERROR: {exc}")
        return 2
    except ConfigError as exc:
        print(f"ERROR: {exc}")
        return 3
    except OutputError as exc:
        print(f"ERROR: {exc}")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())

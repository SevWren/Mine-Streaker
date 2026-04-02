from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

from .benchmark import build_standard_matrix, evaluate_acceptance_gates, run_benchmark_matrix, summarize_by_board
from .config import PathsConfig, RunConfig, RuntimeConfig
from .preflight import (
    check_required_modules_or_raise,
    configure_mplconfigdir,
    enforce_strict_repro_or_raise,
    maybe_reexec_with_strict_repro,
    ensure_output_dir,
    validate_image_path,
)
from .runtime import ConfigError, DependencyError, OutputError


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
    parser.add_argument("--verbose", action="store_true", help="Enable verbose pipeline output.")
    return parser.parse_args(argv)


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
        if args.repair_global_cap_s is not None:
            print(f"Repair global cap override: {args.repair_global_cap_s}s")

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
            )
            run_cfg = RunConfig(runtime=runtime, boards=boards)
            metrics = run_benchmark_matrix(run_cfg, boards=boards)
            metrics_by_mode[mode] = metrics
            summary_by_mode[mode] = summarize_by_board(metrics, metric_keys)
            reasons_by_mode[mode] = _collect_reason_counts(metrics)
            print(f"[Mode: {mode}] complete in {time.perf_counter() - mode_t0:.1f}s")

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

"""
iter13_benchmark_ab.py
======================
Standard benchmark matrix for Iteration 13.

Runs the 3-board × 3-seed matrix and emits summary_ab.json / summary_ab.csv
with acceptance gate evaluation against the Iter10 primary baseline.

Usage (PowerShell):
    $env:PYTHONHASHSEED='0'
    python docs/claude_iteration_13/iter13_benchmark_ab.py `
        --modes fast `
        --boards 200x125 250x156 250x250 `
        --seeds 300 301 302 `
        --strict-repro `
        --deterministic-order on `
        --baseline-summary D:/Github/Minesweeper-Draft/results/iter10/iter10_win10_ab/summary_ab.json `
        --verbose

Iter13 acceptance gates (vs iter10 median baseline):
    1. No coverage regression on 200x125 and 250x250
    2. n_unknown equal or lower on median
    3. mean_abs_error equal or lower at 250x250
    4. 250x250 runtime < 180s
    5. 250x156 must not regress vs iter10 on both coverage AND n_unknown
       (this is the gate iter12 failed)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from statistics import median

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2] if len(SCRIPT_PATH.parents) >= 3 else SCRIPT_PATH.parent
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from minesweeper_recon.benchmark_cli import main as _benchmark_main


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _med(summary: dict, board: str, metric: str) -> float | None:
    try:
        return float(summary[board][metric]["median"])
    except (KeyError, TypeError):
        return None


def _evaluate_iter13_gates(
    iter13_summary: dict,
    baseline_summary: dict,
) -> dict:
    """
    Evaluate Iter13-specific acceptance gates.
    Gate 5 (250x156 non-regression) is the new one iter12 failed.
    """
    def check_ge(board, metric):
        c = _med(iter13_summary, board, metric)
        b = _med(baseline_summary, board, metric)
        if c is None or b is None:
            return None, c, b
        return c >= b - 1e-9, c, b

    def check_le(board, metric):
        c = _med(iter13_summary, board, metric)
        b = _med(baseline_summary, board, metric)
        if c is None or b is None:
            return None, c, b
        return c <= b + 1e-9, c, b

    def check_lt(board, metric, limit):
        c = _med(iter13_summary, board, metric)
        if c is None:
            return None, c, limit
        return c < limit, c, limit

    gates = {}

    ok, c, b = check_ge("200x125", "coverage")
    gates["coverage_non_regression_200x125"] = {"pass": ok, "iter13": c, "baseline": b}

    ok, c, b = check_ge("250x250", "coverage")
    gates["coverage_non_regression_250x250"] = {"pass": ok, "iter13": c, "baseline": b}

    ok, c, b = check_le("200x125", "n_unknown")
    gates["n_unknown_non_increasing_200x125"] = {"pass": ok, "iter13": c, "baseline": b}

    ok, c, b = check_le("250x250", "n_unknown")
    gates["n_unknown_non_increasing_250x250"] = {"pass": ok, "iter13": c, "baseline": b}

    ok, c, b = check_le("250x250", "mean_abs_error")
    gates["mae_non_increasing_250x250"] = {"pass": ok, "iter13": c, "baseline": b}

    ok, c, b = check_lt("250x250", "total_time_s", 180.0)
    gates["runtime_target_250x250_lt_180s"] = {"pass": ok, "iter13": c, "baseline": b}

    # Gate 5: 250x156 must not regress on BOTH coverage AND n_unknown
    cov_ok, cov_c, cov_b = check_ge("250x156", "coverage")
    unk_ok, unk_c, unk_b = check_le("250x156", "n_unknown")
    gate5_pass = (cov_ok is not None and unk_ok is not None and cov_ok and unk_ok)
    gates["250x156_non_regression_coverage_AND_n_unknown"] = {
        "pass": gate5_pass,
        "coverage_iter13": cov_c, "coverage_baseline": cov_b,
        "n_unknown_iter13": unk_c, "n_unknown_baseline": unk_b,
        "note": "iter12 failed this gate (cov 0.9916->0.9898, unk 285->342)"
    }

    overall = all(v["pass"] is True for v in gates.values())
    failed = [k for k, v in gates.items() if v["pass"] is False]
    unclear = [k for k, v in gates.items() if v["pass"] is None]

    return {
        "overall_pass": overall,
        "gates": gates,
        "failed_gates": failed,
        "unclear_gates": unclear,
    }


def _print_gate_report(gate_result: dict) -> None:
    print("\n" + "=" * 68)
    print("ITERATION 13 — GATE EVALUATION")
    print("=" * 68)
    for gate_name, info in gate_result["gates"].items():
        status = "PASS ✓" if info["pass"] else ("FAIL ✗" if info["pass"] is False else "N/A ?")
        print(f"  {status}  {gate_name}")
        for k, v in info.items():
            if k == "pass":
                continue
            print(f"         {k}: {v}")
    print()
    overall = gate_result["overall_pass"]
    print(f"  OVERALL: {'ACCEPTED ✓' if overall else 'REJECTED ✗'}")
    if gate_result["failed_gates"]:
        print(f"  Failed gates: {', '.join(gate_result['failed_gates'])}")


def main(argv=None) -> int:
    # Parse iter13-specific args first, then pass the rest to benchmark_cli
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--baseline-summary", default=None)
    parser.add_argument("--baseline-commit", default="")
    our_args, remaining = parser.parse_known_args(argv or sys.argv[1:])

    # Redirect output to iter13 directory
    has_out = any(a.startswith("--out") for a in remaining)
    if not has_out:
        out_dir = str(REPO_ROOT / "results" / "iter13" / "iter13_win13_ab")
        remaining = ["--out", out_dir] + remaining

    # Run the benchmark
    t0 = time.perf_counter()
    rc = _benchmark_main(remaining)
    elapsed = time.perf_counter() - t0

    # Post-process: load the summary and run gate evaluation
    out_dir_path = Path(next(
        (remaining[i+1] for i, a in enumerate(remaining) if a == "--out"),
        str(REPO_ROOT / "results" / "iter13" / "iter13_win13_ab")
    ))
    summary_path = out_dir_path / "summary_ab.json"

    if summary_path.exists() and our_args.baseline_summary:
        try:
            iter13_payload = _load_json(summary_path)
            baseline_payload = _load_json(Path(our_args.baseline_summary))

            # Extract the fast-mode summary by board
            iter13_by_board = iter13_payload.get("summary_by_mode", {}).get("fast", {})
            baseline_by_board = baseline_payload.get("summary_by_mode", {}).get("fast", {})

            if iter13_by_board and baseline_by_board:
                gate_result = _evaluate_iter13_gates(iter13_by_board, baseline_by_board)
                _print_gate_report(gate_result)

                # Write gate result alongside the summary
                gate_path = out_dir_path / "iter13_gate_result.json"
                gate_result_serializable = {
                    "overall_pass": gate_result["overall_pass"],
                    "failed_gates": gate_result["failed_gates"],
                    "unclear_gates": gate_result["unclear_gates"],
                    "gates": {k: {str(kk): str(vv) for kk, vv in v.items()}
                              for k, v in gate_result["gates"].items()},
                    "baseline_summary": str(our_args.baseline_summary),
                    "baseline_commit": our_args.baseline_commit,
                    "iter13_hypothesis": (
                        "Phase2 stagnation_rounds 4->8, max_mines 16->24, "
                        "solver subset_cap 1200->2400 under deadline"
                    ),
                    "elapsed_s": round(elapsed, 1),
                }
                gate_path.write_text(json.dumps(gate_result_serializable, indent=2), encoding="utf-8")
                print(f"\n  Gate result saved: {gate_path}")
            else:
                print("\n  ⚠ Could not extract fast-mode summaries for gate evaluation")
                print(f"    iter13 modes: {list(iter13_payload.get('summary_by_mode', {}).keys())}")
                print(f"    baseline modes: {list(baseline_payload.get('summary_by_mode', {}).keys())}")
        except Exception as exc:
            print(f"\n  ⚠ Gate evaluation failed: {exc}")
    elif not our_args.baseline_summary:
        print("\n  ℹ  No --baseline-summary provided — skipping gate evaluation")
        print("     Re-run with --baseline-summary path/to/iter10/summary_ab.json")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())

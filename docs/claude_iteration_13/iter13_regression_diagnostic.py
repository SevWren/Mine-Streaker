"""
iter13_regression_diagnostic.py
================================
PURPOSE
-------
Isolate which specific iter12 change caused the 250x156 coverage/n_unknown
regression before writing any fixes.

WHAT ITER12 CHANGED (all toggleable via BoardConfig knobs)
----------------------------------------------------------
Group A — New pipeline stages that consume global repair budget:
  A1. Inter-repair SA between Phase1 and Phase2
        iter12 value:  inter_repair_sa_iters = 400_000 (ROI-focused)
        revert to:     inter_repair_sa_iters = 0  (disabled, same as iter11 decision)

  A2. Deterministic pattern-breaker before Phase2
        iter12 value:  pattern_breaker_enabled = True
        revert to:     pattern_breaker_enabled = False

Group B — Phase2 caps tightened vs pre-iter12 getattr() fallback values:
  B1. delta_shortlist:  16 (iter12)  →  24 (pre-iter12 fallback)
  B2. beam_width:        4 (iter12)  →   6 (pre-iter12 fallback)
  B3. beam_branch:       6 (iter12)  →   8 (pre-iter12 fallback)
  B4. fullsolve_cap:     4 (iter12)  →   8 (pre-iter12 fallback)

DIAGNOSTIC CONDITIONS
---------------------
C0  BASELINE       — iter12 defaults, should reproduce the regression
C1  NO_INTER_SA    — disable inter-repair SA only (A1 reverted)
C2  NO_PATTERN_BK  — disable pattern-breaker only (A2 reverted)
C3  WIDER_P2_CAPS  — restore all Phase2 caps to pre-iter12 values (all B reverted)
C4  NO_STAGES      — C1 + C2 (both new stages disabled, Phase2 caps unchanged)
C5  NO_BK_WIDE_P2  — C2 + C3 (no pattern-breaker, wider Phase2 caps)
C6  ALL_REVERTED   — C1 + C2 + C3 (everything reverted to pre-iter12)

READING THE RESULTS
-------------------
If C1 alone recovers 250x156 → inter-repair SA is stealing budget from Phase2
If C2 alone recovers 250x156 → pattern-breaker is stealing budget from Phase2
If C3 alone recovers 250x156 → iter12 over-tightened Phase2 caps (most likely)
If C4 recovers but C1/C2 alone don't → both new stages together steal too much
If C6 recovers but nothing else does → interaction effect between stages and caps
If nothing recovers → the regression has a different root cause entirely

STRATEGY
--------
Run all conditions on 250x156 (the regressed board) with 3 seeds first.
Then run the winning condition(s) on the full 3-board matrix to confirm
no new regressions were introduced.

Results are written to:
    results/iter13_diagnostic/diagnostic_summary.json
    results/iter13_diagnostic/diagnostic_comparison.csv
    results/iter13_diagnostic/diagnostic_verdict.txt

USAGE
-----
    $env:PYTHONHASHSEED='0'
    python docs/claude_iteration_13/iter13_regression_diagnostic.py --strict-repro

With a specific board only (faster, for quick iteration):
    python ... --boards 250x156 --seeds 300 301 302

With a subset of conditions (e.g. test Phase2 caps first):
    python ... --conditions C0 C3 C6
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import replace
from pathlib import Path
from statistics import median
from typing import NamedTuple

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2] if len(SCRIPT_PATH.parents) >= 3 else SCRIPT_PATH.parent
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from minesweeper_recon.benchmark import build_standard_matrix
from minesweeper_recon.config import BoardConfig, PathsConfig, RunConfig, RuntimeConfig
from minesweeper_recon.models import PipelineMetrics
from minesweeper_recon.preflight import (
    check_required_modules_or_raise,
    configure_mplconfigdir,
    enforce_strict_repro_or_raise,
    ensure_output_dir,
    maybe_reexec_with_strict_repro,
    validate_image_path,
)
from minesweeper_recon.runtime import ConfigError, DependencyError


# ─── Condition definitions ────────────────────────────────────────────────────

class Condition(NamedTuple):
    name: str
    label: str          # short label for table columns
    description: str    # what was changed relative to iter12 baseline
    overrides: dict     # BoardConfig field overrides


# iter12 baseline values (reproduced here for clarity and documentation)
ITER12_DEFAULTS = dict(
    inter_repair_sa_iters   = 400_000,   # ROI-focused SA between P1 and P2
    pattern_breaker_enabled = True,      # deterministic 50/50 pattern-breaker
    phase2_delta_shortlist  = 16,        # tightened from pre-iter12 fallback of 24
    phase2_beam_width       = 4,         # tightened from pre-iter12 fallback of 6
    phase2_beam_branch      = 6,         # tightened from pre-iter12 fallback of 8
    phase2_fullsolve_cap    = 4,         # tightened from pre-iter12 fallback of 8
)

# Pre-iter12 values (the getattr() fallback values in repair_phase2.py)
PRE_ITER12_P2 = dict(
    phase2_delta_shortlist  = 24,
    phase2_beam_width       = 6,
    phase2_beam_branch      = 8,
    phase2_fullsolve_cap    = 8,
)


CONDITIONS: list[Condition] = [
    Condition(
        name="C0",
        label="baseline",
        description="iter12 defaults — should reproduce the 250x156 regression",
        overrides={},   # nothing changed from iter12 config defaults
    ),
    Condition(
        name="C1",
        label="no_inter_sa",
        description="Disable inter-repair SA only (A1 reverted). "
                    "Tests whether SA stage steals enough budget to cause regression.",
        overrides=dict(
            inter_repair_sa_iters=0,
        ),
    ),
    Condition(
        name="C2",
        label="no_pattern_bk",
        description="Disable pattern-breaker only (A2 reverted). "
                    "Tests whether pattern-breaker stage steals enough budget.",
        overrides=dict(
            pattern_breaker_enabled=False,
        ),
    ),
    Condition(
        name="C3",
        label="wider_p2_caps",
        description="Restore all Phase2 caps to pre-iter12 values (B reverted). "
                    "Tests whether iter12 over-tightened Phase2 search width.",
        overrides=dict(**PRE_ITER12_P2),
    ),
    Condition(
        name="C4",
        label="no_stages",
        description="Disable both new pipeline stages (A1+A2 reverted), Phase2 unchanged. "
                    "Tests whether the two stages together steal enough budget.",
        overrides=dict(
            inter_repair_sa_iters=0,
            pattern_breaker_enabled=False,
        ),
    ),
    Condition(
        name="C5",
        label="no_bk_wide_p2",
        description="No pattern-breaker + wider Phase2 caps (A2+B reverted). "
                    "Tests interaction between pattern-breaker budget cost and Phase2 width.",
        overrides=dict(
            pattern_breaker_enabled=False,
            **PRE_ITER12_P2,
        ),
    ),
    Condition(
        name="C6",
        label="all_reverted",
        description="All iter12 changes reverted (A1+A2+B). "
                    "If this recovers 250x156 but nothing else does, there is an interaction.",
        overrides=dict(
            inter_repair_sa_iters=0,
            pattern_breaker_enabled=False,
            **PRE_ITER12_P2,
        ),
    ),
]

CONDITION_MAP = {c.name: c for c in CONDITIONS}


# ─── Board construction ───────────────────────────────────────────────────────

def make_diagnostic_boards(
    condition: Condition,
    board_tokens: list[str],
    seeds: list[int],
) -> list[BoardConfig]:
    """
    Build the standard board matrix for this condition.
    Applies condition.overrides on top of iter12 config defaults.
    The label is prefixed with the condition name so results stay separate.
    """
    base_boards = build_standard_matrix(seeds=seeds, board_tokens=board_tokens)
    patched = []
    for board in base_boards:
        patched_label = f"{condition.name}_{board.label}"
        # replace() creates a new frozen dataclass with the overridden fields
        patched_board = replace(board, label=patched_label, **condition.overrides)
        patched.append(patched_board)
    return patched


# ─── Running a single condition ───────────────────────────────────────────────

def run_condition(
    condition: Condition,
    board_tokens: list[str],
    seeds: list[int],
    runtime: RuntimeConfig,
    verbose: bool = True,
) -> list[PipelineMetrics]:
    from minesweeper_recon.pipeline import run_experiment

    if verbose:
        print(f"\n{'─'*68}")
        print(f"  Condition {condition.name}: {condition.label}")
        print(f"  {condition.description}")
        print(f"  Overrides: {condition.overrides if condition.overrides else '(none — iter12 baseline)'}")
        print(f"{'─'*68}")

    boards = make_diagnostic_boards(condition, board_tokens, seeds)
    run_cfg = RunConfig(runtime=runtime, boards=boards)

    t0 = time.perf_counter()
    metrics = run_experiment(run_cfg)
    elapsed = time.perf_counter() - t0

    if verbose:
        print(f"\n  Condition {condition.name} complete in {elapsed:.1f}s")
        # Quick summary by board
        for board_token in board_tokens:
            board_metrics = [m for m in metrics
                             if m.board == board_token]
            if not board_metrics:
                # label format: e.g. "200x125" vs "200x125"
                board_metrics = [m for m in metrics
                                 if board_token in m.board]
            if board_metrics:
                covs = [m.coverage for m in board_metrics]
                unks = [m.n_unknown for m in board_metrics]
                rts  = [m.total_time_s for m in board_metrics]
                print(f"    {board_token}:  "
                      f"cov_median={median(covs):.4f}  "
                      f"n_unk_median={median(unks):.0f}  "
                      f"rt_median={median(rts):.0f}s")

    return metrics


# ─── Comparison and verdict ───────────────────────────────────────────────────

def compute_summary(metrics: list[PipelineMetrics], board_tokens: list[str]) -> dict:
    """Compute per-board median stats from a list of PipelineMetrics."""
    result = {}
    for token in board_tokens:
        # Match board field which is like "250x156"
        bm = [m for m in metrics if m.board == token]
        if not bm:
            continue
        result[token] = {
            "coverage_median":   round(median(m.coverage for m in bm), 4),
            "n_unknown_median":  round(median(m.n_unknown for m in bm), 1),
            "rt_median":         round(median(m.total_time_s for m in bm), 1),
            "mae_median":        round(median(m.mean_abs_error for m in bm), 4),
            "n_runs":            len(bm),
        }
    return result


def verdict(
    all_results: dict[str, dict],  # condition_name -> summary dict
    target_board: str = "250x156",
    runtime_board: str = "250x250",
    iter10_coverage: float = 0.9916,   # 250x156 iter10 baseline (from iter13 plan)
    iter10_n_unknown: float = 285.0,   # 250x156 iter10 baseline
    iter10_rt_250: float = 180.0,      # 250x250 runtime gate
) -> dict:
    """
    For each condition, determine whether it recovered the target board regression.
    Returns a dict with findings and a recommended next action.
    """
    baseline = all_results.get("C0", {}).get(target_board)
    findings = {}

    for cond_name, summary in all_results.items():
        board_stats = summary.get(target_board, {})
        if not board_stats:
            findings[cond_name] = {"recovered": None, "note": "no data for target board"}
            continue

        cov  = board_stats.get("coverage_median", 0.0)
        unk  = board_stats.get("n_unknown_median", 9999)
        rt   = all_results.get(cond_name, {}).get(runtime_board, {}).get("rt_median", 0.0)

        # "Recovered" means: matches or beats iter10 baseline on BOTH metrics
        # (this is the exact Gate 5 from the analysis)
        cov_recovered = cov >= iter10_coverage - 1e-4
        unk_recovered = unk <= iter10_n_unknown + 1.0
        rt_ok         = rt < iter10_rt_250 if rt > 0 else None

        findings[cond_name] = {
            f"{target_board}_coverage":       cov,
            f"{target_board}_n_unknown":      unk,
            f"{runtime_board}_runtime_s":     rt,
            "coverage_recovered":             cov_recovered,
            "n_unknown_recovered":            unk_recovered,
            "runtime_gate_ok":                rt_ok,
            "gate5_pass":                     cov_recovered and unk_recovered,
        }

    # Identify which single condition recovers the regression
    single_recoveries = [
        name for name in ["C1", "C2", "C3"]
        if findings.get(name, {}).get("gate5_pass") is True
    ]
    combo_recoveries = [
        name for name in ["C4", "C5", "C6"]
        if findings.get(name, {}).get("gate5_pass") is True
    ]
    baseline_regressed = not findings.get("C0", {}).get("gate5_pass", True)

    if not baseline_regressed:
        root_cause = "INCONCLUSIVE: C0 (baseline) did not reproduce the regression. " \
                     "Seeds or board configs may differ from iter12 run."
        recommendation = "Re-run with the same seeds used in the original iter12 benchmark."
    elif single_recoveries:
        # Single change is the root cause
        root_cause_map = {
            "C1": "Inter-repair SA consumes enough budget to starve Phase2",
            "C2": "Pattern-breaker consumes enough budget to starve Phase2",
            "C3": "Phase2 caps were over-tightened in iter12 (delta_shortlist/beam_width/fullsolve_cap)",
        }
        root_cause = " AND ".join(root_cause_map[n] for n in single_recoveries)
        recommendation = (
            f"Root cause isolated to: {', '.join(single_recoveries)}. "
            f"Apply only the corresponding revert(s) as iter13's single change. "
            f"Verify no regression on 200x125 and 250x250 with that revert alone."
        )
    elif combo_recoveries and not single_recoveries:
        root_cause = (
            f"Interaction effect: no single change recovers the regression, "
            f"but combinations {combo_recoveries} do. "
            f"Likely: iter12's tighter Phase2 caps AND budget consumption by new stages compound."
        )
        recommendation = (
            "Apply C6 (all reverted) as the iter13 change. This is still one logical fix: "
            "'restore iter12 experimental tightenings to pre-iter12 values.' "
            "Then separate iterations can re-tighten one parameter at a time with measurement."
        )
    else:
        root_cause = "UNRESOLVED: no tested condition recovers the 250x156 regression."
        recommendation = (
            "The regression has a root cause not covered by these conditions. "
            "Candidates: (1) solver subset_cap truncation during repair, "
            "(2) global repair budget allocation (p1 starving p2), "
            "(3) a data/seed difference between this run and the original iter12 run. "
            "Next step: audit Phase1 elapsed_s and Phase2 elapsed_s in baseline C0 "
            "to check if Phase2 is receiving its expected budget."
        )

    return {
        "baseline_regressed": baseline_regressed,
        "single_recoveries":  single_recoveries,
        "combo_recoveries":   combo_recoveries,
        "root_cause":         root_cause,
        "recommendation":     recommendation,
        "findings":           findings,
    }


def print_comparison_table(
    all_results: dict[str, dict],
    conditions: list[Condition],
    board_tokens: list[str],
) -> None:
    print("\n" + "=" * 78)
    print("DIAGNOSTIC COMPARISON TABLE")
    print("=" * 78)

    # Print per-board tables
    for token in board_tokens:
        print(f"\n  Board: {token}")
        print(f"  {'Condition':<18} {'label':<15} {'cov_median':<12} "
              f"{'n_unk_median':<14} {'rt_median':<12} {'n_runs'}")
        print("  " + "-" * 74)

        for cond in conditions:
            stats = all_results.get(cond.name, {}).get(token, {})
            if not stats:
                print(f"  {cond.name:<18} {cond.label:<15} {'—':12} {'—':14} {'—':12}")
                continue
            cov = stats.get("coverage_median", 0.0)
            unk = stats.get("n_unknown_median", 0.0)
            rt  = stats.get("rt_median", 0.0)
            n   = stats.get("n_runs", 0)
            # Flag if this condition looks like a recovery on the problem board
            flag = ""
            if token == "250x156" and cond.name != "C0":
                if cov >= 0.9916 - 1e-4 and unk <= 286:
                    flag = " ← RECOVERED"
            print(f"  {cond.name:<18} {cond.label:<15} {cov:<12.4f} "
                  f"{unk:<14.0f} {rt:<12.0f} {n}{flag}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Iter13 regression isolation diagnostic."
    )
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "results" / "iter13_diagnostic"),
        help="Output directory for diagnostic results.",
    )
    parser.add_argument(
        "--img",
        default=str(REPO_ROOT / "assets" / "input_source_image-left.png"),
        help="Input source image.",
    )
    parser.add_argument(
        "--boards",
        nargs="+",
        default=["250x156"],
        help="Board tokens to run. Default: 250x156 only (the regressed board). "
             "Run '200x125 250x156 250x250' for full validation of winning condition.",
    )
    parser.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=[300, 301, 302],
        help="Seeds. Default: 300 301 302 (same as iter12 benchmark).",
    )
    parser.add_argument(
        "--conditions",
        nargs="+",
        default=[c.name for c in CONDITIONS],
        choices=[c.name for c in CONDITIONS],
        help="Which conditions to run. Default: all (C0 through C6). "
             "Use 'C0 C3' to quickly test baseline vs Phase2-caps-revert first.",
    )
    parser.add_argument(
        "--solver-mode",
        choices=("legacy", "fast"),
        default="fast",
    )
    strict_group = parser.add_mutually_exclusive_group()
    strict_group.add_argument("--strict-repro", dest="strict_repro", action="store_true")
    strict_group.add_argument("--no-strict-repro", dest="strict_repro", action="store_false")
    parser.set_defaults(strict_repro=True)
    parser.add_argument(
        "--deterministic-order",
        choices=("auto", "on", "off"),
        default="on",
    )
    parser.add_argument("--verbose", action="store_true", default=True)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    args = parse_args(raw_argv)

    img     = Path(args.img).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()

    # Strict-repro relaunch
    reexec = maybe_reexec_with_strict_repro(
        strict_repro=bool(args.strict_repro),
        script_path=SCRIPT_PATH,
        argv=raw_argv,
        python_executable=Path(sys.executable),
    )
    if reexec is not None:
        return int(reexec)
    try:
        enforce_strict_repro_or_raise(
            strict_repro=bool(args.strict_repro),
            script_path=SCRIPT_PATH,
            argv=raw_argv,
            python_executable=Path(sys.executable),
        )
    except ConfigError as exc:
        print(f"ERROR: {exc}")
        return 3

    try:
        check_required_modules_or_raise()
        validate_image_path(img)
        configure_mplconfigdir()
        ensure_output_dir(out_dir)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 2

    conditions_to_run = [CONDITION_MAP[n] for n in args.conditions]

    runtime = RuntimeConfig(
        paths=PathsConfig(
            repo_root=REPO_ROOT,
            img=img,
            out_dir=out_dir,
        ),
        verbose=bool(args.verbose),
        solver_mode=args.solver_mode,
        strict_repro=bool(args.strict_repro),
        deterministic_order=args.deterministic_order,
        board_jobs=1,
        repair_eval_jobs=1,
    )

    print("=" * 68)
    print("ITER13 REGRESSION ISOLATION DIAGNOSTIC")
    print("=" * 68)
    print(f"\n  Purpose:    Identify which iter12 change caused 250x156 regression")
    print(f"  Boards:     {args.boards}")
    print(f"  Seeds:      {args.seeds}")
    print(f"  Conditions: {[c.name for c in conditions_to_run]}")
    print(f"  Output:     {out_dir}")
    print(f"\n  Iter10 baseline (Gate 5 target for 250x156):")
    print(f"    coverage  >= 0.9916")
    print(f"    n_unknown <= 285")
    print(f"\n  Iter12 regression (what we are trying to recover):")
    print(f"    coverage  = 0.9898  (was 0.9916 at iter10)")
    print(f"    n_unknown = 342     (was 285 at iter10)")

    # ── Run each condition ────────────────────────────────────────────────────
    t_total = time.perf_counter()
    all_results: dict[str, dict] = {}   # cond_name -> {board_token -> stats}
    all_metrics: dict[str, list[PipelineMetrics]] = {}

    for cond in conditions_to_run:
        metrics = run_condition(
            cond,
            args.boards,
            args.seeds,
            runtime,
            verbose=bool(args.verbose),
        )
        all_metrics[cond.name] = metrics
        all_results[cond.name] = compute_summary(metrics, args.boards)

    total_elapsed = time.perf_counter() - t_total

    # ── Print comparison table ────────────────────────────────────────────────
    print_comparison_table(all_results, conditions_to_run, args.boards)

    # ── Compute verdict ───────────────────────────────────────────────────────
    v = verdict(all_results)

    print("\n" + "=" * 68)
    print("VERDICT")
    print("=" * 68)
    print(f"\n  Baseline regressed:   {v['baseline_regressed']}")
    print(f"  Single recoveries:    {v['single_recoveries'] or 'none'}")
    print(f"  Combo recoveries:     {v['combo_recoveries'] or 'none'}")
    print(f"\n  Root cause:  {v['root_cause']}")
    print(f"\n  Recommended next action:")
    print(f"  {v['recommendation']}")
    print(f"\n  Total diagnostic time: {total_elapsed:.0f}s")

    # ── Save outputs ──────────────────────────────────────────────────────────
    # JSON: full results
    json_path = out_dir / "diagnostic_summary.json"
    payload = {
        "conditions_run": args.conditions,
        "boards": args.boards,
        "seeds": args.seeds,
        "results": all_results,
        "verdict": {
            "baseline_regressed": v["baseline_regressed"],
            "single_recoveries":  v["single_recoveries"],
            "combo_recoveries":   v["combo_recoveries"],
            "root_cause":         v["root_cause"],
            "recommendation":     v["recommendation"],
        },
        "condition_descriptions": {
            c.name: {"label": c.label, "description": c.description,
                     "overrides": {k: str(val) for k, val in c.overrides.items()}}
            for c in CONDITIONS
        },
        "elapsed_s": round(total_elapsed, 1),
        "iter10_baseline_250x156": {
            "coverage_median": 0.9916,
            "n_unknown_median": 285.0,
            "source": "iter13_plan.md section 3.2",
        },
        "iter12_regression_250x156": {
            "coverage_median": 0.9898,
            "n_unknown_median": 342.0,
            "source": "iter13_plan.md section 3.2",
        },
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n  Results saved: {json_path}")

    # CSV: flat table for spreadsheet inspection
    csv_path = out_dir / "diagnostic_comparison.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "condition", "label", "board",
            "coverage_median", "n_unknown_median", "rt_median", "mae_median",
            "n_runs",
            "gate5_pass",   # 250x156 non-regression
            "overrides",
        ])
        for cond in conditions_to_run:
            for token in args.boards:
                stats = all_results.get(cond.name, {}).get(token, {})
                gate5 = v["findings"].get(cond.name, {}).get("gate5_pass", "")
                writer.writerow([
                    cond.name,
                    cond.label,
                    token,
                    stats.get("coverage_median", ""),
                    stats.get("n_unknown_median", ""),
                    stats.get("rt_median", ""),
                    stats.get("mae_median", ""),
                    stats.get("n_runs", ""),
                    gate5,
                    str(cond.overrides),
                ])
    print(f"  CSV saved:     {csv_path}")

    # Verdict text
    verdict_path = out_dir / "diagnostic_verdict.txt"
    verdict_path.write_text(
        f"ITER13 REGRESSION DIAGNOSTIC VERDICT\n"
        f"=====================================\n\n"
        f"Baseline regressed: {v['baseline_regressed']}\n"
        f"Single recoveries:  {v['single_recoveries']}\n"
        f"Combo recoveries:   {v['combo_recoveries']}\n\n"
        f"Root cause:\n  {v['root_cause']}\n\n"
        f"Recommendation:\n  {v['recommendation']}\n\n"
        f"Conditions run: {args.conditions}\n"
        f"Boards: {args.boards}\n"
        f"Seeds: {args.seeds}\n"
        f"Total time: {total_elapsed:.0f}s\n",
        encoding="utf-8",
    )
    print(f"  Verdict saved: {verdict_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

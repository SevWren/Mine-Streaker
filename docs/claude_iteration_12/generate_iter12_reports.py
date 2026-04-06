from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _run_git(repo_root: Path, *args: str) -> str:
    cmd = ["git", "-C", str(repo_root), *args]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
    except subprocess.CalledProcessError:
        return ""
    return out.strip()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _mode_payload(summary: dict, preferred: str = "fast") -> tuple[str, dict]:
    by_mode = summary.get("summary_by_mode", {})
    if preferred in by_mode:
        return preferred, by_mode[preferred]
    if by_mode:
        mode = sorted(by_mode.keys())[0]
        return mode, by_mode[mode]
    return "", {}


def _median(board_payload: dict, metric: str) -> float | None:
    stats = board_payload.get(metric, {})
    if "median" not in stats:
        return None
    return float(stats["median"])


@dataclass(frozen=True)
class Delta:
    baseline: float
    current: float
    delta: float
    status: str


def _delta(baseline: float, current: float, lower_is_better: bool) -> Delta:
    diff = float(current) - float(baseline)
    eps = 1e-9
    if abs(diff) <= eps:
        status = "Unchanged"
    elif lower_is_better:
        status = "Improved" if diff < 0 else "Worse"
    else:
        status = "Improved" if diff > 0 else "Worse"
    return Delta(baseline=float(baseline), current=float(current), delta=diff, status=status)


def _safe_float(v: float | None) -> float:
    return float(v) if v is not None else float("nan")


def _fmt(v: float, digits: int = 4) -> str:
    if v != v:  # NaN check
        return "n/a"
    return f"{v:.{digits}f}"


def _status_from_250(metrics_250: dict[str, Delta], key: str) -> str:
    d = metrics_250.get(key)
    if d is None:
        return "unclear"
    if d.status == "Improved":
        return "helped"
    if d.status == "Worse":
        return "hurt"
    return "neutral"


def _direction_from_statuses(statuses: list[str]) -> str:
    has_help = any(s == "helped" for s in statuses)
    has_hurt = any(s == "hurt" for s in statuses)
    if has_help and has_hurt:
        return "unclear"
    if has_help:
        return "helped"
    if has_hurt:
        return "hurt"
    return "neutral"


def _board_interpretation(board: str, cov: Delta, unk: Delta, mae: Delta, runtime: Delta) -> str:
    return (
        f"{board}: coverage {cov.baseline:.4f}->{cov.current:.4f} ({cov.status}), "
        f"n_unknown {unk.baseline:.1f}->{unk.current:.1f} ({unk.status}), "
        f"mean_abs_error {mae.baseline:.4f}->{mae.current:.4f} ({mae.status}), "
        f"runtime {runtime.baseline:.1f}s->{runtime.current:.1f}s ({runtime.status}). "
        "Practical impact: this board moved "
        f"{'closer' if (cov.status != 'Worse' and unk.status != 'Worse') else 'away'} "
        "from the fully solvable target."
    )


def _gate_verdict(
    base_summary: dict[str, dict],
    cur_summary: dict[str, dict],
) -> dict[str, tuple[bool, str]]:
    def med(summary: dict[str, dict], board: str, metric: str) -> float:
        return float(summary[board][metric]["median"])

    checks: dict[str, tuple[bool, str]] = {}

    b_cov_200 = med(base_summary, "200x125", "coverage")
    c_cov_200 = med(cur_summary, "200x125", "coverage")
    pass_cov_200 = c_cov_200 >= b_cov_200 - 1e-9
    checks["coverage_non_regression_200x125"] = (
        pass_cov_200,
        f"{b_cov_200:.4f} -> {c_cov_200:.4f}",
    )

    b_cov_250 = med(base_summary, "250x250", "coverage")
    c_cov_250 = med(cur_summary, "250x250", "coverage")
    pass_cov_250 = c_cov_250 >= b_cov_250 - 1e-9
    checks["coverage_non_regression_250x250"] = (
        pass_cov_250,
        f"{b_cov_250:.4f} -> {c_cov_250:.4f}",
    )

    b_unk_200 = med(base_summary, "200x125", "n_unknown")
    c_unk_200 = med(cur_summary, "200x125", "n_unknown")
    pass_unk_200 = c_unk_200 <= b_unk_200 + 1e-9
    checks["n_unknown_non_increasing_200x125"] = (
        pass_unk_200,
        f"{b_unk_200:.1f} -> {c_unk_200:.1f}",
    )

    b_unk_250 = med(base_summary, "250x250", "n_unknown")
    c_unk_250 = med(cur_summary, "250x250", "n_unknown")
    pass_unk_250 = c_unk_250 <= b_unk_250 + 1e-9
    checks["n_unknown_non_increasing_250x250"] = (
        pass_unk_250,
        f"{b_unk_250:.1f} -> {c_unk_250:.1f}",
    )

    b_mae_250 = med(base_summary, "250x250", "mean_abs_error")
    c_mae_250 = med(cur_summary, "250x250", "mean_abs_error")
    pass_mae_250 = c_mae_250 <= b_mae_250 + 1e-9
    checks["mae_non_increasing_250x250"] = (
        pass_mae_250,
        f"{b_mae_250:.4f} -> {c_mae_250:.4f}",
    )

    c_runtime_250 = med(cur_summary, "250x250", "total_time_s")
    pass_rt_250 = c_runtime_250 < 180.0
    checks["runtime_target_250x250_lt_180s"] = (
        pass_rt_250,
        f"{c_runtime_250:.1f}s (<180s target)",
    )
    return checks


def _git_changed_py_files(repo_root: Path, baseline_commit: str | None) -> list[str]:
    if baseline_commit and baseline_commit not in ("", "MANUAL_REQUIRED"):
        out = _run_git(
            repo_root,
            "diff",
            "--name-only",
            f"{baseline_commit}..HEAD",
            "--",
            "src/minesweeper_recon/*.py",
        )
        if out:
            return [line.strip() for line in out.splitlines() if line.strip()]
    out = _run_git(repo_root, "status", "--porcelain", "--", "src/minesweeper_recon/*.py")
    files: list[str] = []
    for line in out.splitlines():
        if not line:
            continue
        path = line[3:].strip().replace("\\", "/")
        if path.startswith("rc/"):
            path = "s" + path
        if path and path.endswith(".py"):
            files.append(path)
    return sorted(set(files))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Iter12 scorecard and what-changed markdown reports.")
    parser.add_argument(
        "--baseline-summary",
        default="D:/Github/Minesweeper-Draft/results/iter10/iter10_win10_ab/summary_ab.json",
        help="Baseline summary_ab.json path (Iter10 primary baseline).",
    )
    parser.add_argument(
        "--iter12-summary",
        default="D:/Github/Minesweeper-Draft/results/iter12/iter12_win12_ab/summary_ab.json",
        help="Iter12 summary_ab.json path.",
    )
    parser.add_argument(
        "--out-dir",
        default="D:/Github/Minesweeper-Draft/results/iter12",
        help="Directory for iter12_scorecard.md and iter12_what_changed.md.",
    )
    parser.add_argument(
        "--baseline-commit",
        default="",
        help="Git commit hash for Iter10 baseline. Leave empty if unknown.",
    )
    args = parser.parse_args(argv)

    baseline_path = Path(args.baseline_summary).resolve()
    iter12_path = Path(args.iter12_summary).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline_payload = _load_json(baseline_path)
    iter12_payload = _load_json(iter12_path)

    _, base_mode_summary = _mode_payload(baseline_payload, preferred="fast")
    iter12_mode, cur_mode_summary = _mode_payload(iter12_payload, preferred="fast")
    if not base_mode_summary or not cur_mode_summary:
        raise RuntimeError("Missing summary_by_mode content needed for report generation.")

    boards = ["200x125", "250x156", "250x250"]
    per_board: dict[str, dict[str, Delta]] = {}
    for board in boards:
        b = base_mode_summary.get(board, {})
        c = cur_mode_summary.get(board, {})
        if not b or not c:
            continue
        per_board[board] = {
            "coverage": _delta(_safe_float(_median(b, "coverage")), _safe_float(_median(c, "coverage")), lower_is_better=False),
            "n_unknown": _delta(_safe_float(_median(b, "n_unknown")), _safe_float(_median(c, "n_unknown")), lower_is_better=True),
            "mean_abs_error": _delta(
                _safe_float(_median(b, "mean_abs_error")),
                _safe_float(_median(c, "mean_abs_error")),
                lower_is_better=True,
            ),
            "total_time_s": _delta(
                _safe_float(_median(b, "total_time_s")),
                _safe_float(_median(c, "total_time_s")),
                lower_is_better=True,
            ),
        }

    board_250 = per_board.get("250x250", {})
    cov250 = board_250.get("coverage")
    unk250 = board_250.get("n_unknown")
    rt250 = board_250.get("total_time_s")

    cov_gap_base = 1.0 - float(cov250.baseline if cov250 else float("nan"))
    cov_gap_cur = 1.0 - float(cov250.current if cov250 else float("nan"))
    cov_gap_delta = cov_gap_cur - cov_gap_base
    cov_gap_status = "Improved" if cov_gap_delta < -1e-9 else ("Worse" if cov_gap_delta > 1e-9 else "Unchanged")

    unk_gap_base = float(unk250.baseline if unk250 else float("nan"))
    unk_gap_cur = float(unk250.current if unk250 else float("nan"))
    unk_gap_delta = unk_gap_cur - unk_gap_base
    unk_gap_status = "Improved" if unk_gap_delta < -1e-9 else ("Worse" if unk_gap_delta > 1e-9 else "Unchanged")

    rt_gap_base = float((rt250.baseline - 180.0) if rt250 else float("nan"))
    rt_gap_cur = float((rt250.current - 180.0) if rt250 else float("nan"))
    rt_gap_delta = rt_gap_cur - rt_gap_base
    rt_gap_status = "Improved" if rt_gap_delta < -1e-9 else ("Worse" if rt_gap_delta > 1e-9 else "Unchanged")

    gate_checks = _gate_verdict(base_mode_summary, cur_mode_summary)
    overall_pass = all(v[0] for v in gate_checks.values())

    metrics_rows = iter12_payload.get("metrics_by_mode", {}).get(iter12_mode, [])
    run_count = max(1, len(metrics_rows))
    inter_accept = sum(1 for r in metrics_rows if bool(r.get("inter_repair_sa_accepted", False)))
    pattern_apply = sum(1 for r in metrics_rows if bool(r.get("pattern_breaker_applied", False)))

    baseline_commit = args.baseline_commit.strip() or "MANUAL_REQUIRED"
    repo_root = Path("D:/Github/Minesweeper-Draft").resolve()
    iter12_commit = _run_git(repo_root, "rev-parse", "HEAD")
    changed_py = _git_changed_py_files(repo_root, args.baseline_commit.strip())

    status_cov = _status_from_250(board_250, "coverage")
    status_unk = _status_from_250(board_250, "n_unknown")
    status_mae = _status_from_250(board_250, "mean_abs_error")
    status_rt = _status_from_250(board_250, "total_time_s")

    file_templates: dict[str, tuple[str, str, list[str]]] = {
        "src/minesweeper_recon/pipeline.py": (
            "Added ROI-focused inter-repair SA flow and deterministic pattern-breaker stage before Phase2.",
            "Focus optimization on unresolved clusters and break symmetric unknown pockets before expensive swap search.",
            ["coverage", "n_unknown", "mean_abs_error"],
        ),
        "src/minesweeper_recon/repair_phase2.py": (
            "Replaced broad greedy swap evaluation with hotspot-pruned candidate generation, heuristic delta ranking, and bounded beam finalists.",
            "Cut full-board solve volume and target edits in high-value unknown regions to improve runtime and solvability.",
            ["runtime", "n_unknown", "coverage"],
        ),
        "src/minesweeper_recon/config.py": (
            "Added Iter12 knobs for ROI SA, pattern breaker, hotspot pruning, delta shortlist, and beam caps.",
            "Make new behavior reproducible and tunable without code edits.",
            ["runtime", "n_unknown"],
        ),
        "src/minesweeper_recon/models.py": (
            "Extended context and metrics telemetry for pattern-breaker and Phase2 hotspot/beam stages.",
            "Expose stage-level attribution in per-run outputs and summaries.",
            ["runtime", "n_unknown", "coverage"],
        ),
        "src/minesweeper_recon/benchmark_cli.py": (
            "Updated Iter12 benchmark labeling/default output root and preserved additive summary export.",
            "Keep benchmark artifacts isolated under iter12 and report new telemetry consistently.",
            ["runtime"],
        ),
        "src/minesweeper_recon/preflight.py": (
            "Updated Iter12 CLI messaging/default output text.",
            "Clarify iteration identity in execution output.",
            ["runtime"],
        ),
    }

    source_lines = []
    for rel in changed_py:
        rel_norm = rel.replace("\\", "/")
        desc, why, metrics = file_templates.get(
            rel_norm,
            (
                "Iteration 12 implementation adjustments.",
                "Support hotspot-focused repair and reporting changes.",
                ["coverage", "n_unknown", "runtime", "mean_abs_error"],
            ),
        )
        metric_statuses = []
        for metric in metrics:
            if metric == "coverage":
                metric_statuses.append(status_cov)
            elif metric == "n_unknown":
                metric_statuses.append(status_unk)
            elif metric == "mean_abs_error":
                metric_statuses.append(status_mae)
            elif metric == "runtime":
                metric_statuses.append(status_rt)
        observed = _direction_from_statuses(metric_statuses)
        source_lines.append(
            f"- `{rel_norm}`: {desc}\n"
            f"  Why: {why}\n"
            f"  Expected metric impact: {', '.join(metrics)}\n"
            f"  Observed direction: {observed}"
        )

    scorecard_lines = [
        "# Iteration 12 Scorecard",
        "",
        f"- Baseline summary: `{baseline_path}`",
        f"- Iter12 summary: `{iter12_path}`",
        f"- Compare mode: `{iter12_mode}`",
        "",
        "## Goal-Gap Scoreboard (250x250 median)",
        "",
        "| Gap | Iter10 baseline | Iter12 | Delta | Status |",
        "|---|---:|---:|---:|---|",
        f"| Coverage gap to 1.0 | {_fmt(cov_gap_base)} | {_fmt(cov_gap_cur)} | {_fmt(cov_gap_delta)} | {cov_gap_status} |",
        f"| Unknown gap to 0 | {_fmt(unk_gap_base, 1)} | {_fmt(unk_gap_cur, 1)} | {_fmt(unk_gap_delta, 1)} | {unk_gap_status} |",
        f"| Runtime gap to 180s | {_fmt(rt_gap_base, 1)}s | {_fmt(rt_gap_cur, 1)}s | {_fmt(rt_gap_delta, 1)}s | {rt_gap_status} |",
        "",
        "## Acceptance Gates",
        "",
    ]
    for gate, (ok, detail) in gate_checks.items():
        scorecard_lines.append(f"- `{gate}`: `{'PASS' if ok else 'FAIL'}` ({detail})")
    scorecard_lines.append("")
    scorecard_lines.append(f"- Overall gate status: `{'PASS' if overall_pass else 'FAIL'}`")
    scorecard_lines.append(f"- Inter-repair SA accepted rate: {inter_accept}/{run_count} ({100.0*inter_accept/run_count:.2f}%)")
    scorecard_lines.append(f"- Pattern-breaker applied rate: {pattern_apply}/{run_count} ({100.0*pattern_apply/run_count:.2f}%)")

    what_lines = [
        "# Iteration 12 What Changed",
        "",
        "## Executive Outcome (Plain English)",
        "",
        (
            "Iteration 12 changed the search strategy from broad candidate exploration to a hotspot-focused flow. "
            "The pipeline now tries a local warm-SA restart around unresolved unknown clusters, then runs a deterministic "
            "pattern-breaker pass before Phase2. Phase2 itself now ranks likely-good edits with a local heuristic and only "
            "spends full-board solves on a bounded beam shortlist. The practical question is whether this lowered unknown pockets "
            "and runtime without reducing coverage on key boards."
        ),
        "",
        "## Goal-Gap Scoreboard (toward 100% solvable target)",
        "",
        "| Gap | Iter10 baseline | Iter12 | Delta | Status |",
        "|---|---:|---:|---:|---|",
        f"| Coverage gap (`1.0 - coverage`) | {_fmt(cov_gap_base)} | {_fmt(cov_gap_cur)} | {_fmt(cov_gap_delta)} | {cov_gap_status} |",
        f"| Unknown gap (`n_unknown - 0`) | {_fmt(unk_gap_base, 1)} | {_fmt(unk_gap_cur, 1)} | {_fmt(unk_gap_delta, 1)} | {unk_gap_status} |",
        f"| Runtime gap (`runtime - 180s`) | {_fmt(rt_gap_base, 1)}s | {_fmt(rt_gap_cur, 1)}s | {_fmt(rt_gap_delta, 1)}s | {rt_gap_status} |",
        "",
        "## Board-Size Interpretation",
        "",
    ]

    for board in boards:
        payload = per_board.get(board)
        if payload is None:
            what_lines.append(f"- {board}: n/a (missing from one of the summaries)")
            continue
        what_lines.append(
            "- " + _board_interpretation(
                board,
                payload["coverage"],
                payload["n_unknown"],
                payload["mean_abs_error"],
                payload["total_time_s"],
            )
        )

    what_lines.extend(
        [
            "",
            "## Cause Mapping (Technique -> Effect)",
            "",
            "- ROI-only inter-repair SA: expected to lower local unknown clusters before Phase2; observed via inter-SA accept rate and unknown deltas (confidence: medium).",
            "- Deterministic pattern-breaker: expected to break symmetric unresolved pockets at low solve cost; observed via pattern-breaker apply rate and post-pass unknown change (confidence: medium).",
            "- Hotspot-pruned Phase2 + heuristic delta shortlist: expected to reduce full-solve pressure and runtime by evaluating fewer low-value candidates (confidence: high).",
            "- Beam finalists instead of greedy single-swap: expected to improve local escape behavior while bounding evaluation cost (confidence: medium).",
            "",
            "## Acceptance Gate Verdict",
            "",
        ]
    )
    for gate, (ok, detail) in gate_checks.items():
        what_lines.append(f"- `{gate}`: `{'PASS' if ok else 'FAIL'}` - {detail}")
    what_lines.append(f"- Overall: `{'PASS' if overall_pass else 'FAIL'}`")

    what_lines.extend(
        [
            "",
            "## Source Changes That Caused the Result",
            "",
            (
                f"Comparison baseline commit: `{baseline_commit}`; Iter12 commit: `{iter12_commit}`. "
                "If baseline commit is `MANUAL_REQUIRED`, finalize this report only after filling the exact baseline commit."
            ),
            "",
        ]
    )
    if source_lines:
        what_lines.extend(source_lines)
    else:
        what_lines.append("- No changed `src/minesweeper_recon/*.py` files detected from configured baseline.")

    scorecard_path = out_dir / "iter12_scorecard.md"
    what_changed_path = out_dir / "iter12_what_changed.md"
    scorecard_path.write_text("\n".join(scorecard_lines) + "\n", encoding="utf-8")
    what_changed_path.write_text("\n".join(what_lines) + "\n", encoding="utf-8")

    manifest_dir = iter12_path.parent
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "baseline_summary_path": str(baseline_path),
        "baseline_commit": baseline_commit,
        "iter12_commit": iter12_commit,
        "comparison_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (manifest_dir / "comparison_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

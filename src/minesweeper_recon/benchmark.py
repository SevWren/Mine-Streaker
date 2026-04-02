from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable

from .config import BoardConfig, RunConfig
from .models import PipelineMetrics
from .pipeline import run_experiment


BOARD_PRESETS: dict[str, tuple[int, int, float, int, float]] = {
    "200x125": (200, 125, 0.22, 3, 150.0),
    "250x156": (250, 156, 0.22, 3, 150.0),
    "250x250": (250, 250, 0.21, 3, 180.0),
}


@dataclass(frozen=True)
class MetricSummary:
    median: float
    min: float
    max: float
    n: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "median": self.median,
            "min": self.min,
            "max": self.max,
            "n": self.n,
        }


def _parse_board_token(token: str) -> tuple[int, int]:
    lhs, rhs = token.lower().split("x", 1)
    return int(lhs), int(rhs)


def build_standard_matrix(
    seeds: list[int] | None = None,
    board_tokens: list[str] | None = None,
) -> list[BoardConfig]:
    seeds = seeds or [300, 301, 302]
    board_tokens = board_tokens or ["200x125", "250x156", "250x250"]

    boards: list[BoardConfig] = []
    for token in board_tokens:
        if token in BOARD_PRESETS:
            w, h, density, border, repair2_budget_s = BOARD_PRESETS[token]
        else:
            w, h = _parse_board_token(token)
            density, border, repair2_budget_s = 0.21, 3, 150.0
        for seed in seeds:
            boards.append(
                BoardConfig(
                    width=w,
                    height=h,
                    label=f"{w}x{h}_seed{seed}",
                    density=density,
                    border=border,
                    seed=seed,
                    coarse_iters=1_500_000,
                    fine_iters=4_000_000,
                    refine_iters=5_000_000,
                    T_fine=2.5,
                    T_refine=1.5,
                    repair1_budget_s=None,
                    repair2_budget_s=repair2_budget_s,
                    repair3_max_unknown=25,
                )
            )
    return boards


def run_benchmark_matrix(config: RunConfig, boards: list[BoardConfig] | None = None) -> list[PipelineMetrics]:
    work_boards = boards or config.boards
    run_cfg = RunConfig(runtime=config.runtime, boards=work_boards)
    return run_experiment(run_cfg)


def summarize_metric(values: Iterable[float]) -> MetricSummary:
    vals = [float(v) for v in values]
    return MetricSummary(
        median=float(median(vals)),
        min=float(min(vals)),
        max=float(max(vals)),
        n=len(vals),
    )


def summarize_by_board(metrics: list[PipelineMetrics], keys: list[str]) -> dict[str, dict[str, dict[str, float | int]]]:
    grouped: dict[str, list[PipelineMetrics]] = {}
    for item in metrics:
        grouped.setdefault(item.board, []).append(item)

    out: dict[str, dict[str, dict[str, float | int]]] = {}
    for board, rows in grouped.items():
        out[board] = {}
        for key in keys:
            out[board][key] = summarize_metric([r.to_dict()[key] for r in rows]).to_dict()
    return out


def evaluate_acceptance_gates(
    fast_summary: dict[str, dict[str, dict[str, float | int]]],
    legacy_summary: dict[str, dict[str, dict[str, float | int]]],
) -> dict[str, object]:
    def med(summary: dict[str, dict[str, dict[str, float | int]]], board: str, key: str):
        board_payload = summary.get(board, {})
        metric_payload = board_payload.get(key, {})
        if "median" not in metric_payload:
            return None
        return float(metric_payload["median"])

    def check_ge(board: str, key: str):
        f = med(fast_summary, board, key)
        l = med(legacy_summary, board, key)
        if f is None or l is None:
            return None
        return f >= l

    def check_le(board: str, key: str):
        f = med(fast_summary, board, key)
        l = med(legacy_summary, board, key)
        if f is None or l is None:
            return None
        return f <= l

    def check_lt(board: str, key: str, limit: float):
        f = med(fast_summary, board, key)
        if f is None:
            return None
        return f < limit

    checks: dict[str, bool | None] = {
        "coverage_non_regression_200x125": check_ge("200x125", "coverage"),
        "coverage_non_regression_250x250": check_ge("250x250", "coverage"),
        "n_unknown_non_increasing_200x125": check_le("200x125", "n_unknown"),
        "n_unknown_non_increasing_250x250": check_le("250x250", "n_unknown"),
        "mae_non_increasing_250x250": check_le("250x250", "mean_abs_error"),
        "runtime_target_250x250_lt_180s": check_lt("250x250", "total_time_s", 180.0),
    }
    not_evaluated = [k for k, v in checks.items() if v is None]
    evaluated = [bool(v) for v in checks.values() if v is not None]
    overall = bool(evaluated) and (len(not_evaluated) == 0) and all(evaluated)
    failed = [k for k, v in checks.items() if v is False]
    return {
        "overall_pass": overall,
        "checks": checks,
        "failed_checks": failed,
        "not_evaluated_checks": not_evaluated,
    }

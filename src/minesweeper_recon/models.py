from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np


@dataclass
class SolveResult:
    solvable: bool
    revealed: set[tuple[int, int]]
    flagged: set[tuple[int, int]]
    unknown: set[tuple[int, int]]
    coverage: float
    mine_accuracy: float
    n_unknown: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SolveResult":
        return cls(
            solvable=bool(payload["solvable"]),
            revealed=set(payload["revealed"]),
            flagged=set(payload["flagged"]),
            unknown=set(payload["unknown"]),
            coverage=float(payload["coverage"]),
            mine_accuracy=float(payload["mine_accuracy"]),
            n_unknown=int(payload["n_unknown"]),
        )


@dataclass
class RepairResult:
    grid: np.ndarray
    solve_result: SolveResult
    reason: str
    telemetry: dict[str, Any] = field(default_factory=dict)


@dataclass
class RepairContext:
    grid: np.ndarray
    target: np.ndarray
    weights: np.ndarray
    forbidden: np.ndarray
    label: str
    time_budget_s: float
    deadline_s: float
    solve_fn: Callable[[np.ndarray, Optional[float]], SolveResult]
    output_dir: Optional[str] = None
    verbose: bool = True
    max_rounds: int = 0
    batch_size: int = 0
    search_radius: int = 0
    checkpoint_every: int = 0
    max_outer: int = 0
    max_unknown: int = 0
    initial_solve_result: Optional[SolveResult] = None


@dataclass
class PipelineMetrics:
    label: str
    board: str
    cells: int
    loss_per_cell: float
    mean_abs_error: float
    pct_within_1: float
    pct_within_2: float
    mine_density: float
    corridor_pct: float
    coverage: float
    solvable: bool
    mine_accuracy: float
    n_unknown: int
    repair1_reason: str
    repair2_reason: str
    repair3_reason: str
    total_time_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "board": self.board,
            "cells": self.cells,
            "loss_per_cell": self.loss_per_cell,
            "mean_abs_error": self.mean_abs_error,
            "pct_within_1": self.pct_within_1,
            "pct_within_2": self.pct_within_2,
            "mine_density": self.mine_density,
            "corridor_pct": self.corridor_pct,
            "coverage": self.coverage,
            "solvable": self.solvable,
            "mine_accuracy": self.mine_accuracy,
            "n_unknown": self.n_unknown,
            "repair1_reason": self.repair1_reason,
            "repair2_reason": self.repair2_reason,
            "repair3_reason": self.repair3_reason,
            "total_time_s": self.total_time_s,
        }

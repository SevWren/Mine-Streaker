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
    sort_calls: int = 0
    sort_items: int = 0
    sort_time_s: float = 0.0

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
            sort_calls=int(payload.get("sort_calls", 0)),
            sort_items=int(payload.get("sort_items", 0)),
            sort_time_s=float(payload.get("sort_time_s", 0.0)),
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
    frontier_radius: int = 3
    enable_low_yield_handoff: bool = False
    handoff_min_solves: int = 6
    handoff_window: int = 4
    handoff_min_rate: float = 0.75


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
    solver_mode: str = "fast"
    repair_global_cap_s: float = 0.0
    repair_phase1_elapsed_s: float = 0.0
    repair_phase2_elapsed_s: float = 0.0
    phase1_prefilter_total: int = 0
    phase1_prefilter_passed: int = 0
    phase1_prefilter_rejected: int = 0
    phase1_full_evals: int = 0
    phase1_full_eval_time_s: float = 0.0
    phase2_prefilter_total: int = 0
    phase2_prefilter_passed: int = 0
    phase2_prefilter_rejected: int = 0
    phase2_full_evals: int = 0
    phase2_full_eval_time_s: float = 0.0
    allocator_version: str = ""
    phase1_alloc_s: float = 0.0
    phase2_alloc_s: float = 0.0
    phase1_starved: bool = False
    deterministic_order: str = "auto"
    deterministic_sort_calls_total: int = 0
    deterministic_sort_items_total: int = 0
    deterministic_sort_time_s_total: float = 0.0
    repair_phase1_telemetry: dict[str, Any] = field(default_factory=dict)
    repair_phase2_telemetry: dict[str, Any] = field(default_factory=dict)
    repro_fingerprint: str = ""

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
            "solver_mode": self.solver_mode,
            "repair_global_cap_s": self.repair_global_cap_s,
            "repair_phase1_elapsed_s": self.repair_phase1_elapsed_s,
            "repair_phase2_elapsed_s": self.repair_phase2_elapsed_s,
            "phase1_prefilter_total": self.phase1_prefilter_total,
            "phase1_prefilter_passed": self.phase1_prefilter_passed,
            "phase1_prefilter_rejected": self.phase1_prefilter_rejected,
            "phase1_full_evals": self.phase1_full_evals,
            "phase1_full_eval_time_s": self.phase1_full_eval_time_s,
            "phase2_prefilter_total": self.phase2_prefilter_total,
            "phase2_prefilter_passed": self.phase2_prefilter_passed,
            "phase2_prefilter_rejected": self.phase2_prefilter_rejected,
            "phase2_full_evals": self.phase2_full_evals,
            "phase2_full_eval_time_s": self.phase2_full_eval_time_s,
            "allocator_version": self.allocator_version,
            "phase1_alloc_s": self.phase1_alloc_s,
            "phase2_alloc_s": self.phase2_alloc_s,
            "phase1_starved": self.phase1_starved,
            "deterministic_order": self.deterministic_order,
            "deterministic_sort_calls_total": self.deterministic_sort_calls_total,
            "deterministic_sort_items_total": self.deterministic_sort_items_total,
            "deterministic_sort_time_s_total": self.deterministic_sort_time_s_total,
            "repair_phase1_telemetry": self.repair_phase1_telemetry,
            "repair_phase2_telemetry": self.repair_phase2_telemetry,
            "repro_fingerprint": self.repro_fingerprint,
        }

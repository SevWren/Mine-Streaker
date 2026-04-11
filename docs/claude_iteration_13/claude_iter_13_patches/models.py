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
    solver_mode: str = "fast"
    deterministic_solver: bool = False
    parallel_eval_jobs: int = 1
    parallel_eval_batch_size: int = 0
    failure_policy: str = "fail_fast"
    phase2_hotspot_top_k: int = 6
    phase2_hotspot_radius: int = 6
    phase2_delta_shortlist: int = 24
    phase2_beam_width: int = 6
    phase2_beam_depth: int = 2
    phase2_beam_branch: int = 8
    phase2_fullsolve_cap: int = 8
    phase2_stagnation_rounds: int = 8
    phase2_max_mines: int = 24


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
    inter_repair_sa_accepted: bool = False
    inter_repair_sa_n_unknown_in: int = 0
    inter_repair_sa_n_unknown_out: int = 0
    inter_repair_sa_coverage_in: float = 0.0
    inter_repair_sa_coverage_out: float = 0.0
    inter_repair_sa_skip_reason: str = ""
    inter_repair_sa_elapsed_s: float = 0.0
    pattern_breaker_applied: bool = False
    pattern_breaker_n_unknown_in: int = 0
    pattern_breaker_n_unknown_out: int = 0
    pattern_breaker_coverage_in: float = 0.0
    pattern_breaker_coverage_out: float = 0.0
    pattern_breaker_skip_reason: str = ""
    pattern_breaker_elapsed_s: float = 0.0
    phase2_hotspot_unknown_scanned: int = 0
    phase2_beam_candidates: int = 0
    phase2_heuristic_shortlist: int = 0
    phase2_finalist_solves: int = 0
    parallel_jobs: int = 1
    parallel_enabled: bool = False
    parallel_tasks_submitted: int = 0
    parallel_tasks_completed: int = 0
    parallel_tasks_cancelled: int = 0
    parallel_queue_wait_s: float = 0.0
    parallel_eval_wall_s: float = 0.0
    parallel_eval_cpu_s: float = 0.0
    parallel_effective_speedup_est: float = 0.0
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
            "inter_repair_sa_accepted": self.inter_repair_sa_accepted,
            "inter_repair_sa_n_unknown_in": self.inter_repair_sa_n_unknown_in,
            "inter_repair_sa_n_unknown_out": self.inter_repair_sa_n_unknown_out,
            "inter_repair_sa_coverage_in": self.inter_repair_sa_coverage_in,
            "inter_repair_sa_coverage_out": self.inter_repair_sa_coverage_out,
            "inter_repair_sa_skip_reason": self.inter_repair_sa_skip_reason,
            "inter_repair_sa_elapsed_s": self.inter_repair_sa_elapsed_s,
            "pattern_breaker_applied": self.pattern_breaker_applied,
            "pattern_breaker_n_unknown_in": self.pattern_breaker_n_unknown_in,
            "pattern_breaker_n_unknown_out": self.pattern_breaker_n_unknown_out,
            "pattern_breaker_coverage_in": self.pattern_breaker_coverage_in,
            "pattern_breaker_coverage_out": self.pattern_breaker_coverage_out,
            "pattern_breaker_skip_reason": self.pattern_breaker_skip_reason,
            "pattern_breaker_elapsed_s": self.pattern_breaker_elapsed_s,
            "phase2_hotspot_unknown_scanned": self.phase2_hotspot_unknown_scanned,
            "phase2_beam_candidates": self.phase2_beam_candidates,
            "phase2_heuristic_shortlist": self.phase2_heuristic_shortlist,
            "phase2_finalist_solves": self.phase2_finalist_solves,
            "parallel_jobs": self.parallel_jobs,
            "parallel_enabled": self.parallel_enabled,
            "parallel_tasks_submitted": self.parallel_tasks_submitted,
            "parallel_tasks_completed": self.parallel_tasks_completed,
            "parallel_tasks_cancelled": self.parallel_tasks_cancelled,
            "parallel_queue_wait_s": self.parallel_queue_wait_s,
            "parallel_eval_wall_s": self.parallel_eval_wall_s,
            "parallel_eval_cpu_s": self.parallel_eval_cpu_s,
            "parallel_effective_speedup_est": self.parallel_effective_speedup_est,
            "repro_fingerprint": self.repro_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PipelineMetrics":
        return cls(
            label=str(payload["label"]),
            board=str(payload["board"]),
            cells=int(payload["cells"]),
            loss_per_cell=float(payload["loss_per_cell"]),
            mean_abs_error=float(payload["mean_abs_error"]),
            pct_within_1=float(payload["pct_within_1"]),
            pct_within_2=float(payload["pct_within_2"]),
            mine_density=float(payload["mine_density"]),
            corridor_pct=float(payload["corridor_pct"]),
            coverage=float(payload["coverage"]),
            solvable=bool(payload["solvable"]),
            mine_accuracy=float(payload["mine_accuracy"]),
            n_unknown=int(payload["n_unknown"]),
            repair1_reason=str(payload["repair1_reason"]),
            repair2_reason=str(payload["repair2_reason"]),
            repair3_reason=str(payload["repair3_reason"]),
            total_time_s=float(payload["total_time_s"]),
            solver_mode=str(payload.get("solver_mode", "fast")),
            repair_global_cap_s=float(payload.get("repair_global_cap_s", 0.0)),
            repair_phase1_elapsed_s=float(payload.get("repair_phase1_elapsed_s", 0.0)),
            repair_phase2_elapsed_s=float(payload.get("repair_phase2_elapsed_s", 0.0)),
            phase1_prefilter_total=int(payload.get("phase1_prefilter_total", 0)),
            phase1_prefilter_passed=int(payload.get("phase1_prefilter_passed", 0)),
            phase1_prefilter_rejected=int(payload.get("phase1_prefilter_rejected", 0)),
            phase1_full_evals=int(payload.get("phase1_full_evals", 0)),
            phase1_full_eval_time_s=float(payload.get("phase1_full_eval_time_s", 0.0)),
            phase2_prefilter_total=int(payload.get("phase2_prefilter_total", 0)),
            phase2_prefilter_passed=int(payload.get("phase2_prefilter_passed", 0)),
            phase2_prefilter_rejected=int(payload.get("phase2_prefilter_rejected", 0)),
            phase2_full_evals=int(payload.get("phase2_full_evals", 0)),
            phase2_full_eval_time_s=float(payload.get("phase2_full_eval_time_s", 0.0)),
            allocator_version=str(payload.get("allocator_version", "")),
            phase1_alloc_s=float(payload.get("phase1_alloc_s", 0.0)),
            phase2_alloc_s=float(payload.get("phase2_alloc_s", 0.0)),
            phase1_starved=bool(payload.get("phase1_starved", False)),
            deterministic_order=str(payload.get("deterministic_order", "auto")),
            deterministic_sort_calls_total=int(payload.get("deterministic_sort_calls_total", 0)),
            deterministic_sort_items_total=int(payload.get("deterministic_sort_items_total", 0)),
            deterministic_sort_time_s_total=float(payload.get("deterministic_sort_time_s_total", 0.0)),
            repair_phase1_telemetry=dict(payload.get("repair_phase1_telemetry", {})),
            repair_phase2_telemetry=dict(payload.get("repair_phase2_telemetry", {})),
            inter_repair_sa_accepted=bool(payload.get("inter_repair_sa_accepted", False)),
            inter_repair_sa_n_unknown_in=int(payload.get("inter_repair_sa_n_unknown_in", 0)),
            inter_repair_sa_n_unknown_out=int(payload.get("inter_repair_sa_n_unknown_out", 0)),
            inter_repair_sa_coverage_in=float(payload.get("inter_repair_sa_coverage_in", 0.0)),
            inter_repair_sa_coverage_out=float(payload.get("inter_repair_sa_coverage_out", 0.0)),
            inter_repair_sa_skip_reason=str(payload.get("inter_repair_sa_skip_reason", "")),
            inter_repair_sa_elapsed_s=float(payload.get("inter_repair_sa_elapsed_s", 0.0)),
            pattern_breaker_applied=bool(payload.get("pattern_breaker_applied", False)),
            pattern_breaker_n_unknown_in=int(payload.get("pattern_breaker_n_unknown_in", 0)),
            pattern_breaker_n_unknown_out=int(payload.get("pattern_breaker_n_unknown_out", 0)),
            pattern_breaker_coverage_in=float(payload.get("pattern_breaker_coverage_in", 0.0)),
            pattern_breaker_coverage_out=float(payload.get("pattern_breaker_coverage_out", 0.0)),
            pattern_breaker_skip_reason=str(payload.get("pattern_breaker_skip_reason", "")),
            pattern_breaker_elapsed_s=float(payload.get("pattern_breaker_elapsed_s", 0.0)),
            phase2_hotspot_unknown_scanned=int(payload.get("phase2_hotspot_unknown_scanned", 0)),
            phase2_beam_candidates=int(payload.get("phase2_beam_candidates", 0)),
            phase2_heuristic_shortlist=int(payload.get("phase2_heuristic_shortlist", 0)),
            phase2_finalist_solves=int(payload.get("phase2_finalist_solves", 0)),
            parallel_jobs=int(payload.get("parallel_jobs", 1)),
            parallel_enabled=bool(payload.get("parallel_enabled", False)),
            parallel_tasks_submitted=int(payload.get("parallel_tasks_submitted", 0)),
            parallel_tasks_completed=int(payload.get("parallel_tasks_completed", 0)),
            parallel_tasks_cancelled=int(payload.get("parallel_tasks_cancelled", 0)),
            parallel_queue_wait_s=float(payload.get("parallel_queue_wait_s", 0.0)),
            parallel_eval_wall_s=float(payload.get("parallel_eval_wall_s", 0.0)),
            parallel_eval_cpu_s=float(payload.get("parallel_eval_cpu_s", 0.0)),
            parallel_effective_speedup_est=float(payload.get("parallel_effective_speedup_est", 0.0)),
            repro_fingerprint=str(payload.get("repro_fingerprint", "")),
        )
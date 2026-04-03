from __future__ import annotations

import multiprocessing as mp
import time
from concurrent.futures import ProcessPoolExecutor, TimeoutError, as_completed
from typing import Any

import numpy as np

from .models import SolveResult
from .runtime import BudgetExceeded
from .solver import solve_board

CandidateKey = tuple[tuple[int, int, int], ...]


def _apply_edits(base_grid: np.ndarray, edits: CandidateKey) -> np.ndarray:
    cand = base_grid.copy()
    for y, x, delta in edits:
        cand[int(y), int(x)] = 1 if int(delta) > 0 else 0
    return cand


def _worker_eval_candidate(
    base_grid: np.ndarray,
    edits: CandidateKey,
    solver_mode: str,
    deterministic: bool,
    time_budget_s: float | None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    candidate = _apply_edits(base_grid, edits)
    deadline_s = None
    if time_budget_s is not None:
        deadline_s = time.perf_counter() + max(0.0, float(time_budget_s))

    try:
        sr = solve_board(candidate, deadline_s=deadline_s, mode=solver_mode, deterministic=deterministic)
        return {
            "key": edits,
            "solve_result": sr,
            "elapsed_s": max(0.0, time.perf_counter() - t0),
            "error": "",
        }
    except Exception as exc:
        return {
            "key": edits,
            "solve_result": None,
            "elapsed_s": max(0.0, time.perf_counter() - t0),
            "error": f"{type(exc).__name__}: {exc}",
        }


class ParallelSolveEvaluator:
    def __init__(
        self,
        jobs: int,
        solver_mode: str,
        deterministic: bool,
        failure_policy: str = "fail_fast",
    ) -> None:
        self.jobs = max(1, int(jobs))
        self.solver_mode = solver_mode
        self.deterministic = bool(deterministic)
        self.failure_policy = failure_policy
        self._executor: ProcessPoolExecutor | None = None

    def _ensure_executor(self) -> ProcessPoolExecutor:
        if self._executor is None:
            ctx = mp.get_context("spawn")
            self._executor = ProcessPoolExecutor(max_workers=self.jobs, mp_context=ctx)
        return self._executor

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None

    def evaluate_batch(
        self,
        base_grid: np.ndarray,
        candidates: list[CandidateKey],
        deadline_s: float | None = None,
    ) -> tuple[dict[CandidateKey, SolveResult], dict[str, float | int]]:
        if not candidates:
            return {}, {
                "submitted": 0,
                "completed": 0,
                "cancelled": 0,
                "failed": 0,
                "wall_s": 0.0,
                "cpu_s": 0.0,
            }

        remaining_s = None
        if deadline_s is not None:
            remaining_s = max(0.0, float(deadline_s) - time.perf_counter())
            if remaining_s <= 0.0:
                raise BudgetExceeded("parallel evaluation deadline exceeded before submit")

        executor = self._ensure_executor()
        t_submit = time.perf_counter()
        futures = {
            executor.submit(
                _worker_eval_candidate,
                base_grid,
                edits,
                self.solver_mode,
                self.deterministic,
                remaining_s,
            ): edits
            for edits in candidates
        }
        results: dict[CandidateKey, SolveResult] = {}
        completed = 0
        cancelled = 0
        failed = 0
        cpu_s = 0.0
        try:
            for fut in as_completed(futures, timeout=remaining_s):
                payload = fut.result()
                completed += 1
                cpu_s += float(payload.get("elapsed_s", 0.0))
                key = payload["key"]
                sr = payload.get("solve_result")
                if sr is not None:
                    results[key] = sr
                else:
                    failed += 1
                    if self.failure_policy == "fail_fast":
                        raise RuntimeError(
                            f"parallel candidate evaluation failed for {key}: {payload.get('error', 'unknown error')}"
                        )
        except TimeoutError as exc:
            for fut in futures:
                if not fut.done():
                    fut.cancel()
                    cancelled += 1
            raise BudgetExceeded("parallel evaluation deadline exceeded") from exc
        finally:
            wall_s = max(0.0, time.perf_counter() - t_submit)

        return results, {
            "submitted": len(candidates),
            "completed": completed,
            "cancelled": cancelled,
            "failed": failed,
            "wall_s": round(wall_s, 6),
            "cpu_s": round(cpu_s, 6),
        }

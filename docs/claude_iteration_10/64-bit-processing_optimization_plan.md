# 64-Bit Processing Optimization Plan

Status: Planning document only.  
Scope of this file: define implementation strategy.  
Execution state: no optimization code changes started from this plan yet.

## 1) Executive Summary

The project already runs on 64-bit Python (`C:\Python314\python.exe`, 64-bit pointer width), so the current low CPU usage is not a 32-bit limitation. The primary bottleneck is serial orchestration and serial candidate evaluation in repair phases.

This plan introduces multicore execution in controlled phases:

1. Parallel benchmark task execution across `(mode, board, seed)` workers.
2. Optional board-level parallel execution for `iter10_win10.py`.
3. Parallel batch evaluation for repair candidates (Phase 1 and Phase 2).
4. Additional telemetry to prove speedup and preserve reproducibility controls.

The rollout is feature-flagged and backward-compatible (`jobs=1` equivalent to current behavior).

## 2) Forensic Baseline (Code-Verified)

## 2.1 Repro controls currently limiting per-process threading in strict mode

Strict repro enforces:

- `PYTHONHASHSEED=0`
- `OMP_NUM_THREADS=1`
- `MKL_NUM_THREADS=1`
- `OPENBLAS_NUM_THREADS=1`
- `NUMBA_NUM_THREADS=1`

Reference: `src/minesweeper_recon/preflight.py` (`STRICT_REPRO_ENV_VARS`, strict enforcement path).

## 2.2 Serial orchestration points

- Board loop is sequential in `run_experiment`: `src/minesweeper_recon/pipeline.py`.
- Benchmark modes are sequential in `src/minesweeper_recon/benchmark_cli.py`.
- `run_benchmark_matrix` delegates to serial `run_experiment`: `src/minesweeper_recon/benchmark.py`.

## 2.3 Serial repair hot paths

- Phase 1 candidate evaluation loop is sequential in `src/minesweeper_recon/repair_phase1.py`.
- Phase 2 swap/remove evaluation loops are sequential in `src/minesweeper_recon/repair_phase2.py`.

## 2.4 SA kernel characteristics

- Numba JIT is used (`@njit`), but the SA iteration loop remains sequential.
- Reference: `src/minesweeper_recon/sa.py`.

## 2.5 Existing telemetry indicates solve wait dominates

Observed telemetry from recent runs shows repair runtime heavily spent in `solve_wait` and `full_eval` time, supporting parallel solve-evaluation as highest ROI.

## 3) Goals, Non-Goals, and Constraints

## 3.1 Goals

1. Increase effective multicore CPU utilization during benchmark and repair-heavy workloads.
2. Reduce wall-clock runtime without changing core acceptance logic.
3. Preserve strict reproducibility behavior where configured.
4. Keep compatibility with existing CLI usage.

## 3.2 Non-goals (this pass)

1. No solver logic rewrite in C/C++.
2. No algorithmic objective change to coverage/unknown acceptance criteria.
3. No mandatory default behavior change for existing users.

## 3.3 Constraints

1. Windows 10 + Python spawn semantics (no fork assumptions).
2. Strict reproducibility remains supported.
3. Deadlines and repair budgets must remain hard-limited.
4. All new parallelism must be opt-in or default-safe with deterministic merge behavior.

## 4) Target Architecture (High Level)

## 4.1 Parallelism layers

1. Coarse-grain: benchmark task parallelism across `(mode, board, seed)`.
2. Mid-grain: optional board-level parallelism for `iter10_win10.py`.
3. Fine-grain: batch parallel solve evaluations inside repair phases.

## 4.2 Deterministic selection model

Parallel workers may finish out-of-order. Selection decisions will remain deterministic by:

1. Stable candidate keys.
2. Stable pre-sorted task submission order.
3. Stable tie-break order when merging worker results.

## 5) Workstream A: Benchmark Multicore Execution (Phase 1)

## 5.1 Deliverables

1. Add `--jobs` to benchmark CLI (default `1`).
2. Execute benchmark tasks via `ProcessPoolExecutor` with explicit `spawn`.
3. Preserve full runtime config propagation (`solver_mode`, strict flags, deterministic policy, caps).
4. Deterministic task ordering and deterministic result merge.
5. Progress logging per worker task and total queue progress.

## 5.2 Files to change

1. `src/minesweeper_recon/benchmark_cli.py`
2. `src/minesweeper_recon/benchmark.py`
3. `src/minesweeper_recon/config.py` (if runtime config extension required)
4. `src/minesweeper_recon/models.py` (if benchmark metadata extension required)

## 5.3 Implementation notes

1. Build task list in sorted order: `(mode, board_token, seed)`.
2. Worker entrypoint runs one board config + one mode and returns `PipelineMetrics`.
3. Output path isolation by mode/board/seed to avoid collisions.
4. On worker failure, capture structured error and fail fast with actionable message.
5. Keep `jobs=1` path as exact serial fallback.

## 6) Workstream B: Optional Board Parallelism for `iter10_win10.py` (Phase 2)

## 6.1 Deliverables

1. Add `--board-jobs` (default `1`).
2. Run default boards concurrently when `board_jobs > 1`.
3. Preserve summary format and output naming.

## 6.2 Files to change

1. `docs/claude_iteration_10/iter10_win10.py`
2. `src/minesweeper_recon/pipeline.py`
3. `src/minesweeper_recon/config.py` (runtime option if needed)

## 6.3 Implementation notes

1. Each board run is process-isolated.
2. Compile cost may repeat per worker; acceptable for first pass.
3. Keep serial code path unchanged for backward compatibility.

## 7) Workstream C: Parallel Candidate Evaluation in Repair (Phase 3)

## 7.1 Deliverables

1. Add worker-backed batch evaluation for Phase 1 gated candidates.
2. Add worker-backed batch evaluation for Phase 2 swap/remove candidates.
3. Maintain existing acceptance rules and handoff semantics.
4. Honor deadlines with hard timeouts and cancelation.

## 7.2 Files to change

1. `src/minesweeper_recon/repair_phase1.py`
2. `src/minesweeper_recon/repair_phase2.py`
3. `src/minesweeper_recon/pipeline.py` (worker-pool lifecycle and context wiring)
4. Potential new helper module: `src/minesweeper_recon/parallel_eval.py`

## 7.3 Implementation notes

1. Use persistent pool per board run, not per round.
2. Submit bounded candidate batches to control memory and queue pressure.
3. Return compact solve summaries to minimize IPC payload.
4. Keep parent-side canonical selection and state mutation to avoid race conditions.
5. Invalidate caches on board-state epoch change as currently done.

## 8) Reproducibility and Determinism Policy

## 8.1 Strict mode policy

1. Keep current strict-repro preflight behavior unchanged.
2. Permit `jobs > 1` while preserving deterministic merge order.
3. Require deterministic candidate ordering and deterministic final decision logic.

## 8.2 Non-strict mode policy

1. Maximize throughput.
2. Permit non-deterministic completion order.
3. Keep correctness guards and budget enforcement identical.

## 9) Telemetry Additions (Mandatory)

Add telemetry fields to measure actual speedup and diagnose overhead:

1. `parallel_jobs`
2. `parallel_enabled`
3. `parallel_tasks_submitted`
4. `parallel_tasks_completed`
5. `parallel_tasks_cancelled`
6. `parallel_queue_wait_s`
7. `parallel_eval_wall_s`
8. `parallel_eval_cpu_s` (if collectable)
9. `parallel_effective_speedup_est`

Repair-level telemetry extensions:

1. `batch_size_mean`
2. `batch_timeout_count`
3. `worker_failures`
4. `deadline_preemptions`

## 10) Validation and Test Strategy

## 10.1 Functional parity tests

1. `jobs=1` must match current behavior and output schema.
2. Strict mode reproducibility on same machine:
   - identical outputs for repeated runs with same mode/seed/config.
3. Acceptance metrics must not regress beyond current gate policy.

## 10.2 Performance tests

1. Benchmark matrix on `jobs=1,2,4` (and `8` if stable).
2. Report speedup curve and efficiency.
3. Validate CPU utilization improvement during benchmark workloads.

## 10.3 Deadline safety tests

1. Tiny cap tests must still respect global and phase deadlines.
2. Worker cancelation paths must not overrun wall-clock budgets.

## 11) Risk Register and Mitigations

1. Risk: IPC overhead dominates for small boards.
   - Mitigation: adaptive batching and `jobs` cap by workload size.
2. Risk: memory pressure with many workers.
   - Mitigation: bound in-flight tasks and enforce max jobs default.
3. Risk: reproducibility drift in strict mode.
   - Mitigation: deterministic task ordering + deterministic merge + reproducibility tests.
4. Risk: output collisions in concurrent runs.
   - Mitigation: task-unique output subpaths and atomic writes.
5. Risk: Windows spawn startup overhead.
   - Mitigation: persistent pool reuse, minimize worker boot frequency.

## 12) Rollout Plan

1. Phase 1 rollout behind `--jobs` defaulting to `1`.
2. Phase 2 rollout behind `--board-jobs` defaulting to `1`.
3. Phase 3 rollout behind repair eval jobs flag defaulting to `1`.
4. Maintain fast rollback path by setting jobs flags back to `1`.

## 13) Definition of Done

1. Benchmark pipeline supports multicore execution with deterministic merge.
2. Repair phases support optional parallel candidate evaluation.
3. Telemetry captures parallel overhead and observed speedup.
4. No regression in acceptance gates on required board matrix.
5. Strict reproducibility mode remains operational and validated.

## 14) Implementation Sequence (When Execution Starts)

1. Add benchmark `--jobs` and parallel task runner.
2. Add board-level parallel option for `iter10_win10.py`.
3. Add persistent worker pool for repair batch evaluations.
4. Add full telemetry surface and summary reporting.
5. Run parity, reproducibility, and performance validation matrix.
6. Publish gate report with speedup and regression status.

## 15) Forensic Gap Analysis Addendum (Missed Items)

This section documents gaps found during forensic review and adds concrete controls before implementation.

### [P1] Oversubscription risk in non-strict mode

Gap:

- The plan does not define a policy to prevent `jobs * library_threads` oversubscription in non-strict mode.

Risk:

- CPU thrash, reduced throughput, unstable latency, and higher timeout probability.

Required control:

1. Add runtime thread policy:
   - strict mode: keep current `*_NUM_THREADS=1`
   - non-strict mode: cap effective threads per process based on `jobs`
2. Add telemetry:
   - `effective_thread_cap_per_worker`
   - `oversubscription_guard_applied`

### [P1] Deterministic selection contract is underspecified for parallel repair eval

Gap:

- Plan states deterministic merge, but does not explicitly define selection precedence when candidates complete out-of-order.

Risk:

- Silent behavior drift (different accepted candidate) despite same seed/settings.

Required control:

1. Define canonical decision rule:
   - rank by precomputed candidate order first,
   - then apply existing acceptance criteria,
   - never choose by completion time.
2. Persist `candidate_rank` and `selection_source` in telemetry for audits.

### [P1] Hard deadline guarantees are not fully specified with process pools

Gap:

- Process cancellation behavior on Windows is not deterministic for already-running worker tasks.

Risk:

- Wall-clock budget overruns despite configured caps.

Required control:

1. Use cooperative deadline checks inside worker solve paths.
2. Enforce batch-level timeout with immediate parent cutover.
3. Mark late completions as discarded and exclude from selection.
4. Add telemetry:
   - `late_results_discarded`
   - `deadline_abort_batches`

### [P1] Candidate-eval IPC payload risk (full-board copy amplification)

Gap:

- Plan does not define payload minimization strategy for parallel candidate evaluation.

Risk:

- IPC overhead dominates and removes any speedup, especially with large boards.

Required control:

1. Pass compact edit descriptions (`edits`) plus immutable base snapshot/version id.
2. Reconstruct candidate board in worker from base + edits, or use shared-memory snapshot where practical.
3. Add telemetry:
   - `ipc_bytes_est`
   - `eval_compute_to_ipc_ratio`

### [P1] Windows spawn compatibility constraints not explicit enough

Gap:

- Plan does not explicitly require picklable top-level worker entrypoints and spawn-safe module boundaries.

Risk:

- Runtime failures only on Windows (`spawn`) even when Linux tests pass.

Required control:

1. Keep worker callables at top-level module scope.
2. Avoid closures/lambdas as worker targets.
3. Add CI/local test path that explicitly uses spawn context.

### [P2] Duplicate task tokens and output collision handling not fully defined

Gap:

- Plan mentions output isolation but does not specify duplicate `(mode, board, seed)` behavior.

Risk:

- Overwrites or non-deterministic summaries with repeated tokens.

Required control:

1. Validate unique task keys before submission.
2. On duplicates: fail fast with actionable error.
3. Record task key in every metrics payload.

### [P2] Worker crash containment and fallback policy missing

Gap:

- Fail-fast is mentioned, but no fallback policy is defined.

Risk:

- Single transient worker fault aborts long matrix runs unnecessarily.

Required control:

1. Add `--failure-policy {fail_fast,continue}` (default `fail_fast`).
2. In `continue`, mark task as failed in summary and continue remaining tasks.
3. Always preserve non-zero exit when any task fails unless explicitly overridden.

### [P2] JIT warmup duplication across workers not bounded

Gap:

- Each worker may pay compile/warmup overhead.

Risk:

- Parallel run may have poor scaling for short tasks.

Required control:

1. Add per-worker warmup timing telemetry.
2. Add adaptive job recommendation:
   - reduce jobs for short boards / low task count.

### [P2] Memory budgeting not formalized

Gap:

- Plan lacks an explicit memory-based jobs cap.

Risk:

- Memory pressure, paging, severe slowdown, or worker termination.

Required control:

1. Add conservative auto-cap:
   - `jobs <= min(cpu_count, task_count, memory_based_cap)`
2. Add telemetry:
   - `rss_peak_mb_parent`
   - `rss_peak_mb_worker_est`

### [P3] Observability of queue dynamics missing

Gap:

- Plan includes totals but not queue depth/in-flight visibility.

Risk:

- Hard to diagnose starvation and scheduler inefficiency.

Required control:

1. Add progress telemetry:
   - `inflight_max`
   - `queue_depth_peak`
   - `task_submit_to_start_ms_p50/p95`

## 16) Edge-Case Test Matrix (Mandatory Before Rollout)

1. `jobs=1` exact parity test (baseline lock).
2. `jobs=0`, negative jobs, non-integer jobs -> validation errors.
3. `jobs > task_count` -> no deadlock, correct completion.
4. Duplicate task keys -> deterministic fail-fast.
5. Tight global cap + high queue depth -> no wall-clock overrun.
6. Worker exception injection -> policy behavior verified (`fail_fast` vs `continue`).
7. KeyboardInterrupt during active pool -> clean shutdown, no orphan workers.
8. Strict repro with `jobs>1` repeated twice -> identical summary ordering and identical outputs.
9. Non-strict with high jobs -> oversubscription guard behavior visible in telemetry.
10. Very small boards -> parallel overhead does not regress > threshold; auto-cap recommendation triggers.

## 17) Regression-Minimization Controls (Change Management)

1. Stage gate 0 (instrumentation only):
   - Add telemetry with no behavior change.
2. Stage gate 1 (benchmark parallel only):
   - Guard behind `--jobs`, default `1`.
3. Stage gate 2 (board parallel):
   - Guard behind `--board-jobs`, default `1`.
4. Stage gate 3 (repair parallel):
   - Guard behind `--repair-eval-jobs`, default `1`.
5. At each gate:
   - run parity suite,
   - run reproducibility suite,
   - run performance suite,
   - require explicit pass before next gate.

Rollback rule:

- Any gate failure reverts to serial path by setting jobs flags to `1`; no mixed partial rollout.

## 18) Quantitative Acceptance Thresholds for This Optimization Program

1. Correctness:
   - No median regression in required acceptance metrics per AGENTS policy.
2. Reproducibility:
   - Strict mode repeated-run hash equality for outputs and summaries.
3. Runtime:
   - Benchmark wall-clock improvement at `jobs>=2` on matrix workloads.
4. Deadline integrity:
   - No phase/global budget overrun beyond jitter tolerance.
5. Stability:
   - Zero orphan worker processes after completion or interruption.

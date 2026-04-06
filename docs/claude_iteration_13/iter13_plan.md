# Iteration 13 Plan: Adaptive Phase2 Search Recovery Under Hard Runtime Gate

## 1. Document Control

- Document path: `D:/Github/Minesweeper-Draft/docs/claude_iteration_13/iter13_plan.md`
- Repository root: `D:/Github/Minesweeper-Draft`
- Iteration tag: `iter13`
- Draft date: 2026-04-05 (America/Chicago)
- Plan status: Proposed for implementation
- Source of truth for executable logic: `D:/Github/Minesweeper-Draft/src/minesweeper_recon`
- Wrapper/docs location only: `D:/Github/Minesweeper-Draft/docs/claude_iteration_13`

## 2. Executive Summary

Iteration 12 validated reproducibility and safety, but failed the practical runtime gate and introduced a quality regression on `250x156`.

The Iter13 plan targets one primary change:

- Replace fixed-tight Phase2 pruning behavior with a deterministic adaptive exploration controller that widens search only when stagnation is detected, while preserving explicit solve-budget ceilings.

This plan is designed to recover missed high-value candidates on `250x156` and drive `250x250` runtime below `180s`, without coverage regression.

## 2.1 Industry-Standard Gap Analysis (Plan-Level)

Gap analysis was performed against common engineering planning controls: scope control, measurable outcomes, ownership, risk management, validation rigor, and go/no-go governance.

| Gap ID | Area | Identified Gap | Delivery Risk if Unaddressed | Remediation Added in This Plan |
|---|---|---|---|---|
| G1 | KPI precision | Goals existed, but not enough quantified stage-level targets. | Teams optimize locally without proving gate impact. | Added explicit success targets and operational SLOs in section `5.4`. |
| G2 | Ownership | File scope existed, but no named decision rights per stage. | Slow decisions and unclear accountability on regressions. | Added RACI-lite ownership model in section `6.5`. |
| G3 | Baseline control | Baseline paths were defined, but no integrity checks before comparison. | Invalid comparisons due drift, stale artifacts, or commit mismatch. | Added baseline integrity checklist in section `7.4`. |
| G4 | NFRs | Runtime and correctness intent existed, but no explicit non-functional limits by behavior. | Hidden regressions in memory, determinism, or deadline handling. | Added non-functional requirements in section `8.7`. |
| G5 | Milestone gating | Work steps existed, but exit criteria were broad. | Partial implementation can pass to benchmark prematurely. | Added milestone exit criteria in section `10.7`. |
| G6 | Statistical method | Median-only rules existed, but no tie/ambiguity method or evidence package standard. | Inconsistent acceptance decisions across runs. | Added statistical evaluation method in section `11.3`. |
| G7 | Execution choreography | Benchmark command existed, but no staged runbook with fail-fast points. | Wasted compute on known-broken builds. | Added staged execution runbook in section `12.3`. |
| G8 | Rollback trigger specificity | Rollback intent existed, but trigger thresholds were not explicit. | Late rollback and unstable branch state. | Added explicit kill-switch and trigger matrix in section `15.1`. |
| G9 | Attribution quality | Report deliverables existed, but no minimum causal-evidence standard. | Postmortem cannot separate cause from coincidence. | Added attribution evidence standards in section `16.1`. |

## 3. Iter12 Retrospective Inputs (Ground Truth)

### 3.1 Confirmed Wins

- Determinism and parity checks passed.
- Inter-repair SA telemetry and reporting are stable.
- Runtime improved materially versus older broad-search behavior.

### 3.2 Confirmed Failures

- `250x156` median regressed:
  - coverage: `0.9916 -> 0.9898` (worse)
  - n_unknown: `285 -> 342` (worse)
  - mean_abs_error: `0.7362 -> 0.7510` (worse)
- `250x250` runtime still missed hard gate:
  - median runtime: `293.3s`, target `< 180s`

### 3.3 Root-Cause Hypothesis from Iter12

- Phase2 became too restrictive in difficult states:
  - hotspot narrowing + short shortlist + low finalist caps + early stagnation exit.
- Result: less solve spend on high-upside candidates in hard pockets.

## 4. Iter13 Primary Hypothesis

If Phase2 uses deterministic adaptive breadth escalation (narrow -> medium -> broad) based on measured stagnation, with strict per-stage solve caps and hard global deadline compliance, then:

1. `250x156` will recover quality (coverage and n_unknown) by avoiding premature stagnation.
2. `250x250` runtime will decrease versus broad legacy search by keeping adaptive widening bounded and selective.
3. Determinism and reproducibility will remain intact.

## 5. Iter13 Goals, Non-Goals, and Guardrails

### 5.1 Primary Goals

1. Pass all acceptance gates on median across 3 seeds.
2. Eliminate Iter12 `250x156` quality regression versus Iter10 baseline.
3. Keep deterministic parity checks passing.
4. Keep benchmark/report schema additive only.

### 5.2 Non-Goals

- No redesign of solver internals.
- No corridor algorithm redesign.
- No multithreading inside inter-repair stage.
- No timeout inflation as a strategy.

### 5.3 Hard Guardrails

- No increasing runtime budget or deadline limits to force pass.
- Runtime gains must come from better search efficiency and candidate prioritization.
- Inter-repair SA stays module-level and synchronous.
- Existing forbidden-mask invariants remain strict.

### 5.4 Success Metrics and Operational SLO Targets

In addition to acceptance gates, Iter13 must satisfy the following operational targets during validation:

- `250x250` median runtime target: `< 180s` (hard), stretch target `< 165s`.
- `250x156` regression recovery target:
  - coverage median `>= 0.9916`
  - n_unknown median `<= 285`
- Stagnation quality target: reduce `repair2_reason == stagnated` incidence on `250x156` versus Iter12.
- Determinism target: zero mismatches for `inter_repair_sa_accepted` and `inter_repair_sa_n_unknown_out` in Check D and Check E comparisons.
- Deadline compliance target: zero deadline-overrun exceptions outside declared timeout handling paths.

## 6. Scope and File Ownership

### 6.1 Allowed Functional Edit Location

- `D:/Github/Minesweeper-Draft/src/minesweeper_recon/*.py`

### 6.2 Iter13 Wrapper/Artifact Location

- `D:/Github/Minesweeper-Draft/docs/claude_iteration_13`
- `D:/Github/Minesweeper-Draft/results/iter13/...`

### 6.3 Expected Files to Change (Functional)

1. `src/minesweeper_recon/repair_phase2.py` (primary)
2. `src/minesweeper_recon/config.py` (adaptive knobs)
3. `src/minesweeper_recon/models.py` (telemetry fields)
4. `src/minesweeper_recon/pipeline.py` (pass-through config + metrics wiring)
5. `src/minesweeper_recon/benchmark_cli.py` or summary aggregation location (additive surfacing only)

### 6.4 Expected Wrapper/Reporting Files

1. `docs/claude_iteration_13/iter13_win13.py`
2. `docs/claude_iteration_13/iter13_benchmark_ab.py`
3. `docs/claude_iteration_13/generate_iter13_reports.py`
4. `results/iter13/iter13_scorecard.md`
5. `results/iter13/iter13_what_changed.md`

### 6.5 Ownership and Decision Rights (RACI-Lite)

- Responsible (implementation): `repair_phase2.py` owner for adaptive controller and search behavior.
- Responsible (wiring): `config.py`, `models.py`, `pipeline.py`, `benchmark_cli.py` owners for additive config/telemetry/reporting.
- Accountable (gate decision): iteration lead decides `ACCEPTED`/`REJECTED` based on section `13` gates.
- Consulted: solver and runtime maintainers for determinism/deadline semantics.
- Informed: benchmark/report consumers via iter13 scorecard and what-changed outputs.

## 7. Baselines and Comparison Identifiers

### 7.1 Primary Acceptance Baseline

- `D:/Github/Minesweeper-Draft/results/iter10/iter10_win10_ab/summary_ab.json`

### 7.2 Secondary Trend Baseline

- `D:/Github/Minesweeper-Draft/results/iter12/iter12_win12_ab/summary_ab.json`

### 7.3 Source Diff Attribution Baseline

- Attribution policy: always use immediate predecessor iteration for source attribution.
  - If evaluating Iter12: attribution baseline is Iter11.
  - If evaluating Iter13: attribution baseline is Iter12.
- Baseline commit: commit that produced Iter12 benchmark artifact for Iter13 attribution (expected `c68331c748d51c50382c9ba46b8eefde56e93a93` unless superseded)
- Iter13 commit: current `HEAD` at reporting time
- Record both in:
  - `D:/Github/Minesweeper-Draft/results/iter13/<run_id>/comparison_manifest.json`

### 7.4 Baseline Integrity Checklist (Mandatory Before Benchmark Compare)

1. Verify baseline summary exists and is readable.
2. Verify baseline commit hash resolves in local git history.
3. Verify iter13 run commit hash equals `HEAD` used for execution.
4. Verify board/seed/mode matrix match baseline comparison matrix.
5. Verify strict-repro and deterministic-order settings match comparison policy.
6. Refuse publication if any checklist item fails.

## 8. Technical Design: Iter13 Primary Change

## 8.1 High-Level Design

Implement an Adaptive Phase2 Search Controller (APSC) that controls exploration breadth per round using deterministic escalation levels:

- Level 0 (narrow): current hotspot-focused fast path
- Level 1 (medium): widened hotspots + larger shortlist/finalists
- Level 2 (broad): multi-cluster coverage + larger beam branching
- Level 3 (recovery): one bounded rescue sweep before declaring stagnation

Escalation triggers only when no improvement is observed across configured rounds.
De-escalation occurs after improvement.

## 8.2 Deterministic Escalation Rules

For each outer loop round in Phase2:

1. Compute `improved_this_round`.
2. If improved:
   - reset `stagnation_rounds = 0`
   - step level down by 1 (not below 0)
3. Else:
   - increment `stagnation_rounds`
   - escalate when `stagnation_rounds >= threshold[level]`
4. Never exceed `max_level = 3`.
5. All tie-breakers remain lexicographic on coordinates and stable candidate keys.

## 8.3 Multi-Cluster Hotspot Diversification

Replace single-density-biased unknown selection with deterministic multi-cluster anchor selection:

- Partition unknown cells into connected clusters.
- Rank clusters by:
  1. size desc
  2. centroid `(y,x)` asc for tie-break
- Allocate anchor budget across top-K clusters by weighted round-robin.
- Build selected unknown working set from each chosen cluster using configured radius.

Expected effect:

- Avoid over-focusing one unresolved pocket.
- Increase chance of finding quality moves when dominant cluster is misleading.

## 8.4 Adaptive Candidate and Solve Caps

Per level, define deterministic caps:

- hotspot_top_k
- hotspot_radius
- delta_shortlist
- beam_width
- beam_depth
- beam_branch
- finalist_fullsolve_cap
- max_action_candidates

Also enforce global constraints every round:

- `remaining_budget_s` from global deadline
- `max_round_fullsolves` derived from observed `avg_solve_s`
- hard cap floor and ceiling

No separate budget line is introduced; consumption remains implicit under global deadline.

## 8.5 Rescue Sweep (Level 3)

One bounded rescue sweep when level reaches 3 and stagnation persists:

- Expand candidate set across additional clusters.
- Temporarily increase shortlist and finalist cap within round hard cap.
- Execute once per board or once per stagnation epoch (configurable).

If still no improvement, terminate with `stagnated`.

## 8.6 Telemetry Requirements

Add level-aware telemetry so failure modes are diagnosable:

- `phase2_level0_rounds`
- `phase2_level1_rounds`
- `phase2_level2_rounds`
- `phase2_level3_rounds`
- `phase2_escalations`
- `phase2_deescalations`
- `phase2_rescue_sweeps`
- `phase2_cluster_count_avg`
- `phase2_clusters_scanned_total`
- `phase2_round_fullsolve_cap_avg`
- `phase2_stagnation_exit_level`

All additive; no breaking schema changes.

## 8.7 Non-Functional Requirements (NFRs)

- Determinism: all new ordering decisions must be stable and tie-broken deterministically.
- Bounded compute: every adaptive widening step must remain under per-round solve caps.
- Deadline safety: all new branches must honor `global_deadline_s` semantics.
- Backward compatibility: disabling adaptive mode should recover Iter12-equivalent behavior envelope.
- Observability: each adaptive transition must be inferable from telemetry alone.
- Maintainability: helper functions should remain module-level and avoid hidden closures for multiprocessing compatibility.

## 9. Configuration Plan (Additive)

Add Iter13 knobs to `BoardConfig` with conservative defaults:

- `phase2_adaptive_enabled: bool = True`
- `phase2_level_threshold_l0: int = 2`
- `phase2_level_threshold_l1: int = 2`
- `phase2_level_threshold_l2: int = 2`
- `phase2_level_max: int = 3`
- `phase2_rescue_once: bool = True`
- `phase2_cluster_top_k: int = 4`
- `phase2_cluster_min_share: int = 1`

Per-level cap tuples (or explicit fields) for deterministic tuning:

- `phase2_l0_hotspot_top_k`, `phase2_l1_hotspot_top_k`, ...
- `phase2_l0_delta_shortlist`, `phase2_l1_delta_shortlist`, ...
- `phase2_l0_fullsolve_cap`, `phase2_l1_fullsolve_cap`, ...

If tuple fields are awkward for dataclasses, use explicit per-level scalar fields.

## 10. Detailed Implementation Work Plan

## 10.1 Step A: Phase2 Controller Skeleton

File: `src/minesweeper_recon/repair_phase2.py`

Tasks:

1. Add internal level state struct (local variables, no new class required).
2. Add deterministic escalation/de-escalation logic.
3. Map level -> caps each round.
4. Ensure existing candidate-generation path uses active level caps.

Done criteria:

- Compiles.
- Existing behavior replicated when adaptive disabled.

## 10.2 Step B: Multi-Cluster Unknown Selection

File: `src/minesweeper_recon/repair_phase2.py`

Tasks:

1. Add helper to compute unknown clusters deterministically.
2. Add helper to allocate hotspot anchors across clusters.
3. Replace current single-pass hotspot selection with cluster-aware selection.

Done criteria:

- Stable output ordering across runs with identical seeds.
- No regression in forbidden-mask handling.

## 10.3 Step C: Rescue Sweep and Exit Semantics

File: `src/minesweeper_recon/repair_phase2.py`

Tasks:

1. Add one-shot rescue sweep path at top level.
2. Add telemetry counters for rescue usage and final exit level.
3. Preserve reason semantics (`stagnated`, `timeout`, etc).

Done criteria:

- Rescue path invoked only under configured conditions.
- Never violates solve/deadline constraints.

## 10.4 Step D: Config and Metrics Wiring

Files:

- `src/minesweeper_recon/config.py`
- `src/minesweeper_recon/models.py`
- `src/minesweeper_recon/pipeline.py`

Tasks:

1. Add config fields with defaults.
2. Extend `RepairContext` and `PipelineMetrics` with new telemetry fields.
3. Populate new fields in `PipelineMetrics(...)` creation.

Done criteria:

- `to_dict()` and `from_dict()` parity maintained.
- JSON outputs include all new fields.

## 10.5 Step E: Benchmark Summary Surfacing

File:

- `src/minesweeper_recon/benchmark_cli.py` (or actual summary aggregator)

Tasks:

1. Add key Iter13 Phase2 telemetry fields to per-run summary output (CSV and JSON path remains additive).
2. Keep previous inter-SA fields intact.
3. Keep internal gate computation required even when running `--modes fast` only.
4. Add internal payload fields:
   - `gate_version`
   - `baseline_summary_path`
   - `baseline_commit`
   - per-gate medians and deltas
   - failed-tasks guard status
5. Do not alter existing field names for already-published metrics.

Done criteria:

- `summary_ab.json` and `summary_ab.csv` parse cleanly.
- Internal gates are present in payload for fast-only runs via explicit baseline input.
- Downstream report script can consume additional fields and independently recompute gates.

## 10.6 Step F: Iter13 Wrappers and Reporting Script

Files in `docs/claude_iteration_13`:

1. `iter13_win13.py` (single-run wrapper)
2. `iter13_benchmark_ab.py` (benchmark wrapper)
3. `generate_iter13_reports.py` (scorecard + what changed)

Tasks:

- Align default output roots to `results/iter13/...`.
- Ensure baseline references point to Iter10 primary baseline.
- Emit comparison manifest with baseline/iter13 commit IDs.
- Keep external independent gate recompute in reporting even when internal gates are present.

Done criteria:

- Scripts run without manual path editing.
- Outputs written to iter13 directories only.
- Report output clearly flags mismatch if internal and external gate verdicts differ.

## 10.7 Milestone Exit Criteria (Quality Gates)

- M1 exit:
  - Code compiles and adaptive mode toggles on/off without runtime exceptions.
- M2 exit:
  - Multi-cluster selection and rescue sweep produce deterministic traces in repeated dry runs.
- M3 exit:
  - New telemetry fields round-trip through `to_dict()` and `from_dict()`.
- M4 exit:
  - Checks A-I produce explicit PASS/FAIL evidence files or console logs.
- M5 exit:
  - Full 3-board x 3-seed matrix completed and summaries generated.
- M6 exit:
  - Final decision documented with gate-by-gate rationale and attributable source diffs.

## 11. Validation Protocol (Required)

## 11.1 Existing A-E Class Checks

Re-run and record pass/fail with evidence:

- A: Forbidden mask integrity on accepted path.
- B: Coverage regression triggers full revert path.
- C: Skip branches fire correctly (`already_solved`, cap, budget tight).
- D: strict-repro double-run parity.
- E: board-jobs parity (`1` vs `2`).

## 11.2 New Iter13 Checks

- F: Adaptive-level determinism
  - same seed/run -> identical level transition sequence
- G: Rescue sweep boundedness
  - no more than configured rescue count
- H: Deadline compliance
  - no phase exceeds global deadline path
- I: Telemetry completeness
  - all new fields present in per-run metrics

## 11.3 Statistical Evaluation Method and Evidence Package

- Primary comparator: median across seeds for each board and metric.
- Secondary comparator: per-seed signed deltas to detect instability hidden by medians.
- Tie handling:
  - absolute delta `<= 1e-9` classified as unchanged.
- Decision evidence package per gate:
  - baseline median
  - iter13 median
  - absolute delta
  - pass/fail result
  - per-seed values for auditability
- Reproducibility evidence package:
  - Check D pair outputs
  - Check E pair outputs
  - config fingerprint and commit hash
- Dual-gate evidence package:
  - internal gate payload verdict and details
  - external independent recompute verdict and details
  - explicit mismatch flag (must be false for publication)

## 12. Benchmark Execution Plan

## 12.1 Matrix Command (Primary)

```powershell
python D:/Github/Minesweeper-Draft/docs/claude_iteration_13/iter13_benchmark_ab.py --modes fast --boards 200x125 250x156 250x250 --seeds 300 301 302 --strict-repro --deterministic-order on --baseline-summary D:/Github/Minesweeper-Draft/results/iter10/iter10_win10_ab/summary_ab.json --baseline-commit <iter10_commit_or_resolved_id> --verbose
```

## 12.2 Optional Diagnostic Matrix (If Needed)

- Per-board isolation run for `250x156` with same seeds.
- One `--jobs 2` parity run to validate nondeterminism risk.

## 12.3 Execution Runbook (Fail-Fast Sequence)

1. Run static compile check (`py_compile`) on touched modules.
2. Execute unit/synthetic validation checks A-C before any long benchmark.
3. Execute determinism checks D and E.
4. Run primary matrix command.
5. Generate scorecard and what-changed reports.
6. Run acceptance-gate evaluation and publish decision.
7. Stop pipeline immediately if coverage regression appears on `200x125` or `250x250` during trial runs.

## 13. Acceptance Gates (Hard)

Candidate is accepted only if all pass on medians across 3 seeds:

1. No coverage regression on `200x125` and `250x250`.
2. `n_unknown` equal or lower on median.
3. `mean_abs_error` equal or lower on `250x250`.
4. Runtime at `250x250` strictly `< 180s`.

Additional Iter13 gate:

5. `250x156` must not regress versus Iter10 baseline on both coverage and n_unknown.

Gate execution policy:

6. Internal gates are mandatory in benchmark payload and must use explicit baseline input.
7. External reporting must independently recompute gates from raw summary data.
8. Publication is blocked if internal and external gate verdicts disagree.

## 14. Decision Logic

Priority order when metrics conflict:

1. Coverage stability and deterministic solvability
2. Reproducibility
3. Runtime
4. Visual fidelity (`mean_abs_error`, `loss_per_cell`)

Do not trade coverage regression for runtime improvement.
Do not trade reproducibility for throughput.

## 15. Rollback and Contingency Plan

If Iter13 fails gates:

1. Keep code but set adaptive controller default to conservative disabled mode.
2. Preserve telemetry so failed behavior is attributable.
3. Document root cause in Iter13 reports.
4. Do not remove safety checks.

No destructive git operations are part of this plan.

## 15.1 Explicit Kill-Switch and Rollback Triggers

- Trigger R1: any deterministic parity failure in Check D or Check E.
  - Action: disable adaptive mode default and block acceptance.
- Trigger R2: coverage regression on `200x125` or `250x250` medians.
  - Action: immediate reject; keep telemetry for postmortem.
- Trigger R3: runtime remains `>= 180s` at `250x250` median after tuning sweep.
  - Action: reject iteration and retain best diagnostic configuration artifact.
- Trigger R4: unexplained telemetry inconsistency (missing required fields).
  - Action: block report publication until fixed.

## 16. Reporting Deliverables

Required outputs:

1. `D:/Github/Minesweeper-Draft/results/iter13/iter13_scorecard.md`
2. `D:/Github/Minesweeper-Draft/results/iter13/iter13_what_changed.md`
3. `D:/Github/Minesweeper-Draft/results/iter13/<run_id>/comparison_manifest.json`
4. `summary_ab.json` and `summary_ab.csv` in run directory

`iter13_what_changed.md` must include:

- executive plain-English outcome
- goal-gap scoreboard
- per-board interpretation
- technique-to-effect mapping with confidence
- gate-by-gate verdict
- source-change attribution per modified file

## 16.1 Attribution Evidence Standard (Minimum)

Each claimed improvement or regression must include:

1. The metric and board impacted.
2. The exact source file(s) and change category.
3. The expected mechanism of effect.
4. The observed telemetry evidence that supports or weakens that mechanism.
5. Confidence level: `high`, `medium`, or `low`.

## 17. Suggested Milestone Sequence

1. M1: Implement adaptive controller skeleton and compile.
2. M2: Add cluster diversification and rescue sweep.
3. M3: Wire config + telemetry + summary fields.
4. M4: Run A-E + new F-I checks.
5. M5: Run benchmark matrix and generate reports.
6. M6: Gate decision and final documentation.

## 18. Definition of Done

Iter13 is complete only when all conditions are true:

1. Code compiles and runs in strict-repro mode.
2. Validation checks A-I are documented pass/fail with evidence.
3. Standard matrix results are generated under `results/iter13/...`.
4. Scorecard and what-changed reports exist and are internally consistent.
5. Comparison manifest records baseline path and both commit IDs.
6. Acceptance decision is explicit: `ACCEPTED` or `REJECTED` with reason.

## 19. Out-of-Scope Reminder

The following remain out of scope unless separately approved:

- solver algorithm redesign
- corridor algorithm redesign
- SA kernel redesign
- deadline/timeout inflation as optimization strategy

## 20. Immediate Next Action

Begin with Phase2 adaptive controller implementation in `repair_phase2.py`, then wire config and telemetry before running validation checks.

## 21. Gap Closure Checklist for Iter13

Before declaring Iter13 complete, confirm all gap items are closed:

- G1 closed: quantified SLO targets checked and reported.
- G2 closed: RACI-lite ownership applied during implementation and decisioning.
- G3 closed: baseline integrity checklist executed and archived.
- G4 closed: NFR checks documented in validation output.
- G5 closed: each milestone has explicit exit evidence.
- G6 closed: statistical evidence package produced with per-seed deltas.
- G7 closed: fail-fast runbook followed in order.
- G8 closed: rollback triggers evaluated and documented as not triggered or triggered.
- G9 closed: report attribution includes mechanism + telemetry confidence mapping.

# Iteration 13 Execution Plan (Companion to `iter13_plan.md`)

## 1. Purpose and Relationship to Master Plan

This document is the operational companion to:

- `D:/Github/Minesweeper-Draft/docs/claude_iteration_13/iter13_plan.md`

`iter13_plan.md` defines strategy, scope, and governance.
This document defines exact execution order, commands, checkpoints, and evidence required to complete Iteration 13.

## 2. Execution Objectives

1. Implement Iter13 adaptive Phase2 search changes exactly within approved scope.
2. Preserve deterministic behavior and safety invariants.
3. Produce reproducible benchmark and validation artifacts under `results/iter13/...`.
4. Produce auditable acceptance decision using defined gates.

## 3. Scope and Constraints (Execution-Time)

Allowed functional code location:

- `D:/Github/Minesweeper-Draft/src/minesweeper_recon`

Allowed Iter13 wrappers/docs location:

- `D:/Github/Minesweeper-Draft/docs/claude_iteration_13`

Allowed result location:

- `D:/Github/Minesweeper-Draft/results/iter13`

Hard constraints:

- No timeout/deadline inflation to force pass.
- No redesign of solver, corridor, or SA kernel.
- Additive telemetry/schema only.
- Preserve deterministic ordering and reproducibility controls.

## 4. Definitions of Ready / Done

## 4.1 Definition of Ready

Execution can begin only when all are true:

1. Baseline artifacts exist:
   - `results/iter10/iter10_win10_ab/summary_ab.json`
   - `results/iter12/iter12_win12_ab/summary_ab.json`
2. Baseline commit hashes resolve in git.
3. Working tree status is recorded.
4. Iter13 output root exists or can be created.

## 4.2 Definition of Done

Iteration is complete only when all are true:

1. Work packages WP1-WP8 are complete with evidence.
2. Checks A-I executed with pass/fail evidence artifacts.
3. Standard matrix benchmark executed and summaries generated.
4. `iter13_scorecard.md` and `iter13_what_changed.md` generated.
5. `comparison_manifest.json` contains baseline and iter13 commit IDs.
6. Acceptance decision documented: `ACCEPTED` or `REJECTED`.

## 5. Directory and Artifact Contract

Execution root:

- `D:/Github/Minesweeper-Draft`

Iteration docs:

- `D:/Github/Minesweeper-Draft/docs/claude_iteration_13`

Execution evidence:

- `D:/Github/Minesweeper-Draft/results/iter13/<run_id>/...`

Required artifacts per full run:

1. `summary_ab.json`
2. `summary_ab.csv`
3. `comparison_manifest.json`
4. `iter13_scorecard.md`
5. `iter13_what_changed.md`
6. validation evidence files/logs for checks A-I

Recommended run id format:

- `iter13_win13_ab_<YYYYMMDD_HHMMSS>`

## 6. Baseline Integrity Procedure (Mandatory)

Run before any code changes:

```powershell
cd D:/Github/Minesweeper-Draft
git status --short
Test-Path D:/Github/Minesweeper-Draft/results/iter10/iter10_win10_ab/summary_ab.json
Test-Path D:/Github/Minesweeper-Draft/results/iter12/iter12_win12_ab/summary_ab.json
git rev-parse 05fa7ed
```

Create baseline manifest draft at:

- `D:/Github/Minesweeper-Draft/results/iter13/<run_id>/comparison_manifest.json`

Initial required fields:

- `baseline_summary_path`
- `baseline_commit`
- `iter13_commit` (placeholder until final commit)
- `comparison_timestamp`
- `attribution_baseline_iteration` (must be immediate predecessor, i.e., Iter12 for Iter13)
- `gate_version`

## 7. Work Package Breakdown

## 7.1 WP1: Adaptive Phase2 Controller Skeleton

File target:

- `src/minesweeper_recon/repair_phase2.py`

Tasks:

1. Add adaptive level state machine (L0-L3).
2. Add deterministic escalation/de-escalation logic.
3. Apply level-mapped caps during each Phase2 outer loop.
4. Preserve existing behavior when adaptive mode disabled.

Exit criteria:

- Module compiles.
- No functional regressions when adaptive off.
- Telemetry captures level progression counters.

Evidence:

- diff snippet
- compile success log

## 7.2 WP2: Multi-Cluster Hotspot Diversification

File target:

- `src/minesweeper_recon/repair_phase2.py`

Tasks:

1. Deterministic cluster extraction for unknown regions.
2. Deterministic cluster ranking and anchor allocation.
3. Working set assembly from multiple clusters.

Exit criteria:

- Stable outputs across repeated same-seed runs.
- No forbidden-region violations introduced.

Evidence:

- deterministic sample trace output
- telemetry showing cluster scan counts

## 7.3 WP3: Level-3 Rescue Sweep

File target:

- `src/minesweeper_recon/repair_phase2.py`

Tasks:

1. Implement bounded rescue sweep policy.
2. Respect per-round solve caps and global deadline.
3. Track rescue sweep telemetry and exit level.

Exit criteria:

- Rescue executes only under configured conditions.
- Cannot loop indefinitely.

Evidence:

- unit/synthetic scenario demonstrating rescue trigger and bounded termination

## 7.4 WP4: Config and Context Wiring

File targets:

- `src/minesweeper_recon/config.py`
- `src/minesweeper_recon/models.py`
- `src/minesweeper_recon/pipeline.py`

Tasks:

1. Add Iter13 adaptive config fields (additive defaults).
2. Extend `RepairContext` with needed parameters.
3. Extend `PipelineMetrics` with Iter13 telemetry fields.
4. Wire fields through `to_dict()` and `from_dict()`.

Exit criteria:

- Round-trip serialization parity confirmed.
- Existing fields unchanged.

Evidence:

- serialization check output

## 7.5 WP5: Benchmark Summary Surfacing

File target:

- `src/minesweeper_recon/benchmark_cli.py` (or active summary aggregator)

Tasks:

1. Surface Iter13 adaptive telemetry per run.
2. Keep existing inter-SA fields intact.
3. Keep schema additive and backward compatible.
4. Compute internal gates for fast-only runs using explicit baseline input.
5. Include in internal payload:
   - `gate_version`
   - `baseline_summary_path`
   - `baseline_commit`
   - per-gate medians
   - per-gate deltas
   - failed-tasks guard verdict

Exit criteria:

- `summary_ab.json` and `summary_ab.csv` include new fields without breaking existing consumers.
- Internal gate payload is non-empty for fast-only benchmark runs.

Evidence:

- sample rows from JSON and CSV

## 7.6 WP6: Iter13 Wrappers and CLI Entry Points

File targets:

- `docs/claude_iteration_13/iter13_win13.py`
- `docs/claude_iteration_13/iter13_benchmark_ab.py`

Tasks:

1. Add wrapper scripts that call canonical src logic.
2. Default outputs to `results/iter13/...`.
3. Preserve strict-repro and deterministic-order support.

Exit criteria:

- Wrappers run without path edits.

Evidence:

- wrapper invocation logs

## 7.7 WP7: Validation Automation

File target:

- `docs/claude_iteration_13/generate_iter13_reports.py` and optional validation helper script

Tasks:

1. Ensure checks A-I can be executed and recorded consistently.
2. Ensure report generator consumes Iter13 summary fields.
3. Ensure `comparison_manifest.json` is written with final commit IDs.
4. Ensure external reporting independently recomputes gates from summaries and compares with internal payload.

Exit criteria:

- Validation evidence generated in machine-readable form.
- External gate recompute result matches internal gate payload.

Evidence:

- validation output file(s)

## 7.8 WP8: Benchmark + Decision + Reporting

Tasks:

1. Run full matrix benchmark.
2. Generate scorecard and what-changed reports.
3. Apply acceptance gates and document decision.

Exit criteria:

- Decision file and report artifacts complete.

Evidence:

- final scorecard
- final what-changed
- final manifest

## 8. Validation Execution (Checks A-I)

## 8.1 Check A

- Validate forbidden mask integrity on accepted inter-repair path.
- Required assertion:

```python
assert int(np.sum((grid == 1) & (forbidden == 1))) == 0
```

## 8.2 Check B

- Force coverage regression case.
- Confirm full revert to pre-inter-SA grid/solve result.

## 8.3 Check C

- Validate skip branches:
  - `already_solved`
  - `n_unknown_exceeds_cap`
  - `budget_too_tight`

## 8.4 Check D

- Run strict-repro twice.
- Confirm equality for:
  - `inter_repair_sa_accepted`
  - `inter_repair_sa_n_unknown_out`

## 8.5 Check E

- Compare `--board-jobs 1` vs `--board-jobs 2`.
- Confirm parity for stage acceptance and selected deterministic fields.

## 8.6 Check F

- Confirm adaptive level sequence is deterministic for fixed seed/board.

## 8.7 Check G

- Confirm rescue sweep boundedness (no > configured max).

## 8.8 Check H

- Confirm deadline compliance: no unexpected budget overruns.

## 8.9 Check I

- Confirm all new Iter13 telemetry fields present in metrics output.

## 8.10 Validation Evidence Storage

Store validation evidence under:

- `D:/Github/Minesweeper-Draft/results/iter13/<run_id>/validation/`

Suggested filenames:

- `checkA.txt`
- `checkB.txt`
- `checkC.txt`
- `checkD.txt`
- `checkE.txt`
- `checkF.txt`
- `checkG.txt`
- `checkH.txt`
- `checkI.txt`
- `validation_summary.md`

## 9. Benchmark Execution Runbook

## 9.1 Pre-Benchmark Fast-Fail

```powershell
cd D:/Github/Minesweeper-Draft
python -m py_compile src/minesweeper_recon/pipeline.py src/minesweeper_recon/repair_phase2.py src/minesweeper_recon/models.py src/minesweeper_recon/config.py src/minesweeper_recon/benchmark_cli.py
```

Stop if compile fails.

## 9.2 Primary Matrix Command

```powershell
python D:/Github/Minesweeper-Draft/docs/claude_iteration_13/iter13_benchmark_ab.py --modes fast --boards 200x125 250x156 250x250 --seeds 300 301 302 --strict-repro --deterministic-order on --baseline-summary D:/Github/Minesweeper-Draft/results/iter10/iter10_win10_ab/summary_ab.json --baseline-commit <iter10_commit_or_resolved_id> --verbose
```

## 9.3 Optional Diagnostics

```powershell
python D:/Github/Minesweeper-Draft/docs/claude_iteration_13/iter13_benchmark_ab.py --modes fast --boards 250x156 --seeds 300 301 302 --strict-repro --deterministic-order on --verbose
python D:/Github/Minesweeper-Draft/docs/claude_iteration_13/iter13_benchmark_ab.py --modes fast --boards 200x125 250x156 250x250 --seeds 300 301 302 --strict-repro --deterministic-order on --jobs 2 --verbose
```

## 9.4 Report Generation

```powershell
python D:/Github/Minesweeper-Draft/docs/claude_iteration_13/generate_iter13_reports.py --baseline-summary D:/Github/Minesweeper-Draft/results/iter10/iter10_win10_ab/summary_ab.json --iter13-summary D:/Github/Minesweeper-Draft/results/iter13/<run_id>/summary_ab.json --baseline-commit <iter10_commit_or_resolved_id> --require-internal-gates --recompute-gates --out-dir D:/Github/Minesweeper-Draft/results/iter13
```

## 10. Acceptance Decision Process

## 10.1 Gate Evaluation

Required gates (median across 3 seeds):

1. Coverage non-regression on `200x125` and `250x250`.
2. `n_unknown` non-increasing.
3. `mean_abs_error` non-increasing at `250x250`.
4. `250x250` runtime `< 180s`.
5. `250x156` no regression on coverage and n_unknown vs Iter10 baseline.
6. Internal gates present in payload (required, not optional).
7. Internal and external recompute gate verdicts must match.

## 10.2 Decision Tree

- If all gates pass -> `ACCEPTED`.
- If any gate fails -> `REJECTED` and record primary failure cause.
- If determinism checks fail -> immediate reject regardless of quality/runtime.
- If internal gate payload is missing/empty -> immediate reject.
- If internal and external gate verdicts mismatch -> immediate reject until reconciled.

## 10.3 Decision Artifact

Create:

- `D:/Github/Minesweeper-Draft/results/iter13/iter13_decision.md`

Required content:

1. gate-by-gate pass/fail table
2. acceptance verdict
3. top 3 causal findings
4. follow-up action list
5. internal gate payload snapshot (`gate_version`, baseline metadata, per-gate medians/deltas)
6. external recompute snapshot and match/mismatch status

## 11. Rollback / Kill-Switch Execution

If rollback trigger fires:

1. Set adaptive defaults to safe-conservative mode (or disabled) in config.
2. Keep telemetry fields enabled for diagnosis.
3. Re-run minimal validation (A, D, E) to confirm stability.
4. Record rollback reason in decision artifact.
5. If trigger is gate mismatch, archive both internal payload and external recompute details for audit.

## 12. Traceability Matrix (Plan -> Execution)

| Master Plan Section | Execution Section in This Doc | Evidence Artifact |
|---|---|---|
| Hypothesis and goals | 2, 10 | `iter13_decision.md` |
| Scope and guardrails | 3, 5 | git diff + manifest |
| Technical design | 7.1-7.3 | code diffs + telemetry |
| Validation A-I | 8 | `validation/` files |
| Benchmark protocol | 9 | `summary_ab.json/csv` |
| Acceptance gates | 10.1 | scorecard + decision doc |
| Internal vs external gate parity | 7.7, 9.4, 10 | decision doc + recompute log |
| Rollback policy | 11 | decision doc + config diff |

## 13. Execution Checklist (Operator)

1. Complete baseline integrity checks.
2. Implement WP1-WP5 in src.
3. Implement WP6-WP7 in docs/results tooling.
4. Run compile fast-fail.
5. Run checks A-I and archive outputs.
6. Run benchmark matrix and archive outputs.
7. Generate reports and manifest.
8. Evaluate gates and publish decision.
9. If rejected, execute rollback protocol and document.

## 14. Final Deliverables Checklist

1. Updated source files in `src/minesweeper_recon`.
2. Iter13 wrapper/report scripts in `docs/claude_iteration_13`.
3. `results/iter13/<run_id>/summary_ab.json`.
4. `results/iter13/<run_id>/summary_ab.csv`.
5. `results/iter13/<run_id>/comparison_manifest.json`.
6. `results/iter13/iter13_scorecard.md`.
7. `results/iter13/iter13_what_changed.md`.
8. `results/iter13/iter13_decision.md`.
9. `results/iter13/<run_id>/validation/validation_summary.md`.

## 15. Immediate Start Command Block

```powershell
cd D:/Github/Minesweeper-Draft
git status --short
python -m py_compile src/minesweeper_recon/pipeline.py src/minesweeper_recon/repair_phase2.py src/minesweeper_recon/models.py src/minesweeper_recon/config.py src/minesweeper_recon/benchmark_cli.py
```

After this block passes, start WP1 in `src/minesweeper_recon/repair_phase2.py`.

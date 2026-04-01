# AGENTS.MD

## 1) Audit Scope (Completed)

This guide is based on a full audit of:

- `D:/Github/Minesweeper/docs/claude_minesweeper_conversations.json`

Audit coverage:

- Conversations: 2
- Messages: 12
- Tool uses: 67
- Tool results: 67
- Files created in-history: 11
- Non-zero command exits observed: 6
- Explicit tool-result errors: 2

Important caveat:

- 67 assistant display blocks in the exported text were marked as unsupported in the source viewer.
- Decisions in this document are grounded on `tool_use` + `tool_result` records and explicit metric outputs, not unsupported display fragments.

## 2) Project Goal (Canonical)

Build a Minesweeper board generator that transforms an input image into a mine layout such that:

1. The resulting number field approximates the image faithfully.
2. The board is logically solvable without guessing (target state).
3. The pipeline scales to large boards (up to at least 250x250) from high-resolution images (up to 2000x2000 px input).

## 3) Hard Constraints and Success Criteria

Hard constraints:

- Number validity: all computed numbers must remain in `[0, 8]`.
- Deterministic logic: solver coverage should approach full logical revelation.
- Reproducibility: all optimization runs must be seed-controlled.

Primary metrics:

- `loss_per_cell` (lower is better)
- `mean_abs_error` for `|N - T|` (lower is better)
- `coverage` (higher is better)
- `n_unknown` (lower is better)
- `mine_accuracy` (higher is better)
- Runtime by board size

## 4) Validated Architecture From Prior Iterations

Core flow:

1. `load_image_smart` preprocessing (crop panel, grayscale/contrast, resize, normalize to `[0,8]` target).
2. Edge-weight map generation (`compute_edge_weights`) for perceptual emphasis.
3. Structured initialization with mine constraints and corridor strategy.
4. Numba-accelerated SA inner loop (`_sa_inner`) with incremental neighborhood updates.
5. Solver pass (`solve_board` or incremental solver path) for logical coverage.
6. Repair pass (`targeted_repair` then `batched_repair`) to reduce unknown safe cells.
7. Optional post-repair SA (currently unstable for coverage).
8. Render + metrics export.

Key historical implementation files (snapshot locations in this repo):

- `docs/claude_iteration_1-6/iter1.py` ... `iter6.py`
- `docs/claude_iteration_8/iter8.py`
- `docs/claude_iteration_9/iter9.py` (exists but is outside the audited JSON history)

## 5) Iteration Ledger (Condensed)

### Iterations 1-5 (small-board synthetic)

- Iter 1 baseline SA: low coverage due to excessive mine density.
- Iter 2: density control + border + better solver; major coverage jump.
- Iter 3: repair pass; coverage near complete but fidelity cost increased.
- Iter 4: solvability-constrained revert loop; little effective loss recovery.
- Iter 5: joint objective (`visual + solvability`) improved balance.

Verified metrics:

| Iter | Loss | Coverage | Mine Density | Solvable |
|---|---:|---:|---:|---|
| 1 | 2296.902 | 0.0121 | 0.4483 | False |
| 2 | 3797.263 | 0.8796 | 0.3633 | False |
| 3 | 5050.601 | 0.9952 | 0.3083 | False |
| 4 | 5633.437 | 0.9976 | 0.3067 | False |
| 5 | 4384.728 | 0.9827 | 0.3250 | False |

### Iteration 6 (first large-scale real image)

Major events:

- Introduced large-scale engine and Numba SA.
- Fixed `_sa_inner` export bug.
- Fixed int8 upsample overflow (`255 out of bounds for int8`).
- Hit repair scalability bottleneck (O(C^2) solver in repair loop).

### Iteration 7 (scalability fix pass)

Key additions:

- `IncrementalSolver` for local coverage impact checks.
- `batched_repair` for reduced full-resolve frequency.
- Post-repair SA revert guard based on coverage regression.

Verified metrics:

| Board | Loss/Cell | MAE | Coverage | Unknown | Mine Accuracy | Time |
|---|---:|---:|---:|---:|---:|---:|
| 120x75 | 2.4143 | 1.0371 | 0.9984 | 12 | 0.9918 | 17.3s |
| 200x125 | 1.8738 | 0.8022 | 0.9996 | 9 | 0.9974 | 44.1s |

### Iteration 8 (adaptive corridor architecture)

Root cause identified:

- Fixed-grid corridors forced zeros on 54.5% of cells and blocked 2049 high-target cells (T>3), limiting visual fidelity.

Change:

- Replaced fixed corridors with adaptive MST-style corridors routed through low-target regions.

Verified metrics:

| Board | Loss/Cell | MAE | Coverage | Unknown | Density | Corridor % | Time |
|---|---:|---:|---:|---:|---:|---:|---:|
| 200x125 | 2.0834 | 0.8201 | 0.9991 | 19 | 0.1306 | 28.1 | 26.2s |
| 250x156 | 1.8225 | 0.7274 | 0.9990 | 33 | 0.1198 | 21.62 | 51.9s |
| 250x250 | 1.8143 | 0.6914 | 0.9994 | 36 | 0.1117 | 16.17 | 147.2s |

## 6) Current State (Most Defensible Reading)

What is working:

- End-to-end generation scales to 250x250 in under 3 minutes (observed 147.2s).
- Coverage is consistently very high (~0.999+), with small unknown pockets.
- Incremental + batched repair removed the Iteration 6 timeout bottleneck.

What is not solved:

- True full deterministic solve is still not reached (`solvable=False` in all reported runs).
- Post-repair SA still tends to degrade coverage and is reverted.
- Effective mine density remains low (about 0.11-0.14 in large runs), constraining visual expressiveness.

## 7) Known Risks and Open Technical Questions

1. Coverage-fidelity coupling remains unstable after repair.
2. Corridor-protected topology is fragile; small SA moves can disconnect logic paths.
3. Density ceiling is not being fully exploited in adaptive runs.
4. Some residual unknown cells may be unavoidable 50/50 structures.
5. 200x125 quality regressed in Iter 8 versus Iter 7, despite better architecture at larger scales.

## 8) Required Method for Future Iterations

All future agents should follow this protocol:

1. Start from the best reproducible baseline artifact and record commit/hash.
2. Change one main hypothesis at a time (corridor geometry, SA acceptance policy, density policy, repair strategy).
3. Run the fixed benchmark matrix:
   - 200x125
   - 250x156
   - 250x250
4. Use at least 3 seeds per configuration before declaring improvement.
5. Report median and worst-case for coverage, unknown count, and MAE.
6. Reject any candidate that improves loss but regresses coverage by >0.001.
7. Keep a revert guard for post-repair stages until a safer constrained SA is validated.

## 9) Priority Backlog (Next Iteration)

Highest priority:

1. Corridor-width sensitivity (`width=0` and `width=1`) with connectivity checks.
2. Corridor-aware SA move rejection (block mine flips near corridor critical paths).
3. Integrate reachability penalty throughout main SA (not refinement only).

Secondary:

1. Adaptive density schedule by board size and target histogram.
2. Constrained post-repair SA with hard topology lock on critical corridor cells.
3. Calibration of coverage-vs-fidelity trade curve for deterministic stop criteria.

## 10) Definition of Done for Next Stable Baseline

A new baseline should only be accepted if all are met:

1. Reproducible across 3 seeds.
2. No regression in median coverage on 200x125 and 250x250.
3. Equal or lower median `n_unknown` at same scales.
4. Equal or lower median `mean_abs_error` at 250x250.
5. Runtime at 250x250 remains under 180 seconds on equivalent hardware.

## 11) Operational Note for Agents

When numbers conflict across narratives and logs, treat tool-result metric dumps as source of truth.

## Iteration 12 Plan: Hotspot-Focused Repair With Attributable Results

### Summary
- Objective: reduce `n_unknown` and runtime on large boards without coverage regression, using deterministic hotspot-focused methods instead of broader expensive search.
- Code location policy: all functional `.py` edits go only in [src/minesweeper_recon](D:/Github/Minesweeper-Draft/src/minesweeper_recon).  
- Iteration artifact policy: Iter12 runners/docs live in [docs/claude_iteration_12](D:/Github/Minesweeper-Draft/docs/claude_iteration_12) as wrappers/spec artifacts, not forked logic copies.
- Results policy: all Iter12 outputs go under `D:/Github/Minesweeper-Draft/results/iter12/...`.
- Baseline comparison identifiers:
  - Primary acceptance baseline: `D:/Github/Minesweeper-Draft/results/iter10/iter10_win10_ab/summary_ab.json`
  - Secondary trend reference: Iter11 check outputs under `D:/Github/Minesweeper-Draft/results/iter11/*`

### Implementation Changes
- Algorithmic scope for Iter12:
  - ROI-only SA move sampling in inter-repair SA (module-level, synchronous, no threading, same coverage gate).
  - Deterministic 50/50 pattern-breaker pass before Phase2.
  - Hotspot-pruned Phase2 candidate generation.
  - Heuristic delta ranking to reduce full-board solves per round.
  - Deterministic bounded beam search (hotspot-local) replacing purely greedy single-step pick.
- Keep changes additive and localized:
  - No solver/corridor redesign.
  - No timeout inflation.
  - No breaking summary schema changes.

### Iter12 “What Changed” Reporting Spec (expanded)
- Create [iter12_what_changed.md](D:/Github/Minesweeper-Draft/results/iter12/iter12_what_changed.md) with these required sections:
  1. **Executive outcome (plain English)**: 3-6 lines on whether Iter12 moved closer to a fully solvable board goal.
  2. **Goal-gap scoreboard**:
     - Coverage gap: `1.0 - coverage_median`
     - Unknown gap: `n_unknown_median - 0`
     - Runtime gap: `runtime_median - 180s`
     - Show Iter10 baseline, Iter12 value, absolute delta, and status: `Improved / Worse / Unchanged`.
  3. **Board-size interpretation** (`200x125`, `250x156`, `250x250`):
     - One paragraph each: what improved, what worsened, practical impact on solvability.
  4. **Cause mapping (technique -> effect)**:
     - For each new technique, state expected effect, observed effect, and confidence (`high/med/low`).
  5. **Acceptance gate verdict**:
     - Explicit pass/fail by gate with one-line rationale per gate.
- Add source-code attribution inside the same file under **“Source changes that caused the result”**:
  - Compare Iter12 source vs prior iteration baseline for `src/minesweeper_recon/*.py`.
  - Per changed file include:
    - file path
    - concise “what changed”
    - why it was changed
    - which metric(s) it should affect (`coverage`, `n_unknown`, `runtime`, `mean_abs_error`)
    - observed direction in Iter12 results (`helped`, `hurt`, `neutral`, `unclear`)
- Baseline for source attribution:
  - Use the baseline commit associated with the Iter10 primary benchmark artifact.
  - Record exact IDs in `results/iter12/<run_id>/comparison_manifest.json`:
    - `baseline_summary_path`
    - `baseline_commit`
    - `iter12_commit`
    - `comparison_timestamp`
  - If baseline commit cannot be auto-resolved, require explicit manual value in manifest before publishing final comparison.

### Validation and Benchmark
- Run deterministic checks (A-E class) again for new logic: invariants, skip/gate behavior, strict repro parity, board-jobs parity.
- Run standard 3-board x 3-seed matrix in strict-repro deterministic-order mode.
- Evaluate acceptance gates against Iter10 primary baseline first; include Iter11 only as contextual trend.
- Publish two Iter12 explainers:
  - [iter12_scorecard.md](D:/Github/Minesweeper-Draft/results/iter12/iter12_scorecard.md): at-a-glance metric table and gate status.
  - [iter12_what_changed.md](D:/Github/Minesweeper-Draft/results/iter12/iter12_what_changed.md): plain-English interpretation + source attribution.

### Assumptions and Defaults
- `src` is canonical for executable logic; docs folders are not a second codebase.
- Iter12 remains rejected if runtime/coverage gates fail, even if some local metrics improve.
- Runtime fixes must come from reduced work (better pruning/search), not relaxed time budgets.

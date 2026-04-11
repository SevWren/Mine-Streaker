This is the plan proposed by Codex using the Gpt 5.3 Codex model with the input `What Needs To Happen Next (In Order)` from   `D:\Github\Minesweeper-Draft\docs\claude_iteration_13\iter13_diagnostic_digest(ClaudeReviewed).txt`

---

```
 Proposed Plan (Codex)

  ## Iter13 Root-Cause Patch and Staged Validation

  Summary
  - Run targeted C0 verification on 250x156 (300/301/302) before full benchmark.

  Implementation Changes
  - In src/minesweeper_recon/repair_phase2.py:
      - Replace hardcoded scan_unknown_cap = 256.
      - Use dynamic cap driven by unknown count and config ceiling:
      - scan_unknown_cap = min(len(unknown_list), configured_cap) with default configured_cap=512.
  - In src/minesweeper_recon/config.py:
      - Add phase2_scan_unknown_cap: int = 512 to BoardConfig.
  - Fully wire the knob so it’s tunable:
      - Add phase2_scan_unknown_cap to RepairContext in src/minesweeper_recon/models.py.
      - Pass it from board config into Phase2 RepairContext(...) in src/minesweeper_recon/pipeline.py.
  - In src/minesweeper_recon/solver.py:
      - Change subset_cap = 2400 if deadline_s is None else 1200 to subset_cap = 2400.

  Test Plan

  1. Targeted verification first:
  - set PYTHONHASHSEED=0
  - python docs/claude_iteration_13/iter13_regression_diagnostic.py --strict-repro --deterministic-order on --boards
    250x156 --seeds 300 301 302 --conditions C0 --out D:\Github\Minesweeper-Draft\results\iter13\diagnostic_c0
  - Check D:\Github\Minesweeper-Draft\results\iter13\diagnostic_c0\diagnostic_summary.json for
    results.C0.250x156.n_unknown_median < 285.

  2. If targeted check passes, run full matrix:

  - set PYTHONHASHSEED=0
  - python docs/claude_iteration_12/iter12_benchmark_ab.py --strict-repro --deterministic-order on --modes fast
    --boards 200x125 250x156 250x250 --seeds 300 301 302 --out D:\Github\Minesweeper-
    Draft\results\iter13\iter13_win13_ab
  - Evaluate acceptance gates from summary_ab.json (summary_by_mode.fast):
  - coverage non-regression on 200x125 and 250x250
  - n_unknown non-increasing on 200x125 and 250x250
  - mean_abs_error non-increasing on 250x250
  - runtime <180s on 250x250

  Assumptions

  - Default phase2_scan_unknown_cap remains 512.
  - Iter13 remains scoped to root-cause fixes only; adaptive Phase2 controller remains shelved.

```
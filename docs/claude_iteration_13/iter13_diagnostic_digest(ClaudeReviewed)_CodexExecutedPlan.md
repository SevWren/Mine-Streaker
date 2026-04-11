# Iter13 Diagnostic Digest (Claude Reviewed, Codex Executed)

## 1) Objective
Execute the agreed staged Iter13 plan exactly:
1. Apply the primary suspected root-cause fix first (`scan_unknown_cap` behavior in Phase 2).
2. Run targeted C0 verification on `250x156`, seeds `300/301/302`.
3. Use that result to decide whether the secondary solver fix is needed.
4. Apply secondary fix only if needed and re-run the same targeted C0 verification.
5. Run full 3-board x 3-seed benchmark only if targeted confirmation succeeds.

Result storage root used for this execution: `D:\Github\Minesweeper-Draft\results\iter13`

## 2) Executed Plan (What Was Actually Run)
1. Primary fix implemented in Phase 2 scan cap logic.
2. Targeted diagnostic run (C0 only) executed:
   - Boards: `250x156`
   - Seeds: `300 301 302`
   - Out: `D:\Github\Minesweeper-Draft\results\iter13\diagnostic_scan_only`
3. Decision rule evaluation:
   - Targeted confirmation did not succeed (`n_unknown_median` stayed `342`, not `< 285`).
4. Secondary fix implemented (`subset_cap` under deadline).
5. Targeted diagnostic re-run (same C0/board/seeds):
   - Out: `D:\Github\Minesweeper-Draft\results\iter13\diagnostic_scan_plus_solver`
6. Decision rule re-evaluated:
   - Still not recovered (`n_unknown_median` remained `342`).
7. Full benchmark step was intentionally not executed because targeted confirmation gate failed.

## 3) Commands Executed
```powershell
$env:PYTHONHASHSEED='0'; python docs/claude_iteration_13/iter13_regression_diagnostic.py --strict-repro --deterministic-order on --boards 250x156 --seeds 300 301 302 --conditions C0 --out D:\Github\Minesweeper-Draft\results\iter13\diagnostic_scan_only
```

```powershell
$env:PYTHONHASHSEED='0'; python docs/claude_iteration_13/iter13_regression_diagnostic.py --strict-repro --deterministic-order on --boards 250x156 --seeds 300 301 302 --conditions C0 --out D:\Github\Minesweeper-Draft\results\iter13\diagnostic_scan_plus_solver
```

```powershell
python -m py_compile src/minesweeper_recon/repair_phase2.py src/minesweeper_recon/solver.py
```

## 4) Targeted Verification Outcomes
### Scan-only (primary fix only)
- Source: `results\iter13\diagnostic_scan_only\diagnostic_summary.json`
- `coverage_median = 0.9898`
- `n_unknown_median = 342`
- `rt_median = 120.4`

### Scan + solver (primary + secondary)
- Source: `results\iter13\diagnostic_scan_plus_solver\diagnostic_summary.json`
- `coverage_median = 0.9898`
- `n_unknown_median = 342`
- `rt_median = 128.4`

### Decision
- Primary recovery was **not** confirmed independently.
- Adding the secondary solver fix did **not** change median `n_unknown` for targeted C0.
- Therefore the staged plan reached a valid stopping decision before full-matrix benchmark.

## 5) Every File Change Made

### [src/minesweeper_recon/repair_phase2.py](D:/Github/Minesweeper-Draft/src/minesweeper_recon/repair_phase2.py)
Change A (near line 237):
```python
# Before
scan_unknown_cap = 256

# After
scan_unknown_cap = 512
```

Change B (near line 398):
```python
# Before
cap=scan_unknown_cap,

# After
cap=min(len(unknown_list), scan_unknown_cap),
```

Net behavior change:
- The scan cap is now dynamic per outer iteration with a hard ceiling of `512`.
- Example: if `len(unknown_list)=342`, all `342` can be scanned.

### [src/minesweeper_recon/solver.py](D:/Github/Minesweeper-Draft/src/minesweeper_recon/solver.py)
Change C (near line 232):
```python
# Before
subset_cap = 2400 if deadline_s is None else 1200

# After
subset_cap = 2400
```

Net behavior change:
- Solver subset constraint truncation is no longer reduced when a deadline exists.

### [docs/claude_iteration_13/iter13_diagnostic_digest(ClaudeReviewed)_CodexExecutedPlan.md](D:/Github/Minesweeper-Draft/docs/claude_iteration_13/iter13_diagnostic_digest(ClaudeReviewed)_CodexExecutedPlan.md)
Change D:
- Added this execution digest documenting the completed staged plan, results, and full file-change log.

## 6) Artifacts Produced
- `D:\Github\Minesweeper-Draft\results\iter13\diagnostic_scan_only\diagnostic_summary.json`
- `D:\Github\Minesweeper-Draft\results\iter13\diagnostic_scan_only\diagnostic_comparison.csv`
- `D:\Github\Minesweeper-Draft\results\iter13\diagnostic_scan_only\diagnostic_verdict.txt`
- `D:\Github\Minesweeper-Draft\results\iter13\diagnostic_scan_plus_solver\diagnostic_summary.json`
- `D:\Github\Minesweeper-Draft\results\iter13\diagnostic_scan_plus_solver\diagnostic_comparison.csv`
- `D:\Github\Minesweeper-Draft\results\iter13\diagnostic_scan_plus_solver\diagnostic_verdict.txt`

# Iteration 13 Plan: Solver Uncapping & Stagnation Tuning (From Gemini - Unproven)

## 1. Executive Summary
Iteration 12 introduced a quality regression on `250x156` and missed the `250x250` runtime gate (293.3s vs 180s). Initial analysis pointed to Phase 2 stagnation, prompting a highly complex Adaptive Search design. 

However, a deeper code audit revealed that the root cause of Phase 2 stagnation is actually a hidden subset cap in the solver (`subset_cap = 1200` when `deadline_s` is active), which cripples deductive logic during repair evaluations. Furthermore, Phase 2 aborts after just 4 non-improving rounds. 

**This iteration pivots away from architectural bloat.** We will uncap the solver, slightly raise Phase 2 stagnation tolerance, and isolate the Iteration 12 regression with targeted A/B configurations.

## 2. Hypothesis
If we restore the solver's `subset_cap` to 2400 during deadline-bound evaluations and increase Phase 2's `no_improve_outer` limit from 4 to 8, Phase 2 will correctly score and execute complex repair swaps without giving up prematurely. This will recover the `250x156` coverage regression and improve solvability rates with zero architectural complexity.

## 3. Scope of Changes
1. **`solver.py`**: Remove the `if deadline_s is None` penalty on `subset_cap`. Lock it at 2400.
2. **`repair_phase2.py`**: Increase `max_mines` from 16 to 24. Increase `no_improve_outer` abort threshold from 4 to 8.
3. **`repair_phase3.py`**: Inject telemetry to audit how often enumeration actually runs and succeeds.

## 4. Benchmark Strategy
We will run a controlled benchmark that tests the new baseline against Iter12 features:
*   **Run 1 (Baseline Fix):** Iter13 fixes applied, but Iter12 features disabled (`inter_repair_sa_iters=0`, `pattern_breaker_enabled=False`). This isolates if our solver uncapping fixes the fundamental regression.
*   **Run 2 (Combined):** Iter13 fixes applied, with Iter12 features enabled. This checks if ROI-SA and Pattern Breaker are actually beneficial once the solver works correctly.

## 5. Acceptance Gates
1. Coverage non-regression on `200x125` and `250x250`.
2. Recover `250x156` coverage back to Iter10 baseline (`>= 0.9916`).
3. Median `250x250` runtime improves toward the 180s target.
iter13_plan.md (Claude Audit) findings:



# Where the Plan Has Significant Problems


## Problem 1 — The runtime gate is not addressed by the proposed mechanism.

The 250x250 median runtime is 293.3s against a 180s target. That's a 113s deficit — a 63% overshoot. The iter13 plan claims adaptive escalation will reduce runtime "by keeping adaptive widening bounded and selective." But looking at the actual code: the dominant runtime cost is evaluate_edits_batch() → solve_board() calls. The solver itself runs 300 rounds with up to 2,400 constraints and an O(N²) subset propagation inner loop. The adaptive controller changes when Phase 2 widens its search, not how fast each solve is. L0 (narrow) should be faster, but escalation to L2/L3 on hard boards will spend more solve-time, not less. The plan doesn't quantify where the 113s will actually come from, which is a credibility gap that could easily result in another runtime gate failure.
Problem 2 — The 250x156 regression root cause may not be what the plan assumes.
The iter12 plan says the regression came from Phase 2 being "too restrictive." But there's another explanation hiding in the numbers: iter12 ran inter_repair_sa_iters = 400_000 (the default was not zero — it was only disabled for iter11's acceptance decision, but iter12 re-enabled it with ROI focus). If the inter-repair SA was accepted only 22% of the time in iter11 and made no median n_unknown improvement, then iter12's ROI-focused version — which the plan says was accepted at an unspecified rate — may have consumed time budget that was then unavailable to Phase 2. The plan does not show the inter-SA acceptance rate for iter12 specifically. This is a missing diagnostic that could mean iter13's fix targets the wrong bottleneck.


## Problem 3 — The plan adds enormous complexity for uncertain gain.

The APSC involves a 4-level state machine with: escalation/de-escalation logic, multi-cluster partition and anchor allocation by weighted round-robin, per-level cap tuples (hotspot_top_k, radius, delta_shortlist, beam_width, beam_depth, beam_branch, finalist_fullsolve_cap, max_action_candidates — 8 parameters per level = 32 new parameters), a rescue sweep that executes once per board or per stagnation epoch, and 11 new telemetry fields. The project's own working rule #1 is "Make one primary hypothesis change per iteration." This plan makes at minimum 4-5 simultaneous structural changes to Phase 2. If it fails, attribution will be impossible. If it passes on one metric and fails another, untangling cause from effect requires re-running with individual pieces disabled — that's the next two or three iterations just to understand what iter13 did.

## Problem 4 — Phase 3 (enumeration) is being ignored despite being the most direct path to solvable=True.
The project's core objective — never achieved in any iteration — is solvable=True. repair_phase3.py exists and handles the case where n_unknown ≤ 25. But the iter12 data shows n_unknown on 200x125 is likely in the range where Phase 3 could trigger, and the 250x156 regression pushed n_unknown from ~285 to ~342 — well beyond Phase 3's cap. Neither plan discusses whether Phase 3 is actually engaging, what it's producing, or whether its enumeration cap is tuned. This is a silent under-investment in the one component closest to the core goal.

## Problem 5 — The solver's subset propagation cap is a hidden ceiling.
The fast solver caps at subset_cap = 1200 constraints when a deadline is active (which it always is during repair). At 250×250 boards with hundreds of unknowns, there are potentially thousands of constraints. This means the solver is silently truncating its own reasoning during all repair evaluations. Neither iter12 nor iter13 mentions this. If the solver can't fully propagate constraints during repair candidate evaluation, it can't correctly score which swap improves solvability — it will systematically undervalue good moves and Phase 2's stagnation becomes self-fulfilling.

## What Should Actually Be Prioritized

Ranked by expected impact-to-effort ratio:

### Priority 1 — Diagnose the actual iter12 250x156 regression before fixing it. Run a minimal diagnostic: disable only the iter12 changes one at a time (disable ROI-SA, disable pattern-breaker, restore Phase 2 caps to iter10 defaults) and check which single change caused the regression. This takes one benchmark run, costs nothing architecturally, and properly identifies the actual bottleneck. The iter13 plan explicitly states this kind of attribution is required but then skips directly to a full redesign.

### Priority 2 — Fix the solver's deadline-based subset cap. During repair, deadline_s is always set, so subset_cap = 1200 applies. Raising it to match the no-deadline behavior (2400), or removing the distinction entirely since the repair already has its own global deadline, would make every Phase 2 solve more accurate with near-zero code change. This is a one-line fix that could meaningfully reduce n_unknown by allowing the solver to resolve constraints it's currently skipping.

### Priority 3 — Make a targeted, single Phase 2 change, not an adaptive controller. The specific failure mode is: 4 outer iterations without improvement → stagnation exit. The simplest fix is raising the stagnation threshold from 4 to 8-12, and widening max_mines from 16 to 24. This is two parameter changes, fully backward-compatible, zero risk to determinism, and directly addresses the 250x156 pattern where hard pockets are not exhausted in 4 rounds. Measure that first before building a 32-parameter adaptive controller.

### Priority 4 — Audit Phase 3 engagement. Add telemetry for how often Phase 3 actually runs and what it produces. If boards are entering Phase 3's range (n_unknown ≤ 25) but Phase 3 isn't resolving them, that's a solver completeness issue that needs fixing before anything else on the solvability path.

## Summary Verdict

The iter13 plan is targeting a real problem with the wrong solution at the wrong scale. The 250x156 regression and runtime miss are real and need fixing. But the proposed APSC is: too complex to attribute cleanly, adds 32+ new parameters, doesn't credibly explain where the 113s runtime improvement comes from, and ignores two cheaper and higher-impact interventions (solver cap fix, stagnation threshold tuning) that should be tried first.

The plan also violates the project's own working rule of one primary change per iteration, and skips over a direct diagnostic step that would actually confirm  the root cause before prescribing the remedy.

Recommended path: Run a targeted regression-isolation benchmark (one run, ~1 hour), fix the solver deadline subset cap (one line), raise the Phase 2 stagnation threshold (one parameter), and audit Phase 3 engagement — all as a single focused iteration. Only if those changes fail to move the metrics should the adaptive controller be considered, and even then it should be introduced one level at a time.
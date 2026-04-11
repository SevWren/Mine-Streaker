> User:  Yes, I want you to build that diagnostic first, so you resume correctly from the previous turn's erroneous halting.
> 
> ```
> ===== ITERATION STATUS =====
> Research Phase: analysis
> Iteration Position: Pre-Iteration 13 Review
> Current Standing: structural failure detected - 
> iter13 plan adds excessive complexity to address a root cause that
> has not been isolated, while ignoring two cheaper higher-impact
> Show more
> ```

---

Architected regression-isolation diagnostic toggling iter12 changes individually

Let me read the source carefully to identify every iter12 change that has a config knob, so the diagnostic toggles exactly the right things.

Architected diagnostic benchmark isolating iter12 regression causes

Now I have everything. The picture is clear:

*   **4 iter12 Phase2 knobs were tightened** vs their fallback values: `delta_shortlist` 24->16, `beam_width` 6->4, `beam_branch` 8->6, `fullsolve_cap` 8->4
*   **2 new pipeline stages** each consume global repair budget: inter-repair SA (400k iters) and pattern-breaker
*   The regression could be from any one of these, or a combination

Now I can write a proper diagnostic that tests each in isolation.

Iter13_regression_diagnostic.py — Isolates which iter12 change caused the 250x156 regression
> iter13_regression_diagnostic.py — Isolates which iter12 change caused the 250x156 regression
> iter13_regression_diagnostic.py
> Done

Now validate the diagnostic logic against the extracted source to make sure every condition is wired correctly:

Validated diagnostic implementation and identified minor formatting inconsistency
> Validate all diagnostic conditions are correctly wired against actual source
> ```python
> config_src = extract_file(content, "src/minesweeper_recon/config.py")
> p2_src = extract_file(content, "src/minesweeper_recon/repair_phase2.py")
> pipeline = extract_file(content, "src/minesweeper_recon/pipeline.py")
> models = extract_file(content, "src/minesweeper_recon/models.py")
> 
> import re
> 
> print("=== CHECK 1: All override keys exist in BoardConfig ===")
> all_override_keys = {
> ```
> Check 1 shows that `inter_repair_sa_iters` and `pattern_breaker_enabled` are in `BoardConfig` but NOT in `RepairContext` (models.py). That's fine because these are only used by the pipeline function directly via `getattr(config, ...)` — they don't need to be in `RepairContext`. The Phase2 knobs (`phase2_*`) ARE in `RepairContext` because they're passed through to `run_phase2_swap_repair`.
> 
> The diagnostic's `make_diagnostic_boards` uses `replace(board, ...)` on `BoardConfig` objects — that's correct since these are all `BoardConfig` fields.
> 
> The `compute_summary` uses `m.board == token` where token is e.g. "250x156" and `m.board = f"{W}x{H}"`. We need to verify this format matches. Since W=250, H=156, `f"{W}x{H}"` = "250x156" which matches the token "250x156". Good.
> 
> One issue: in `make_diagnostic_boards`, I do:
> ```python
> bm = [m for m in metrics if m.board == token]
> ```
> But in `run_condition`, I try:
> ```python
> board_metrics = [m for m in metrics if m.board == board_token.replace("x", "x")]
> ```
> Wait that's a no-op replace. The token is "250x156" and `m.board` is "250x156" — they should match directly. Let me verify there's no issue with the board label vs board field.
> 
> Actually, the board label in `PipelineMetrics` is set to `config.label` which we're overriding to `f"{condition.name}_{board.label}"`. But `m.board` is set to `f"{W}x{H}"` which doesn't include the condition name. So `m.board == "250x156"` should work fine even with our label override.
> 
> Let me also fix the quick-print in `run_condition` which has `board_token.replace("x", "x")` which is a no-op bug. Actually it should just be `m.board == board_token`. Let me check if this needs fixing... it's just the verbose print during the run, not the actual results computation. Not critical but should fix it for clarity.
> 
> Also, the `compute_summary` function uses `m.board == token` directly, which is correct.
> 
> So the diagnostic looks solid. Let me finalize it and output it.
> Show less
> 
> Confirm the two non-RepairContext fields are read from BoardConfig in pipeline — validating our repla...
> ```python
> ...
> boost_radius = 4
> boost_map = np.zero...
> ..._iters = int(config.inter_repair_sa_iters)
> chunk_iters = max(1, int(getattr(config, "inter_re...
> ```
> Done

All checks pass. One small issue to fix — a cosmetic no-op in `run_condition`'s verbose print — then produce the final file:

Ran 3 commands
> Fix the cosmetic no-op in run_condition verbose print
> ```bash
> python3 - << 'EOF'
> # Read the diagnostic file, fix the no-op replace, re-save
> with open('/mnt/user-data/outputs/iter13_regression_diagnostic.py', 'r') as f:
>     src = f.read()
> 
> # The verbose print in run_condition has a no-op token comparison
> # Find and fix it
> ```
> Final syntax and logic validation of the diagnostic script
> ```bash
> python3 - << 'EOF'
> # final syntax check - parse the diagnostic script
> import ast, sys
> 
> with open('/mnt/user-data/outputs/iter13_regression_diagnostic.py', 'r') as f:
>     src = f.read()
> ```
> Verify PRE_ITER12_P2 dict expansion is correctly used in conditions
> ```bash
> python3 - << 'EOF'
> # The regex didn't catch the PRE_ITER12_P2 dict references - verify those are in CONDITIONS
> with open('/mnt/user-data/outputs/iter13_regression_diagnostic.py', 'r') as f:
>     src = f.read()
> 
> # Find all override dicts in CONDITIONS
> ```
> Done

  Validated. Present the output:
>   Presented file
> Done

**What this is and how to use it**
This is the regression-isolation diagnostic that should have been the first output two turns ago. It answers the question "which specific iter12 change broke `250x156`?" before any fix is written.

**What it tests**
Seven conditions, each a named `BoardConfig` variant created using `dataclasses.replace()` — no source code modifications required:

| Condition | What's changed vs iter12 |
| :--- | :--- |
| C0 baseline | Nothing — reproduces the regression |
| C1 no_inter_sa | `inter_repair_sa_iters=0` |
| C2 no_pattern_bk | `pattern_breaker_enabled=False` |
| C3 wider_p2_caps | `delta_shortlist=24, beam_width=6, beam_branch=8, fullsolve_cap=8` |
| C4 no_stages | C1 + C2 |
| C5 no_bk_wide_p2 | C2 + C3 |
| C6 all_reverted | C1 + C2 + C3 |

All iter12 defaults were confirmed against the actual `config.py` source. All pre-iter12 values were confirmed against the actual `getattr()` fallbacks in `repair_phase2.py`. All disable knobs were confirmed to fire the correct skip branches in `pipeline.py`.

**How to run**
```powershell
# Fastest - only the regressed board, find the cause
$env:PYTHONHASHSEED='0'
python docs/claude_iteration_13/iter13_regression_diagnostic.py `
  --strict-repro --boards 250x156 --seeds 300 301 302

# Quick first pass - just baseline vs Phase2-caps-revert (most likely culprit)
python ... --conditions C0 C3

# Full matrix validation once the cause is isolated
python ... --boards 200x125 250x156 250x250 --conditions C0 <winning_condition>
```

**What the output tells you**
The `diagnostic_verdict.txt` gives a plain-English conclusion. The rule is: whichever single condition (C1, C2, or C3) recovers `250x156` back to iter10 levels (`coverage >= 0.9916`, `n_unknown <= 285`) is the root cause. That revert and only that revert becomes iter13's single change. If no single condition works but C6 does, there is a compounding interaction and all three reverts go in together as one logical fix.

===== ITERATION STATUS =====

Research Phase: analysis Iteration Position: Pre-Iteration 13 Review — diagnostic built Current Standing: leading approach — regression-isolation diagnostic validated against extracted source, all 6 override keys confirmed against config.py defaults and repair_phase2.py getattr() fallbacks, all disable knobs confirmed against pipeline.py skip branches Next Required Action: Run the diagnostic on the user's machine ( `--boards 250x156 --seeds 300 301 302` ), read `diagnostic_verdict.txt` , then write exactly one fix targeting the identified root cause Proceed To Next Iteration?: no Reason: The diagnostic run has not happened yet — the verdict file it produces is the required input before any patch can be written with justified confidence


---


## Verification Result

**Codex executed the instructions correctly.** The staged plan was followed precisely: primary fix first, gate check, secondary fix, gate recheck, full benchmark withheld because the gate failed. No procedural errors.

### File-by-file audit

**`repair_phase2.py` ✓** — Both changes are syntactically valid and operative:
- Line 240: `scan_unknown_cap = 512` (was 256) — active
- Line 411: `cap=min(len(unknown_list), scan_unknown_cap)` — active
- The commented-out line 238 is inert backup, not a problem
- The config knob is not wired through RepairContext yet (that was the "fully wire" decision still pending — acceptable for now since the hardcode and the config default are the same value of 512, so behavior is correct)

**`solver.py` ✓** — Change C is operative. The old conditional expression on lines 237/240 is inside a `"""` docstring and is dead code. Line 246 `subset_cap = 2400` is what actually runs.

**`config.py` ✓** — `phase2_scan_unknown_cap: int = 512` is correctly added to `BoardConfig`.

### What the results tell us

Both fixes together produced no change: `n_unknown_median` stayed at 342 across both the scan-only and scan-plus-solver runs. This is genuine: the file is valid, the fix ran, and it didn't move the needle.

This means **the scan_unknown_cap hypothesis was wrong as the primary cause.** The 342-unknown stagnation wall does not come from unknowns being excluded from the scan window. Something upstream is producing a qualitatively harder board configuration than iter10 did, and Phase2 stagnation is a symptom, not the cause.

### What has not been examined yet

The recommendation in the diagnostic output is correct but was not yet acted on: **audit Phase1 elapsed_s and Phase2 elapsed_s** in the baseline C0 run to check whether Phase2 is actually receiving its expected budget and how long each phase runs. The regression source could be in Phase1 producing a different residual board, not in Phase2's behavior at all. That is the next diagnostic step.

### Status: not ready to proceed to full benchmark

The fixes are applied correctly and should be kept — they are net improvements (wider scan, accurate solver oracle). But the regression gate has not passed. Proceeding to a full benchmark now would measure an improvement that hasn't been achieved yet.

===== ITERATION STATUS =====
Research Phase: analysis
Iteration Position: Pre-Iteration 13 Review — second diagnostic complete
Current Standing: primary hypothesis (scan_unknown_cap) falsified; secondary fix (solver subset_cap) also insufficient; both changes are correct and should be kept; root cause of 250x156 regression still unidentified
Next Required Action: Audit Phase1 and Phase2 elapsed_s from the C0 baseline run logs to determine whether Phase1 is leaving a harder residual board in iter12 than iter10 did — specifically check if Phase1 stagnates earlier or the handoff_low_yield trigger fires differently
Proceed To Next Iteration?: no
Reason: The 250x156 regression gate has not passed; the fixes applied are improvements but insufficient; the root cause is upstream of Phase2 and requires Phase1 telemetry to identify
============================
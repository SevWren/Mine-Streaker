"""
iter13_patches.py
=================
Single-file reference for all Iteration 13 source changes.

PRIMARY HYPOTHESIS
------------------
Phase 2 repair exits too early on hard boards because:

  (A) [Solver oracle is incomplete during repair]
      When deadline_s is active (always true during repair), solver.py
      caps subset propagation at 1200 constraints instead of 2400.
      This means the solver used to *evaluate* each swap candidate
      silently skips half its reasoning. A swap that would resolve a
      pocket looks identical to one that wouldn't — Phase 2 picks
      randomly among them and hits stagnation.

  (B) [Phase 2 exits stagnation too fast]
      Phase 2 declares stagnation after 4 consecutive non-improving
      outer iterations. With iter12's tighter candidate filtering
      (hotspot pruning + small finalist cap), a hard pocket can exhaust
      4 rounds without any candidate making it through to the finalist
      stage. The stagnation counter triggers before the pocket is
      actually exhausted.

  (C) [Phase 2 searches too few mine candidates]
      max_mines = 16 means only the 16 highest-scored mines are
      considered as swap sources. On boards with many unknown clusters
      (250x156 median n_unknown ~285-342), the best swap source may
      rank 17th or 20th. It's never evaluated.

CHANGES — exactly three, fully attributable
-------------------------------------------
1. solver.py          line ~6838   subset_cap: 1200 -> 2400 under deadline
2. repair_phase2.py   stagnation:  no_improve_outer >= 4  -> >= 8
3. repair_phase2.py   mine width:  max_mines = 16         -> 24
   config.py          expose both as named knobs

WHAT IS NOT CHANGED
-------------------
- inter_repair_sa (left at iter12 defaults — ROI-focused, iters=400k)
- pattern_breaker (left at iter12 defaults — enabled)
- hotspot_top_k, delta_shortlist, beam_width/depth/branch (iter12 values kept)
- solver logic beyond the cap line
- corridors, SA kernel, pipeline orchestration
- benchmark schema (additive only — repair3_reason added to metric_keys)

ACCEPTANCE GATES (same as prior iterations)
-------------------------------------------
1. No coverage regression on 200x125 and 250x250 medians vs iter10 baseline
2. n_unknown equal or lower on median
3. mean_abs_error equal or lower at 250x250
4. 250x250 runtime < 180s
5. 250x156 must not regress vs iter10 on coverage AND n_unknown

HOW TO APPLY
------------
Run apply_patches() from this file, or apply each patch manually
to the files in src/minesweeper_recon/.
"""

from __future__ import annotations
import re
from pathlib import Path

REPO_ROOT = Path("D:/Github/Minesweeper-Draft")
SRC = REPO_ROOT / "src" / "minesweeper_recon"


# ──────────────────────────────────────────────────────────────────────────────
# PATCH 1: solver.py — remove deadline-based subset cap reduction
# ──────────────────────────────────────────────────────────────────────────────
# Analogy: during repair, the solver is acting like a detective who
# interviews only half the witnesses when under a time-pressure warning.
# The witnesses are still available — the cap is artificial.
# Removing the deadline discrimination means every solve call during
# repair uses the same completeness as a standalone solve call.
#
# Risk: each solve call takes slightly longer (~5-15% on large boards).
# Benefit: swap candidates are evaluated correctly, not underscored.
# Net: fewer wasted full-solve calls on wrong candidates → net time neutral
#      or negative at board level.

SOLVER_OLD = '            subset_cap = 2400 if deadline_s is None else 1200'
SOLVER_NEW = '            subset_cap = 2400  # iter13: same cap regardless of deadline'


# ──────────────────────────────────────────────────────────────────────────────
# PATCH 2 + 3: repair_phase2.py — stagnation threshold + mine width
# ──────────────────────────────────────────────────────────────────────────────
# Stagnation: 4 rounds → 8 rounds
# Analogy: a lock-picker who gives up after trying 4 combinations when
# the lock has 8 tumblers. The iter12 tighter filters mean each round
# evaluates fewer candidates — so stagnation fires before the search
# space is actually exhausted.
#
# max_mines: 16 → 24
# Analogy: searching for a lost key by only looking in the 16 most
# likely spots, when the correct spot might rank 20th. Slightly wider
# search, same ranking logic.

PHASE2_STAG_OLD = '                if no_improve_outer >= 4:'
PHASE2_STAG_NEW = '                if no_improve_outer >= int(getattr(context, "phase2_stagnation_rounds", 8)):'

PHASE2_MINES_OLD = '    max_mines = 16'
PHASE2_MINES_NEW = '    max_mines = int(getattr(context, "phase2_max_mines", 24))'

# Also widen max_scored_swaps proportionally (was 160 = 16 mines * 10)
PHASE2_SCORED_OLD = '    max_scored_swaps = 160'
PHASE2_SCORED_NEW = '    max_scored_swaps = 240  # iter13: scaled with max_mines'


# ──────────────────────────────────────────────────────────────────────────────
# PATCH 4: config.py — expose new knobs with iter13 defaults
# ──────────────────────────────────────────────────────────────────────────────
# Adding two new BoardConfig fields so the values can be tuned in benchmark
# runs without code edits, and show up in repro fingerprints.

CONFIG_OLD = '    phase2_fullsolve_cap: int = 4'
CONFIG_NEW = (
    '    phase2_fullsolve_cap: int = 4\n'
    '    # iter13: stagnation exit control and mine search width\n'
    '    phase2_stagnation_rounds: int = 8\n'
    '    phase2_max_mines: int = 24'
)


# ──────────────────────────────────────────────────────────────────────────────
# PATCH 5: benchmark_cli.py — add repair3 to metric_keys (observability)
# ──────────────────────────────────────────────────────────────────────────────
# Phase 3 (enumeration) fires when n_unknown <= 25 after phases 1+2.
# It currently produces repair3_reason in every run but that field
# is invisible in summary_ab.json because it's not in metric_keys.
# Adding it gives us the first-ever view of Phase 3 engagement rate.
# repair3_reason is a string (skipped/forced_unique/enum_resolved/...) —
# the summarize_metric path handles strings by converting to float which
# will fail gracefully. We need to handle this separately.
# Solution: add it to reason_counts collection, not metric_keys.

BENCH_REASON_COLLECT_OLD = (
    "    def _collect_reason_counts(metrics) -> dict[str, dict[str, dict[str, int]]]:\n"
    "    out: dict[str, dict[str, dict[str, int]]] = {}\n"
    "    for m in metrics:\n"
    "        board = m.board\n"
    "        out.setdefault(board, {\"repair1_reason\": {}, \"repair2_reason\": {}})\n"
    "        r1 = str(m.repair1_reason)\n"
    "        r2 = str(m.repair2_reason)\n"
    "        out[board][\"repair1_reason\"][r1] = out[board][\"repair1_reason\"].get(r1, 0) + 1\n"
    "        out[board][\"repair2_reason\"][r2] = out[board][\"repair2_reason\"].get(r2, 0) + 1\n"
    "    return out"
)

# Simpler: just patch the reason collection to include repair3
BENCH_REASONS_OLD = '        out.setdefault(board, {"repair1_reason": {}, "repair2_reason": {}})'
BENCH_REASONS_NEW = (
    '        out.setdefault(board, {"repair1_reason": {}, "repair2_reason": {}, "repair3_reason": {}})'
)

BENCH_REASONS_R3_OLD = (
    '        out[board]["repair2_reason"][r2] = out[board]["repair2_reason"].get(r2, 0) + 1\n'
    '    return out'
)
BENCH_REASONS_R3_NEW = (
    '        out[board]["repair2_reason"][r2] = out[board]["repair2_reason"].get(r2, 0) + 1\n'
    '        r3 = str(m.repair3_reason)\n'
    '        out[board]["repair3_reason"][r3] = out[board]["repair3_reason"].get(r3, 0) + 1\n'
    '    return out'
)


# ──────────────────────────────────────────────────────────────────────────────
# APPLICATION
# ──────────────────────────────────────────────────────────────────────────────

def _apply_patch(filepath: Path, old: str, new: str, label: str) -> bool:
    text = filepath.read_text(encoding="utf-8")
    if old not in text:
        print(f"  ✗ PATCH FAILED — pattern not found: {label}")
        print(f"    File: {filepath}")
        print(f"    Looking for: {repr(old[:80])}")
        return False
    count = text.count(old)
    if count > 1:
        print(f"  ⚠ WARNING — pattern found {count} times: {label}")
    patched = text.replace(old, new, 1)
    filepath.write_text(patched, encoding="utf-8")
    print(f"  ✓ {label}")
    return True


def apply_patches(repo_root: Path = REPO_ROOT) -> bool:
    src = repo_root / "src" / "minesweeper_recon"
    ok = True

    print("\n=== Applying Iteration 13 patches ===\n")

    # Patch 1: solver.py
    ok &= _apply_patch(
        src / "solver.py", SOLVER_OLD, SOLVER_NEW,
        "solver.py: remove deadline-based subset cap reduction (1200→2400)"
    )

    # Patch 2: repair_phase2.py stagnation threshold
    ok &= _apply_patch(
        src / "repair_phase2.py", PHASE2_STAG_OLD, PHASE2_STAG_NEW,
        "repair_phase2.py: stagnation threshold 4→8 (config-driven)"
    )

    # Patch 3a: repair_phase2.py max_mines
    ok &= _apply_patch(
        src / "repair_phase2.py", PHASE2_MINES_OLD, PHASE2_MINES_NEW,
        "repair_phase2.py: max_mines 16→24 (config-driven)"
    )

    # Patch 3b: repair_phase2.py max_scored_swaps
    ok &= _apply_patch(
        src / "repair_phase2.py", PHASE2_SCORED_OLD, PHASE2_SCORED_NEW,
        "repair_phase2.py: max_scored_swaps 160→240 (proportional to max_mines)"
    )

    # Patch 4: config.py new knobs
    ok &= _apply_patch(
        src / "config.py", CONFIG_OLD, CONFIG_NEW,
        "config.py: add phase2_stagnation_rounds=8 and phase2_max_mines=24"
    )

    # Patch 5: benchmark_cli.py repair3 reason tracking
    ok &= _apply_patch(
        src / "benchmark_cli.py", BENCH_REASONS_OLD, BENCH_REASONS_NEW,
        "benchmark_cli.py: add repair3_reason to reason_counts collection"
    )
    ok &= _apply_patch(
        src / "benchmark_cli.py", BENCH_REASONS_R3_OLD, BENCH_REASONS_R3_NEW,
        "benchmark_cli.py: populate repair3_reason counts per board"
    )

    # Also wire new config fields through pipeline.py's Phase 2 context
    # The pipeline already uses getattr(config, "phase2_*", default) pattern
    # so new config fields are picked up automatically — no pipeline patch needed.
    # Verify the getattr pattern covers new fields:
    pipeline_path = src / "pipeline.py"
    pipeline_text = pipeline_path.read_text(encoding="utf-8")
    has_stagnation_wire = 'phase2_stagnation_rounds' in pipeline_text
    has_mines_wire = 'phase2_max_mines' in pipeline_text
    if not has_stagnation_wire:
        # Pipeline uses getattr(context, ...) not getattr(config, ...) for phase2 knobs
        # The context is built from config in pipeline, so we need to add the pass-through
        PIPELINE_CTX_OLD = (
            '                phase2_fullsolve_cap=int(getattr(config, "phase2_fullsolve_cap", 8)),\n'
            '            )\n'
            '        )\n'
            '        grid = phase2.grid'
        )
        PIPELINE_CTX_NEW = (
            '                phase2_fullsolve_cap=int(getattr(config, "phase2_fullsolve_cap", 8)),\n'
            '                phase2_stagnation_rounds=int(getattr(config, "phase2_stagnation_rounds", 8)),\n'
            '                phase2_max_mines=int(getattr(config, "phase2_max_mines", 24)),\n'
            '            )\n'
            '        )\n'
            '        grid = phase2.grid'
        )
        ok &= _apply_patch(
            pipeline_path, PIPELINE_CTX_OLD, PIPELINE_CTX_NEW,
            "pipeline.py: pass phase2_stagnation_rounds and phase2_max_mines to RepairContext"
        )

    # And add the fields to RepairContext in models.py
    models_path = src / "models.py"
    models_text = models_path.read_text(encoding="utf-8")
    if 'phase2_stagnation_rounds' not in models_text:
        MODELS_OLD = '    phase2_fullsolve_cap: int = 8'
        MODELS_NEW = (
            '    phase2_fullsolve_cap: int = 8\n'
            '    phase2_stagnation_rounds: int = 8\n'
            '    phase2_max_mines: int = 24'
        )
        ok &= _apply_patch(
            models_path, MODELS_OLD, MODELS_NEW,
            "models.py: add phase2_stagnation_rounds and phase2_max_mines to RepairContext"
        )

    print(f"\n{'All patches applied ✓' if ok else 'Some patches FAILED — check output above'}")
    return ok


def verify_patches(repo_root: Path = REPO_ROOT) -> None:
    """Quick sanity check after patching — read and print the changed lines."""
    src = repo_root / "src" / "minesweeper_recon"
    print("\n=== Verification ===\n")

    for filepath, pattern, label in [
        (src / "solver.py",         "subset_cap",           "solver subset_cap"),
        (src / "repair_phase2.py",  "no_improve_outer >=",  "phase2 stagnation"),
        (src / "repair_phase2.py",  "max_mines",            "phase2 max_mines"),
        (src / "repair_phase2.py",  "max_scored_swaps",     "phase2 scored swaps"),
        (src / "config.py",         "phase2_stagnation",    "config stagnation knob"),
        (src / "config.py",         "phase2_max_mines",     "config max_mines knob"),
        (src / "models.py",         "phase2_stagnation",    "RepairContext stagnation field"),
        (src / "pipeline.py",       "phase2_stagnation",    "pipeline stagnation wire"),
        (src / "benchmark_cli.py",  "repair3_reason",       "benchmark repair3 tracking"),
    ]:
        try:
            text = filepath.read_text(encoding="utf-8")
            for line in text.split('\n'):
                if pattern in line:
                    print(f"  {label}:")
                    print(f"    {line.strip()}")
                    break
            else:
                print(f"  ✗ MISSING: {label} in {filepath.name}")
        except FileNotFoundError:
            print(f"  ✗ FILE NOT FOUND: {filepath}")


if __name__ == "__main__":
    import sys
    if "--verify" in sys.argv:
        verify_patches()
    else:
        ok = apply_patches()
        if ok:
            verify_patches()
        sys.exit(0 if ok else 1)

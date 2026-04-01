# Intrinsic 5x5 Macrotile Minesweeper Art Generator

## Summary
- Build a **standard 8-neighbor Minesweeper** generator. No custom clue rules, no art-overlay trick, no CRF repair pass.
- Encode the image through the **fully solved board’s native clue/mine pattern**, using **5x5 macrotiles of real Minesweeper cells** as the visual construction unit.
- Let the **final board size float**. The generator searches upward over macrotile lattice resolutions until the solved-board rendering reaches the fidelity target.
- Guarantee no-guess play from a **designated start cell** using a fixed **rule-ladder solver** plus **local frontier repair**, then rerun the solver from scratch as the acceptance check.

## Key Changes
- Replace `image -> mine prior -> full-board solve -> repair` with `image -> tile target lattice -> compatible macrotile assembly -> solver replay -> local frontier tile repair -> full replay verification`.
- Define each visual tile as a **5x5 core** of real cells with a **1-cell halo**, so each library entry is modeled as a local `7x7` neighborhood.
- Use the halo to form an exact interface:
  - `north/south/east/west` edge signatures are the mine-state bitmasks on the halo edge adjacent to the `5x5` core.
  - `corner` signatures are the four halo corner mine bits.
  - Adjacent tiles are composable iff shared edge and corner signatures match exactly.
- Generate an offline **TileLibrary**:
  - Sample or search local `7x7` mine neighborhoods.
  - Compute the resulting solved `5x5` core under standard Minesweeper rules.
  - Store `TileSignature`, `core mine mask`, `core clue grid`, rendered preview, density, and visual descriptors.
  - Keep rotations/reflections as explicit variants.
  - Fill sparse signature buckets with targeted CP-SAT search instead of leaving gaps.
- Use a fixed **visual scoring model** against the untouched source image:
  - Derive grayscale, edge map, and gradient orientation from the source as immutable features.
  - For each source patch and candidate tile preview, minimize:
    - `0.55 * edge_chamfer`
    - `0.30 * grayscale_L1`
    - `0.15 * orientation_error`
- Search over increasing lattice sizes:
  - Start coarse.
  - Partition the source into one patch per macrotile.
  - Assemble a full tile layout with exact signature matching using row-wise DP / beam search.
  - Render the solved-board preview.
  - If fidelity is below threshold, retry at a finer lattice.
- Use this exact **rule ladder** for human-solvability certification:
  - `Tier 1`: single-clue saturation and clearance.
  - `Tier 2`: overlapping-neighborhood subset / difference rules.
  - `Tier 3`: connected-frontier invariant extraction on components with at most `25` unknown cells, but only record moves that are fixed in all satisfying assignments.
  - `Tier 4`: total-mine-count reasoning across independent frontier components.
- Add a **frontier-local repair loop** instead of global re-solving:
  - Run the rule-ladder solver from the designated start.
  - If stuck, identify the stalled frontier component.
  - First try swapping affected macrotiles with alternatives that keep the same exterior signatures.
  - If that fails, expand to a `2x2` or `3x3` tile patch and solve a local CP-SAT over tile choices with the outer halo frozen.
  - Objective: create at least one next rule-ladder move while minimizing additional visual loss.
  - Resume solver and repeat.
- Accept a board only if:
  - the replay from the start finishes with no guess step,
  - the final replay uses only the allowed rule tiers,
  - the solved-board preview meets the fidelity threshold.
- Canonical output artifacts:
  - `mine_mask`
  - `clue_grid`
  - `start_cell`
  - `tile_layout`
  - `certificate_steps`
  - `fidelity_report`

## Public Interfaces / Types
- `TileSignature`: edge and corner halo bitmasks.
- `TileEntry`: signature, `5x5` core mine mask, clue grid, preview raster, descriptors.
- `TileLibrary`: indexed lookup by signature and descriptor bucket.
- `RuleStep`: tier, prerequisite cells, deduced cells, explanation payload.
- `Certificate`: ordered `RuleStep[]` from start to solved.
- `FidelityReport`: lattice size, score breakdown, rendered preview, acceptance decision.
- `GeneratorReport`: board metadata, mine count, start cell, certificate, fidelity report.

## Test Plan
- `Tile correctness`
  - Every `TileEntry` must reproduce its stored clue grid exactly from its mine mask plus halo.
  - Rotation/reflection variants must remain valid and keep correct transformed signatures.
- `Composition correctness`
  - Adjacent tiles with matching signatures must yield no clue mismatch across boundaries.
  - Mismatched signatures must be rejected deterministically.
- `Solver certification`
  - Replay must solve accepted boards using only the four allowed tiers.
  - No accepted board may require a branch, probability estimate, or hidden search step outside `Tier 3`.
- `Frontier-locality`
  - Repair must only edit tiles intersecting the stalled frontier patch.
  - Already certified regions must stay unchanged after each repair.
- `Fidelity`
  - Default acceptance metric:
    - line-art mode: `0.6 * edge_F1 + 0.4 * SSIM >= 0.90`
    - grayscale mode: `0.4 * edge_F1 + 0.6 * SSIM >= 0.88`
- `Scale`
  - Large inputs must increase lattice resolution or patch-repair cost, not trigger whole-grid CSP solving.
  - Benchmark that the active reasoning set stays frontier-local even when the final board is large.

## Assumptions
- The source image is **never altered**. Grayscale, edges, and orientations are derived features only.
- Final board size is **not fixed**. The generator is allowed to increase lattice resolution until it hits the fidelity target or a configured compute ceiling.
- If fidelity target is unmet at the compute ceiling, generation fails with diagnostics rather than silently degrading the image.
- “Human solvable” means solvable by the fixed rule ladder above from the designated start cell.
- Difficulty is not a target variable. Mine count and density are emergent from tile choice and solvability constraints.

## References
- [Simon Tatham: Writing a soluble-grid generator for Mines](https://www.chiark.greenend.org.uk/~sgtatham/quasiblog/mines-solver/)
- [Frontier division and independent frontiers in Minesweeper reasoning](https://dspace.jaist.ac.jp/dspace/bitstream/10119/18136/2/paper.pdf)
- [Geometry-agnostic Minesweeper solver README](https://github.com/madewokherd/mines)
- [Wang Tiles for Image and Texture Generation](https://graphics.uni-konstanz.de/publikationen/Cohen2003WangTilesImage/Cohen2003WangTilesImage.pdf)

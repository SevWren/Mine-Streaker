# AGENTS.md

## Purpose

This repository is for building and improving a Minesweeper image-reconstruction pipeline:

1. Convert an input image into a mine layout.
2. Reconstruct the target image through the resulting number field.
3. Maximize logical solvability (minimal or zero guess-required cells).
4. Scale reliably to large boards (at least `250x250`).

## Scope For Agents

Agents should focus on:

- Algorithm and solver improvements
- Runtime/performance improvements
- Reproducible experiment workflows
- Clear reporting of regressions and tradeoffs

Agents should avoid:

- Dumping long conversation history into repo files
- Storing transient audit artifacts as permanent docs
- Mixing experiment logs with instruction files

## Repository Expectations

- `docs/` contains prior artifacts and references.
- `archive/` contains zipped historical outputs.
- Canonical input images for this project are in `D:\Github\Minesweeper\assets\`.
- Use images from `assets/` as the source inputs for Minesweeper reconstruction runs.
- Do not use historical images from `docs/` as primary run inputs unless explicitly requested.
- Keep new executable code in a clear location (for example, `src/` or `experiments/`) instead of scattering scripts in docs folders.
- Keep large generated outputs out of core source paths unless intentionally versioned.

## Working Rules

1. Make one primary hypothesis change per iteration.
2. Keep changes reproducible with fixed seeds.
3. Record exact config and metric outputs for each run.
4. Do not claim improvement from a single seed run.
5. Prefer median performance across seeds for decisions.

## Standard Benchmark Matrix

Run at minimum:

- `200x125`
- `250x156`
- `250x250`

Use at least 3 seeds per configuration.

Report at least:

- `loss_per_cell`
- `mean_abs_error`
- `coverage`
- `n_unknown`
- `mine_accuracy`
- runtime

## Acceptance Gates

A candidate iteration should be accepted only if:

1. No regression in median coverage on `200x125` and `250x250`.
2. `n_unknown` is equal or lower on median.
3. `mean_abs_error` is equal or lower on median at `250x250`.
4. Runtime at `250x250` stays within practical limit (target: `< 180s` on comparable hardware).

## Current Technical Priorities

1. Improve post-repair optimization without coverage collapse.
2. Improve corridor strategy to preserve solvability while raising usable mine density.
3. Reduce remaining unknown-cell pockets (including likely 50/50 structures).
4. Maintain high-scale stability and reproducibility.

## Implementation Hygiene

- Keep functions modular (`preprocess`, `optimize`, `solve`, `repair`, `evaluate`, `render`).
- Add/update tests or validation scripts when changing solver or optimization logic.
- Keep logs concise and machine-parseable where possible.
- Prefer explicit failure messages over silent fallbacks.

## Decision Rule

When metrics conflict, prioritize:

1. deterministic solvability/coverage stability
2. reproducibility across seeds
3. visual fidelity metrics

Do not trade large coverage regressions for small loss improvements.

# Iteration 10 Run Tutorial (Windows)

This guide explains:

- what each script is for,
- why you would use it,
- how each one works,
- every supported flag and mode,
- and what output you should expect.

## 1) Which script should I run?

### `iter10_win10.py`
Use this for a normal single pipeline run.

- Why: you want results now (images, grids, metrics) for one solver mode.
- What it does: runs the Iteration 10 reconstruction pipeline end-to-end.
- Typical use: daily development and quick checks.

### `iter10_benchmark_ab.py`
Use this for benchmark comparisons (A/B).

- Why: you want to compare `legacy` vs `fast` and check acceptance gates.
- What it does: runs many jobs across modes/seeds/boards, then writes summary reports.
- Typical use: formal performance/regression decisions.

## 2) Basic commands

Run from `D:\Github\Minesweeper-Draft\docs\claude_iteration_10`:

```powershell
python iter10_win10.py
```

```powershell
python iter10_benchmark_ab.py
```

## 3) Full parameter reference

## `iter10_win10.py` parameters

From `--help`:

- `--img IMG`
  - Input image path.
  - Default: `assets/input_source_image-left.png` (resolved from repo root).
- `--out OUT`
  - Output directory.
  - Default: `results/iter10_win10`.
- `--solver-mode {legacy,fast}`
  - Solver implementation.
  - Default: `fast`.
- `--deterministic-order {auto,on,off}`
  - `auto`: deterministic ordering follows strict-repro setting.
  - `on`: always deterministic ordering.
  - `off`: disable deterministic ordering (faster, less reproducible).
  - Default: `auto`.
- `--strict-repro`
  - Enforce strict same-machine reproducibility checks.
  - Default behavior.
- `--no-strict-repro`
  - Disable strict reproducibility checks.
- `--board-jobs BOARD_JOBS`
  - Number of parallel worker processes for board execution.
  - Default: `1`.

### `iter10_win10.py` mode examples

Fast mode (default):

```powershell
python iter10_win10.py --solver-mode fast
```

Legacy mode:

```powershell
python iter10_win10.py --solver-mode legacy
```

Strict reproducible run:

```powershell
python iter10_win10.py --strict-repro
```

Non-strict run:

```powershell
python iter10_win10.py --no-strict-repro
```

Parallel board run:

```powershell
python iter10_win10.py --board-jobs 2 --no-strict-repro --deterministic-order off
```

Deterministic ordering explicitly on/off:

```powershell
python iter10_win10.py --deterministic-order on
python iter10_win10.py --deterministic-order off --no-strict-repro
```

Custom image and output:

```powershell
python iter10_win10.py --img D:\Github\Minesweeper-Draft\assets\input_source_image-left.png --out D:\Github\Minesweeper-Draft\results\iter10_custom
```

## `iter10_benchmark_ab.py` parameters

From `--help`:

- `--img IMG`
  - Input image path.
- `--out OUT`
  - Output root directory.
- `--modes {legacy,fast} [{legacy,fast} ...]`
  - One or both modes to run.
  - Default: `legacy fast`.
- `--seeds SEEDS [SEEDS ...]`
  - One or more random seeds.
  - Default: `300 301 302`.
- `--boards BOARDS [BOARDS ...]`
  - Board tokens like `200x125`.
  - Default: `200x125 250x156 250x250`.
- `--deterministic-order {auto,on,off}`
  - Same meaning as in `iter10_win10.py`.
- `--strict-repro`
  - Strict reproducibility enabled (default).
- `--no-strict-repro`
  - Disable strict reproducibility checks.
- `--repair-global-cap-s REPAIR_GLOBAL_CAP_S`
  - Optional override for combined Phase1+Phase2 repair cap (seconds).
- `--jobs JOBS`
  - Number of parallel worker processes for benchmark tasks.
  - Default: `1`.
- `--failure-policy {fail_fast,continue}`
  - Worker failure behavior in parallel mode.
  - `fail_fast` aborts on first failed task.
  - `continue` records failed tasks and continues remaining tasks.
- `--verbose`
  - Turn on verbose pipeline logs.

### `iter10_benchmark_ab.py` mode examples

Default A/B matrix:

```powershell
python iter10_benchmark_ab.py
```

Fast-only benchmark:

```powershell
python iter10_benchmark_ab.py --modes fast
```

Legacy-only benchmark:

```powershell
python iter10_benchmark_ab.py --modes legacy
```

Custom seeds + boards:

```powershell
python iter10_benchmark_ab.py --modes legacy fast --boards 200x125 250x250 --seeds 300 301 302
```

Strict deterministic benchmark:

```powershell
python iter10_benchmark_ab.py --strict-repro --deterministic-order on
```

Non-strict faster benchmark:

```powershell
python iter10_benchmark_ab.py --no-strict-repro --deterministic-order off
```

Parallel benchmark run:

```powershell
python iter10_benchmark_ab.py --jobs 4 --failure-policy fail_fast --no-strict-repro --deterministic-order off
```

Apply a global repair cap:

```powershell
python iter10_benchmark_ab.py --repair-global-cap-s 120
```

Verbose logs:

```powershell
python iter10_benchmark_ab.py --verbose
```

## 4) What output should I expect?

## `iter10_win10.py` output

You get per-board artifacts, for example:

- final image render (`iter10_*_FINAL.png`)
- saved arrays (`grid_*_FINAL.npy`, `target_*_FINAL.npy`)
- metrics JSON (`metrics_*_FINAL.json`)

If you use default output root, runs are separated by solver mode:

- `...\results\iter10_win10\fast\...`
- `...\results\iter10_win10\legacy\...`

## `iter10_benchmark_ab.py` output

You get:

- per-run artifacts under each mode folder, plus
- benchmark summaries at output root:
  - `summary_ab.json`
  - `summary_ab.csv`

The summary includes per-board/per-mode medians and gate results.

## 5) How strict reproducibility behaves

By default, both scripts run in strict repro mode.

- If `PYTHONHASHSEED` is not `0`, the script auto-relaunches itself with `PYTHONHASHSEED=0`.
- You will see a log line that shows the relaunch command.
- Thread-control env vars are also pinned for deterministic behavior in strict mode.

Use `--no-strict-repro` if you want to skip strict enforcement.

## 6) In plain terms: how each script works internally

### `iter10_win10.py` flow

1. Parse CLI options.
2. Resolve image/output paths.
3. Run preflight checks (dependencies, image, output path, strict repro).
4. Compile SA kernel.
5. Run board pipeline (optimize -> solve -> repair phases -> render/report).
6. Save artifacts and print summary metrics.

### `iter10_benchmark_ab.py` flow

1. Parse benchmark options (modes/seeds/boards/etc.).
2. Run same preflight checks.
3. For each requested mode:
   - run full experiment set for all requested boards/seeds,
   - collect run metrics.
4. Build aggregated summaries.
5. Evaluate acceptance gates when both `legacy` and `fast` are present.
6. Write `summary_ab.json` and `summary_ab.csv`.

## 7) Quick recommendations

- Use `iter10_win10.py` while actively tuning code.
- Use `iter10_benchmark_ab.py` before deciding if a change should be accepted.
- Keep strict repro on for forensic comparisons.
- Use at least 3 seeds for conclusions.

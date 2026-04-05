# Iteration 12 Mirror: `minesweeper_recon` File Responsibility Map

Mirror copy of:
`D:/Github/Minesweeper-Draft/src/minesweeper_recon/FILE_ROLE_MAP.md`

## Package API / Entrypoints

| File | Primary responsibility | Main outputs |
|---|---|---|
| `__init__.py` | Public package exports and lazy entrypoint wrappers. | `run_board`, `run_experiment`, `solve_board` |
| `preflight.py` | CLI argument parsing, dependency checks, strict-repro enforcement, output path validation. | validated runtime environment |
| `pipeline.py` | End-to-end board pipeline orchestration (SA, repair phases, solve, metrics, artifact saves). | `PipelineMetrics`, saved board artifacts |
| `benchmark_cli.py` | Benchmark matrix CLI orchestration, per-mode runs, JSON/CSV summary emission. | `summary_ab.json`, `summary_ab.csv` |
| `benchmark.py` | Benchmark matrix construction, metric summarization, acceptance-gate evaluation. | grouped board summaries and gate verdicts |

## Data Models and Runtime Contracts

| File | Primary responsibility | Main outputs |
|---|---|---|
| `config.py` | Dataclass configs for paths, runtime, board-level knobs, and defaults. | `PathsConfig`, `BoardConfig`, `RunConfig` |
| `models.py` | Typed data contracts for solve results, repair context/results, and pipeline metrics. | `SolveResult`, `RepairContext`, `PipelineMetrics` |
| `runtime.py` | Shared runtime exceptions, deadline helpers, reproducibility fingerprinting. | `BudgetExceeded`, `check_deadline`, `build_repro_fingerprint` |

## Core Numeric/Board Logic

| File | Primary responsibility | Main outputs |
|---|---|---|
| `core.py` | Board math primitives: neighborhood counts, weights, image load, board validity checks. | `compute_N`, `compute_edge_weights`, `assert_board_valid` |
| `sa.py` | Numba SA kernel compilation and warmup/heartbeat management. | compiled SA kernel callable |
| `solver.py` | Logical Minesweeper solver (legacy + fast modes) with deterministic ordering hooks. | `SolveResult` from `solve_board` |
| `corridors.py` | Adaptive corridor mask generation to enforce forbidden mine regions. | `forbidden` mask + corridor stats |

## Repair Stages

| File | Primary responsibility | Main outputs |
|---|---|---|
| `repair_phase1.py` | Mine-removal repair near unresolved frontier with prefilter + solve loop. | Phase1 `RepairResult` and telemetry |
| `repair_phase2.py` | Mine-swap/removal repair search with candidate pruning and solve-backed acceptance. | Phase2 `RepairResult` and telemetry |
| `repair_phase3.py` | Enumeration fallback for low-unknown states (bounded brute-force). | Phase3 `RepairResult` |
| `repair_prefilter.py` | Local forcing-potential scoring helper used to prefilter repair candidates. | integer forcing score |

## Parallelism, Diagnostics, I/O, Reporting

| File | Primary responsibility | Main outputs |
|---|---|---|
| `parallel_eval.py` | Multiprocess candidate evaluation for repair phases using spawned workers. | batched candidate solve results + perf stats |
| `diagnostics.py` | Unknown-cell diagnostics and neighborhood analysis for stage logging. | console diagnostics |
| `report.py` | Render final visual report image (target/reconstruction/history overlays). | final PNG report artifact |
| `io_utils.py` | Atomic JSON/NPY writes to prevent partial artifact corruption. | atomically saved files |


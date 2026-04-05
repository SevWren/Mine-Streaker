from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional


def default_repo_root() -> Path:
    # src/minesweeper_recon/config.py -> repo root is two parents up.
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PathsConfig:
    repo_root: Path = field(default_factory=default_repo_root)
    img: Path = field(default_factory=lambda: default_repo_root() / "assets" / "input_source_image-left.png")
    out_dir: Path = field(default_factory=lambda: default_repo_root() / "results" / "iter12" / "iter12_win12")


@dataclass(frozen=True)
class BoardConfig:
    width: int
    height: int
    label: str
    density: float
    border: int
    seed: int
    coarse_iters: int
    fine_iters: int
    refine_iters: int
    T_fine: float
    T_refine: float
    repair1_budget_s: Optional[float]
    repair2_budget_s: float
    repair3_max_unknown: int
    inter_repair_sa_iters: int = 1_000_000
    inter_repair_sa_T: float = 1.0
    inter_repair_sa_max_unknown: int = 500
    inter_repair_sa_roi_ring: int = 4
    inter_repair_sa_chunk_iters: int = 200_000
    pattern_breaker_enabled: bool = True
    pattern_breaker_max_evals: int = 12
    pattern_breaker_cluster_cap: int = 12
    phase2_hotspot_top_k: int = 6
    phase2_hotspot_radius: int = 6
    phase2_delta_shortlist: int = 24
    phase2_beam_width: int = 6
    phase2_beam_depth: int = 2
    phase2_beam_branch: int = 8
    phase2_fullsolve_cap: int = 8


@dataclass(frozen=True)
class RuntimeConfig:
    paths: PathsConfig = field(default_factory=PathsConfig)
    verbose: bool = True
    solver_mode: Literal["legacy", "fast"] = "fast"
    strict_repro: bool = True
    deterministic_order: Literal["auto", "on", "off"] = "auto"
    repair_global_cap_s: Optional[float] = None
    board_jobs: int = 1
    benchmark_jobs: int = 1
    repair_eval_jobs: int = 1
    repair_eval_batch_size: int = 0
    failure_policy: Literal["fail_fast", "continue"] = "fail_fast"


@dataclass(frozen=True)
class RunConfig:
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    boards: list[BoardConfig] = field(default_factory=list)


def default_boards() -> list[BoardConfig]:
    return [
        BoardConfig(
            width=200,
            height=125,
            label="200x125",
            density=0.22,
            border=3,
            seed=300,
            coarse_iters=1_500_000,
            fine_iters=4_000_000,
            refine_iters=5_000_000,
            T_fine=2.5,
            T_refine=1.5,
            repair1_budget_s=None,
            repair2_budget_s=150.0,
            repair3_max_unknown=25,
        ),
        BoardConfig(
            width=300,
            height=187,
            label="300x187",
            density=0.21,
            border=3,
            seed=301,
            coarse_iters=1_500_000,
            fine_iters=4_000_000,
            refine_iters=5_000_000,
            T_fine=2.5,
            T_refine=1.5,
            repair1_budget_s=None,
            repair2_budget_s=180.0,
            repair3_max_unknown=25,
        ),
    ]


def default_run_config(
    paths: PathsConfig | None = None,
    verbose: bool = True,
    solver_mode: Literal["legacy", "fast"] = "fast",
    strict_repro: bool = True,
    deterministic_order: Literal["auto", "on", "off"] = "auto",
    board_jobs: int = 1,
    repair_eval_jobs: int = 1,
) -> RunConfig:
    runtime = RuntimeConfig(
        paths=paths or PathsConfig(),
        verbose=verbose,
        solver_mode=solver_mode,
        strict_repro=strict_repro,
        deterministic_order=deterministic_order,
        board_jobs=max(1, int(board_jobs)),
        repair_eval_jobs=max(1, int(repair_eval_jobs)),
    )
    return RunConfig(runtime=runtime, boards=default_boards())

from __future__ import annotations

from statistics import median

from .config import BoardConfig, RunConfig, RuntimeConfig
from .pipeline import run_board


def build_standard_matrix(seeds: list[int] | None = None) -> list[BoardConfig]:
    seeds = seeds or [300, 301, 302]
    templates = [
        (200, 125, 0.22, 3),
        (250, 156, 0.22, 3),
        (250, 250, 0.21, 3),
    ]
    boards: list[BoardConfig] = []
    for w, h, density, border in templates:
        for seed in seeds:
            boards.append(
                BoardConfig(
                    width=w,
                    height=h,
                    label=f"{w}x{h}_seed{seed}",
                    density=density,
                    border=border,
                    seed=seed,
                    coarse_iters=1_500_000,
                    fine_iters=4_000_000,
                    refine_iters=5_000_000,
                    T_fine=2.5,
                    T_refine=1.5,
                    repair1_budget_s=None,
                    repair2_budget_s=150.0,
                    repair3_max_unknown=25,
                )
            )
    return boards


def run_benchmark_matrix(config: RunConfig, boards: list[BoardConfig] | None = None):
    runtime = RuntimeConfig(paths=config.runtime.paths, verbose=config.runtime.verbose)
    work_boards = boards or config.boards
    metrics = [run_board(board, runtime) for board in work_boards]
    return metrics


def summarize_metric(maps, key: str):
    vals = [m.to_dict()[key] for m in maps]
    return {"median": median(vals), "min": min(vals), "max": max(vals), "n": len(vals)}

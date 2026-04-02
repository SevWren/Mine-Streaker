from .config import BoardConfig, PathsConfig, RunConfig, RuntimeConfig, default_boards, default_run_config


def run_board(*args, **kwargs):
    from .pipeline import run_board as _run_board

    return _run_board(*args, **kwargs)


def run_experiment(*args, **kwargs):
    from .pipeline import run_experiment as _run_experiment

    return _run_experiment(*args, **kwargs)


def solve_board(*args, **kwargs):
    from .solver import solve_board as _solve_board

    return _solve_board(*args, **kwargs)

__all__ = [
    "BoardConfig",
    "PathsConfig",
    "RunConfig",
    "RuntimeConfig",
    "default_boards",
    "default_run_config",
    "run_board",
    "run_experiment",
    "solve_board",
]

from __future__ import annotations

import time


class BudgetExceeded(RuntimeError):
    pass


class ConfigError(RuntimeError):
    pass


class DependencyError(RuntimeError):
    pass


class OutputError(RuntimeError):
    pass


def now_s() -> float:
    return time.perf_counter()


def check_deadline(deadline_s: float | None, context: str) -> None:
    if deadline_s is not None and now_s() >= deadline_s:
        raise BudgetExceeded(f"{context} deadline exceeded")

from __future__ import annotations

import importlib
import os
import platform
import sys
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


def _module_version(module_name: str, fallback: str = "missing") -> str:
    try:
        mod = importlib.import_module(module_name)
    except Exception:
        return fallback
    return str(getattr(mod, "__version__", "unknown"))


def build_repro_fingerprint(*, solver_mode: str, strict_repro: bool, deterministic_order: str = "auto") -> str:
    py_ver = ".".join(map(str, sys.version_info[:3]))
    pyhash = os.environ.get("PYTHONHASHSEED", "")
    omp = os.environ.get("OMP_NUM_THREADS", "")
    mkl = os.environ.get("MKL_NUM_THREADS", "")
    openblas = os.environ.get("OPENBLAS_NUM_THREADS", "")
    numba_threads = os.environ.get("NUMBA_NUM_THREADS", "")
    parts = [
        f"platform={platform.platform()}",
        f"python={py_ver}",
        f"solver_mode={solver_mode}",
        f"strict_repro={int(bool(strict_repro))}",
        f"deterministic_order={deterministic_order}",
        f"PYTHONHASHSEED={pyhash}",
        f"OMP_NUM_THREADS={omp}",
        f"MKL_NUM_THREADS={mkl}",
        f"OPENBLAS_NUM_THREADS={openblas}",
        f"NUMBA_NUM_THREADS={numba_threads}",
        f"numpy={_module_version('numpy')}",
        f"scipy={_module_version('scipy')}",
        f"numba={_module_version('numba')}",
        f"Pillow={_module_version('PIL')}",
        f"matplotlib={_module_version('matplotlib')}",
    ]
    return "|".join(parts)

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from .config import PathsConfig
from .runtime import ConfigError, DependencyError, OutputError

PINNED_INSTALLS = {
    "numba": "numba==0.65.0",
    "matplotlib": "matplotlib==3.10.8",
}

REQUIRED_MODULES = [
    ("numpy", "numpy"),
    ("scipy", "scipy"),
    ("numba", "numba"),
    ("PIL", "Pillow"),
    ("matplotlib", "matplotlib"),
]

STRICT_REPRO_ENV_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMBA_NUM_THREADS",
)
STRICT_REEXEC_MARKER = "MSR_STRICT_REEXEC"


def _ps_quote(token: str) -> str:
    return "'" + token.replace("'", "''") + "'"


def parse_args(defaults: PathsConfig, argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Iteration 10 Minesweeper reconstruction pipeline (Windows 10 compatible)."
    )
    parser.add_argument(
        "--img",
        default=str(defaults.img),
        help="Path to source input image (default: assets/input_source_image-left.png).",
    )
    parser.add_argument(
        "--out",
        default=str(defaults.out_dir),
        help="Directory for output artifacts (default: results/iter10_win10).",
    )
    parser.add_argument(
        "--solver-mode",
        choices=("legacy", "fast"),
        default="fast",
        help="Solver implementation for A/B comparison (default: fast).",
    )
    parser.add_argument(
        "--deterministic-order",
        choices=("auto", "on", "off"),
        default="auto",
        help="Deterministic ordering policy for solver internals (default: auto).",
    )
    strict_group = parser.add_mutually_exclusive_group()
    strict_group.add_argument(
        "--strict-repro",
        dest="strict_repro",
        action="store_true",
        help="Require strict same-machine reproducibility checks (default).",
    )
    strict_group.add_argument(
        "--no-strict-repro",
        dest="strict_repro",
        action="store_false",
        help="Disable strict reproducibility enforcement.",
    )
    parser.set_defaults(strict_repro=True)
    parser.add_argument(
        "--board-jobs",
        type=int,
        default=1,
        help="Number of parallel board workers for iter10_win10 pipeline (default: 1).",
    )
    return parser.parse_args(argv)


def resolve_paths(args: argparse.Namespace, defaults: PathsConfig) -> PathsConfig:
    repo_root = defaults.repo_root
    img = Path(args.img).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    return PathsConfig(repo_root=repo_root, img=img, out_dir=out_dir)


def maybe_reexec_with_strict_repro(
    strict_repro: bool,
    script_path: Path,
    argv: list[str] | None = None,
    python_executable: Path | None = None,
) -> int | None:
    """
    If strict reproducibility is requested but PYTHONHASHSEED is not 0, relaunch
    the same command with PYTHONHASHSEED=0 and return the child exit code.
    Returns None when no relaunch was needed (or relaunch failed to start).
    """
    if not strict_repro:
        return None
    if os.environ.get("PYTHONHASHSEED") == "0":
        return None
    if os.environ.get(STRICT_REEXEC_MARKER) == "1":
        return None

    exe = str((python_executable or Path(sys.executable)).resolve())
    args = argv or []
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    env[STRICT_REEXEC_MARKER] = "1"

    cmd = [exe, str(script_path), *args]
    cmdline = subprocess.list2cmdline(cmd)
    print("INFO: strict reproducibility enabled; relaunching with PYTHONHASHSEED=0", flush=True)
    print(f"INFO: relaunch command: {cmdline}", flush=True)
    try:
        return subprocess.call(cmd, env=env)
    except OSError:
        return None


def enforce_strict_repro_or_raise(
    strict_repro: bool,
    script_path: Path,
    argv: list[str] | None = None,
    python_executable: Path | None = None,
) -> None:
    if not strict_repro:
        return

    pyhash = os.environ.get("PYTHONHASHSEED")
    if pyhash != "0":
        args = argv or []
        exe = str((python_executable or Path(sys.executable)).resolve())
        cmdline = subprocess.list2cmdline([exe, str(script_path), *args])
        # Build PowerShell-safe command with explicit executable + args.
        ps_tokens = [exe, str(script_path), *args]
        ps_cmd = "$env:PYTHONHASHSEED='0'; & " + " ".join(_ps_quote(token) for token in ps_tokens)
        raise ConfigError(
            "Strict reproducibility requires PYTHONHASHSEED=0.\n"
            "Rerun commands:\n"
            f"  PowerShell: {ps_cmd}\n"
            f"  cmd.exe: set PYTHONHASHSEED=0 && {cmdline}"
        )

    for env_key in STRICT_REPRO_ENV_VARS:
        os.environ[env_key] = "1"


def validate_image_path(path: Path) -> None:
    if not path.exists():
        raise ConfigError(f"Input image does not exist: {path}")
    if not path.is_file():
        raise ConfigError(f"Input image path is not a file: {path}")
    try:
        from PIL import Image as PILImage

        with PILImage.open(path) as img:
            img.verify()
    except Exception as exc:
        raise ConfigError(f"Input image is not readable: {path} ({type(exc).__name__}: {exc})") from exc


def check_required_modules_or_raise() -> None:
    missing: list[tuple[str, str]] = []
    for module_name, package_name in REQUIRED_MODULES:
        if importlib.util.find_spec(module_name) is None:
            missing.append((module_name, package_name))

    if not missing:
        return

    lines = ["Missing required Python modules:"]
    for module_name, package_name in missing:
        lines.append(f"  - import '{module_name}' (package '{package_name}')")

    pinned = [PINNED_INSTALLS[p] for _, p in missing if p in PINNED_INSTALLS]
    if pinned:
        cmd = "python -m pip install " + " ".join(pinned)
    else:
        pkgs = " ".join(sorted({package_name for _, package_name in missing}))
        cmd = f"python -m pip install {pkgs}"
    lines.append("")
    lines.append("Install command:")
    lines.append(f"  {cmd}")
    raise DependencyError("\n".join(lines))


def configure_mplconfigdir() -> None:
    if os.environ.get("MPLCONFIGDIR"):
        return
    try:
        base = Path(os.getenv("LOCALAPPDATA", str(Path.home())))
        mpl_dir = base / "MinesweeperDraft" / "mplconfig"
        mpl_dir.mkdir(parents=True, exist_ok=True)
        os.environ["MPLCONFIGDIR"] = str(mpl_dir)
    except Exception:
        # Best effort; matplotlib can still use fallback temp location.
        return


def ensure_output_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise OutputError(f"Unable to create output directory: {path} ({type(exc).__name__}: {exc})") from exc

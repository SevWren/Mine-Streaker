from __future__ import annotations

import argparse
import importlib.util
import os
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
    return parser.parse_args(argv)


def resolve_paths(args: argparse.Namespace, defaults: PathsConfig) -> PathsConfig:
    repo_root = defaults.repo_root
    img = Path(args.img).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    return PathsConfig(repo_root=repo_root, img=img, out_dir=out_dir)


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

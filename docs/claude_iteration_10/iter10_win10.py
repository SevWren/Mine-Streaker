from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2] if len(SCRIPT_PATH.parents) >= 3 else SCRIPT_PATH.parent
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from minesweeper_recon.config import PathsConfig, default_run_config
from minesweeper_recon.preflight import (
    check_required_modules_or_raise,
    configure_mplconfigdir,
    ensure_output_dir,
    parse_args,
    resolve_paths,
    validate_image_path,
)
from minesweeper_recon.runtime import ConfigError, DependencyError, OutputError


def main(argv=None) -> int:
    defaults = PathsConfig(
        repo_root=REPO_ROOT,
        img=REPO_ROOT / "assets" / "input_source_image-left.png",
        out_dir=REPO_ROOT / "results" / "iter10_win10",
    )

    try:
        args = parse_args(defaults, argv=argv)
        paths = resolve_paths(args, defaults)
        check_required_modules_or_raise()
        validate_image_path(paths.img)
        configure_mplconfigdir()
        ensure_output_dir(paths.out_dir)

        from minesweeper_recon.pipeline import run_experiment

        run_config = default_run_config(paths=paths, verbose=True)
        run_experiment(run_config)
        return 0
    except DependencyError as exc:
        print(f"ERROR: {exc}")
        return 2
    except ConfigError as exc:
        print(f"ERROR: {exc}")
        return 3
    except OutputError as exc:
        print(f"ERROR: {exc}")
        return 4
    except KeyboardInterrupt:
        print("ERROR: Interrupted by user")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

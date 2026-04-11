"""
iter13_win13.py
===============
Single-board runner for Iteration 13.

Usage (PowerShell, from repo root):
    $env:PYTHONHASHSEED='0'
    python docs/claude_iteration_13/iter13_win13.py --strict-repro

Iteration 13 primary hypothesis:
    Phase 2 repair exits too early on hard boards because
    (A) the solver silently halves its subset propagation cap during
        deadline-bounded repair evaluations, causing it to underrate
        valid swap candidates, and
    (B) the stagnation exit window (4 outer rounds) is too narrow after
        iter12's tighter candidate filtering, meaning hard 50/50 pockets
        are not exhausted before Phase 2 quits.

Changes vs iter12 baseline:
    solver.py           subset_cap: 1200 (deadline) -> 2400 always
    repair_phase2.py    no_improve_outer >= 4       -> >= 8 (config-driven)
    repair_phase2.py    max_mines = 16              -> 24   (config-driven)
    repair_phase2.py    max_scored_swaps = 160      -> 240  (proportional)
    config.py           +phase2_stagnation_rounds=8, +phase2_max_mines=24
    models.py           +phase2_stagnation_rounds, +phase2_max_mines in RepairContext
    pipeline.py         wire new fields into Phase 2 RepairContext
    benchmark_cli.py    +repair3_reason in reason_counts (observability)
"""

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
    enforce_strict_repro_or_raise,
    ensure_output_dir,
    maybe_reexec_with_strict_repro,
    parse_args,
    resolve_paths,
    validate_image_path,
)
from minesweeper_recon.runtime import ConfigError, DependencyError, OutputError


def main(argv=None) -> int:
    defaults = PathsConfig(
        repo_root=REPO_ROOT,
        img=REPO_ROOT / "assets" / "input_source_image-left.png",
        out_dir=REPO_ROOT / "results" / "iter13" / "iter13_win13",
    )

    try:
        raw_argv = list(argv) if argv is not None else sys.argv[1:]
        args = parse_args(defaults, argv=argv)
        paths = resolve_paths(args, defaults)
        strict_repro = bool(args.strict_repro)
        reexec_code = maybe_reexec_with_strict_repro(
            strict_repro=strict_repro,
            script_path=SCRIPT_PATH,
            argv=raw_argv,
            python_executable=Path(sys.executable),
        )
        if reexec_code is not None:
            return int(reexec_code)
        enforce_strict_repro_or_raise(
            strict_repro=strict_repro,
            script_path=SCRIPT_PATH,
            argv=raw_argv,
            python_executable=Path(sys.executable),
        )
        if int(args.board_jobs) < 1:
            raise ConfigError(f"--board-jobs must be >= 1 (got {args.board_jobs})")
        if int(args.repair_eval_jobs) < 1:
            raise ConfigError(f"--repair-eval-jobs must be >= 1 (got {args.repair_eval_jobs})")

        # Nest under solver_mode so A/B results don't overwrite each other
        if paths.out_dir == defaults.out_dir.resolve():
            paths = PathsConfig(
                repo_root=paths.repo_root,
                img=paths.img,
                out_dir=paths.out_dir / args.solver_mode,
            )

        check_required_modules_or_raise()
        validate_image_path(paths.img)
        configure_mplconfigdir()
        ensure_output_dir(paths.out_dir)

        from minesweeper_recon.pipeline import run_experiment

        run_config = default_run_config(
            paths=paths,
            verbose=True,
            solver_mode=args.solver_mode,
            strict_repro=strict_repro,
            deterministic_order=args.deterministic_order,
            board_jobs=int(args.board_jobs),
            repair_eval_jobs=int(args.repair_eval_jobs),
        )
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

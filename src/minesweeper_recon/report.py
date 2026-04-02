from __future__ import annotations

import numpy as np

from .core import compute_N
from .models import SolveResult
from .preflight import configure_mplconfigdir

configure_mplconfigdir()
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def render_report(target, grid, sr: SolveResult, history, title, save_path, dpi=120):
    N = compute_N(grid)
    H, W = grid.shape
    err = np.abs(N - target)

    fig = plt.figure(figsize=(24, 16))
    gs = fig.add_gridspec(3, 3, hspace=0.35, wspace=0.3)

    ax = fig.add_subplot(gs[0, 0])
    im = ax.imshow(target, cmap="inferno", vmin=0, vmax=8, interpolation="nearest")
    ax.set_title("Target [0-8]", fontweight="bold")
    plt.colorbar(im, ax=ax, fraction=0.046)
    ax.axis("off")

    ax = fig.add_subplot(gs[0, 1])
    ax.imshow(grid, cmap="binary", vmin=0, vmax=1, interpolation="nearest")
    ax.set_title(f"Mine Grid (={grid.mean():.3f})", fontweight="bold")
    ax.axis("off")

    ax = fig.add_subplot(gs[0, 2])
    im = ax.imshow(N, cmap="inferno", vmin=0, vmax=8, interpolation="nearest")
    ax.set_title("Number Field N(x,y)", fontweight="bold")
    plt.colorbar(im, ax=ax, fraction=0.046)
    ax.axis("off")

    ax = fig.add_subplot(gs[1, 0])
    im = ax.imshow(err, cmap="hot", vmin=0, vmax=4, interpolation="nearest")
    ax.set_title(f"|N-T| (mean={err.mean():.2f})", fontweight="bold")
    plt.colorbar(im, ax=ax, fraction=0.046)
    ax.axis("off")

    ax = fig.add_subplot(gs[1, 1])
    board_img = np.ones((H, W, 3), dtype=np.float32)
    for (y, x) in sr.revealed:
        board_img[y, x] = [0.82, 0.82, 0.82]
    for (y, x) in sr.flagged:
        board_img[y, x] = [1.0, 0.4, 0.0]
    for (y, x) in sr.unknown:
        board_img[y, x] = [0.3, 0.3, 0.9]
    ax.imshow(board_img, interpolation="nearest")
    solvable_str = "SOLVABLE" if sr.solvable else f"unknown={sr.n_unknown}"
    ax.set_title(f"Solve Map (cov={sr.coverage:.1%})\n{solvable_str}", fontweight="bold")
    ax.axis("off")

    ax = fig.add_subplot(gs[1, 2])
    if len(history) > 1:
        ax.plot(history, color="steelblue", lw=1.5)
        ax.set_yscale("log")
    ax.set_xlabel("Checkpoint")
    ax.set_ylabel("Loss")
    ax.set_title("Optimization Loss Curve", fontweight="bold")
    ax.grid(True, alpha=0.3)

    ax = fig.add_subplot(gs[2, 0])
    bins = np.arange(0, 10)
    ax.bar(
        bins[:-1] - 0.2,
        np.histogram(target.ravel(), bins=bins)[0],
        width=0.4,
        label="Target",
        color="steelblue",
        alpha=0.7,
    )
    ax.bar(
        bins[:-1] + 0.2,
        np.histogram(N.ravel(), bins=bins)[0],
        width=0.4,
        label="N field",
        color="tomato",
        alpha=0.7,
    )
    ax.legend()
    ax.set_xlabel("Value")
    ax.set_ylabel("Count")
    ax.set_title("Distribution: Target vs N field", fontweight="bold")

    ax = fig.add_subplot(gs[2, 1:])
    ax.axis("off")
    text = (
        f"{'METRIC':<22} {'VALUE':>14}\n{'-' * 38}\n"
        f"{'Board size':<22} {W}x{H} = {W*H:,} cells\n"
        f"{'Loss/cell':<22} {float(np.sum((N-target)**2))/(W*H):>14.4f}\n"
        f"{'Mean |N-T|':<22} {err.mean():>14.4f}\n"
        f"{'Mine density':<22} {grid.mean():>14.4f}\n"
        f"{'Solver coverage':<22} {sr.coverage:>14.4f}\n"
        f"{'Solvable':<22} {str(sr.solvable):>14}\n"
        f"{'Unknown cells':<22} {sr.n_unknown:>14}\n"
        f"{'Mine accuracy':<22} {sr.mine_accuracy:>14.4f}\n"
        f"{'Max N':<22} {int(N.max()):>14}\n"
    )
    ax.text(
        0.02,
        0.97,
        text,
        transform=ax.transAxes,
        fontsize=10,
        va="top",
        fontfamily="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#f8f8e8", edgecolor="gray", alpha=0.9),
    )

    fig.suptitle(title, fontsize=15, fontweight="bold", y=0.98)
    plt.savefig(save_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved  {save_path}")

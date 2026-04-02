from __future__ import annotations

import numpy as np
from PIL import Image as PILImage
from scipy.ndimage import convolve, gaussian_filter, sobel

KERNEL = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]], dtype=np.float32)


def compute_N(grid: np.ndarray) -> np.ndarray:
    """Count mines in 3x3 neighborhood of each cell (excluding center)."""
    return convolve(grid.astype(np.float32), KERNEL, mode="constant", cval=0)


def load_image_smart(path, board_w, board_h, panel="full", invert=True):
    img = PILImage.open(path).convert("L")
    W, H = img.size
    if panel == "left":
        img = img.crop((0, 0, W // 2, H))
    elif panel == "right":
        img = img.crop((W // 2, 0, W, H))
    from PIL import ImageEnhance

    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.resize((board_w, board_h), PILImage.LANCZOS)
    arr = np.array(img, dtype=np.float32)
    if invert:
        arr = 255.0 - arr
    lo, hi = np.percentile(arr, 2), np.percentile(arr, 98)
    arr = np.clip((arr - lo) / (hi - lo + 1e-8), 0, 1) * 8.0
    return arr.astype(np.float32)


def compute_edge_weights(target, boost=4.0, sigma=1.0):
    blurred = gaussian_filter(target, sigma=sigma)
    sx = sobel(blurred, axis=1)
    sy = sobel(blurred, axis=0)
    mag = np.hypot(sx, sy)
    mag /= mag.max() + 1e-8
    return (1.0 + boost * mag).astype(np.float32)


def nbrs(y, x, H, W):
    """Yield valid 8-neighbors of (y,x)."""
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            if dy == 0 and dx == 0:
                continue
            ny, nx = y + dy, x + dx
            if 0 <= ny < H and 0 <= nx < W:
                yield ny, nx


def assert_board_valid(grid, forbidden, label=""):
    tag = f"[{label}] " if label else ""
    N = compute_N(grid)
    assert set(np.unique(grid)).issubset({0, 1}), f"{tag}grid values outside {{0,1}}"
    assert int(np.sum((grid == 1) & (forbidden == 1))) == 0, (
        f"{tag}{np.sum((grid == 1) & (forbidden == 1))} mines in forbidden cells"
    )
    assert int(np.sum((N < 0) | (N > 8))) == 0, f"{tag}N out of [0,8]: min={N.min()}, max={N.max()}"

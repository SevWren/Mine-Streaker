from __future__ import annotations

import json
import os

import numpy as np


def atomic_save_json(data, path: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def atomic_save_npy(arr: np.ndarray, path: str) -> None:
    tmp = path + ".tmp.npy"
    np.save(tmp, arr)
    os.replace(tmp, path)

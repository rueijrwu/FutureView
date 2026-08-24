from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch

from .features import FEATURE_COLUMNS
from .labels import HORIZONS


@dataclass(frozen=True)
class WindowedData:
    x: torch.Tensor
    y: torch.Tensor
    dates: np.ndarray


def build_windows(
    features: pd.DataFrame,
    labels: pd.DataFrame,
    lookback: int = 50,
    horizons: tuple[int, ...] = HORIZONS,
) -> WindowedData:
    merged = features.merge(labels, on="date", how="inner").sort_values("date").reset_index(drop=True)
    target_columns = [f"trend_{h}" for h in horizons]

    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    dates: list[object] = []
    values = merged.loc[:, FEATURE_COLUMNS].to_numpy(dtype=np.float32)
    targets = merged.loc[:, target_columns].to_numpy(dtype=np.float32)

    for end in range(lookback - 1, len(merged)):
        start = end - lookback + 1
        xs.append(values[start : end + 1].T)
        ys.append(targets[end])
        dates.append(merged.loc[end, "date"])

    if not xs:
        raise ValueError("not enough aligned rows to build windows")

    x = torch.from_numpy(np.stack(xs))
    y = torch.from_numpy(np.stack(ys))
    return WindowedData(x=x, y=y, dates=np.asarray(dates))

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch

from .features import FEATURE_COLUMNS, make_causal_features
from .strategy1 import add_strategy1_events, _simulate_from_start, oracle_value_for_window


@dataclass(frozen=True)
class EntryEventDataset:
    x: torch.Tensor
    entry_return: np.ndarray
    oracle_benchmark: np.ndarray
    regret: np.ndarray
    capture_ratio: np.ndarray
    dates: pd.DatetimeIndex
    raw_indices: np.ndarray


def make_entry_event_dataset(
    df: pd.DataFrame,
    *,
    lookback: int = 50,
    horizon: int = 30,
    capture_epsilon: float = 1e-12,
) -> EntryEventDataset:
    """Build samples only at legal Strategy 1 Entry1 events.

    Learning target:
      entry_return = realized return from taking this exact Entry1 event and then
      following the frozen Strategy 1 mechanics through the fixed horizon.

    Benchmark only:
      oracle_benchmark = future-known best legal single campaign over the same
      interval. It is never used as the learning target.

    The input window ends on the Entry1 event date and contains only causal
    OHLCV features available through that close.
    """
    if lookback <= 0 or horizon <= 0:
        raise ValueError("lookback and horizon must be positive")

    events = add_strategy1_events(df).reset_index(drop=True)
    features = make_causal_features(df).reset_index(drop=True)
    feature_dates = pd.DatetimeIndex(pd.to_datetime(features["date"]))
    feature_pos = {pd.Timestamp(d): i for i, d in enumerate(feature_dates)}
    feature_values = features.loc[:, FEATURE_COLUMNS].to_numpy(dtype=np.float32)

    xs: list[np.ndarray] = []
    entry_returns: list[float] = []
    oracle_values: list[float] = []
    dates: list[pd.Timestamp] = []
    raw_indices: list[int] = []

    for i in range(len(events)):
        if not bool(events.at[i, "entry1_event"]):
            continue
        end = i + horizon - 1
        if end >= len(events):
            continue
        date = pd.Timestamp(events.at[i, "date"])
        pos = feature_pos.get(date)
        if pos is None or pos - lookback + 1 < 0:
            continue

        window = feature_values[pos - lookback + 1 : pos + 1]
        if window.shape != (lookback, len(FEATURE_COLUMNS)):
            continue
        if not np.isfinite(window).all():
            raise RuntimeError("non-finite entry-event feature window")

        entry_run = _simulate_from_start(events, i, end)
        oracle_run = oracle_value_for_window(events, i - 1, end)
        entry_return = float(entry_run.final_return)
        oracle_value = float(oracle_run.final_return)
        if oracle_value + 1e-12 < max(0.0, entry_return):
            raise RuntimeError("Oracle benchmark must dominate the current legal entry")

        xs.append(window.T.copy())
        entry_returns.append(entry_return)
        oracle_values.append(oracle_value)
        dates.append(date)
        raw_indices.append(i)

    if not xs:
        raise RuntimeError("no legal Entry1 event samples after lookback/horizon filtering")

    x = torch.from_numpy(np.stack(xs).astype(np.float32))
    entry = np.asarray(entry_returns, dtype=float)
    oracle = np.asarray(oracle_values, dtype=float)
    regret = oracle - entry
    capture = np.full(len(entry), np.nan, dtype=float)
    valid = oracle > capture_epsilon
    capture[valid] = entry[valid] / oracle[valid]

    if x.ndim != 3 or x.shape[1:] != (len(FEATURE_COLUMNS), lookback):
        raise RuntimeError(f"unexpected entry-event tensor shape: {tuple(x.shape)}")
    if not np.isfinite(entry).all() or not np.isfinite(oracle).all() or not np.isfinite(regret).all():
        raise RuntimeError("non-finite entry-event target or benchmark")
    if (regret < -1e-10).any():
        raise RuntimeError("negative Oracle regret detected")

    return EntryEventDataset(
        x=x,
        entry_return=entry,
        oracle_benchmark=oracle,
        regret=regret,
        capture_ratio=capture,
        dates=pd.DatetimeIndex(dates),
        raw_indices=np.asarray(raw_indices, dtype=int),
    )

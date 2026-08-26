from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import strategy1_reference_distribution as base
from .strategy1 import LOCAL_MAX_MIN_GAP, add_strategy1_events
from .strategy1_reference_distribution_fast import _simulate_path_fast

SCALES = (5, 10, 20, 60)
LOOKBACK = 60
REFERENCE_LOOKBACK = 60
HORIZON = 60
ADDON2_SPACING_TOLERANCE = 0.20


@dataclass(frozen=True)
class CQLabels:
    raw_indices: np.ndarray
    dates: np.ndarray
    L: np.ndarray
    mu: np.ndarray
    U: np.ndarray
    C: np.ndarray
    Q: np.ndarray


def make_price_volume_representation(df: pd.DataFrame) -> pd.DataFrame:
    """Return only the agreed dimensionless price/volume representation.

    For N in {5,10,20,60}:
      price_N(t)  = close(t)  / sum(close[t-N+1:t])
      volume_N(t) = volume(t) / sum(volume[t-N+1:t])

    No returns, moving averages, indicators, or other engineered inputs are added.
    """
    out = df.loc[:, ["date", "close", "volume"]].copy()
    close = out["close"].astype(float)
    volume = out["volume"].astype(float)
    for n in SCALES:
        out[f"price_{n}"] = close / close.rolling(n, min_periods=n).sum()
        out[f"volume_{n}"] = volume / volume.rolling(n, min_periods=n).sum()
    cols = ["date", *[f"price_{n}" for n in SCALES], *[f"volume_{n}" for n in SCALES]]
    return out.loc[:, cols].replace([np.inf, -np.inf], np.nan)


def input_columns() -> tuple[str, ...]:
    return tuple([f"price_{n}" for n in SCALES] + [f"volume_{n}" for n in SCALES])


def make_input_windows(df: pd.DataFrame, raw_indices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Build [sample, 8, 60] input windows for supplied raw entry indices."""
    rep = make_price_volume_representation(df).copy()
    rep["date"] = pd.to_datetime(rep["date"])
    rep = rep.set_index("date")
    raw_dates = pd.to_datetime(df["date"]).reset_index(drop=True)
    cols = list(input_columns())

    xs: list[np.ndarray] = []
    kept: list[int] = []
    for entry in np.asarray(raw_indices, dtype=int):
        if entry < LOOKBACK - 1:
            continue
        dates = raw_dates.iloc[entry - LOOKBACK + 1 : entry + 1]
        window = rep.reindex(pd.to_datetime(dates))
        if window[cols].isna().any().any():
            continue
        x = window[cols].to_numpy(dtype=np.float32).T
        if x.shape != (len(cols), LOOKBACK):
            continue
        xs.append(x)
        kept.append(int(entry))

    if not xs:
        raise RuntimeError("no entry samples survived price/volume representation")
    return np.stack(xs), np.asarray(kept, dtype=int)


def _entry_target(entry: int, end: int) -> tuple[float, float, float, int]:
    history_start = max(0, entry - REFERENCE_LOOKBACK + 1)
    configs = base._addon_reference_sets(history_start, entry)
    by_path: dict[tuple[int, int, int, int, int, int], float] = {}
    for config in configs:
        level_indices = tuple(level[0] for level in config)
        ret, _, _, _, path = _simulate_path_fast(
            entry,
            end,
            level_indices,
            ADDON2_SPACING_TOLERANCE,
        )
        by_path.setdefault(path, float(ret))
    returns = np.asarray(list(by_path.values()), dtype=float)
    if len(returns) == 0:
        raise RuntimeError(f"entry {entry} produced no legal realized paths")
    return float(np.min(returns)), float(np.mean(returns)), float(np.max(returns)), int(len(returns))


def make_cq_labels(df: pd.DataFrame) -> CQLabels:
    """Build only historical truth labels: L, mu, U, C, Q.

    L, mu and U are calculated from all legal realized Strategy-1 paths over the
    future horizon. C=U-L. Q=(U-mu)/(U-L). These values are labels only and are
    never part of the model input.
    """
    events = add_strategy1_events(df).reset_index(drop=True)
    base._prepare_worker_state(events)
    _simulate_path_fast.cache_clear()
    event_dates = pd.to_datetime(events["date"])

    indices: list[int] = []
    dates: list[object] = []
    lowers: list[float] = []
    means: list[float] = []
    uppers: list[float] = []

    for raw_entry in np.flatnonzero(events["entry_candidate"].to_numpy(dtype=bool)):
        entry = int(raw_entry)
        end = entry + HORIZON - 1
        if end >= len(events):
            continue
        L, mu, U, _ = _entry_target(entry, end)
        C = U - L
        if not np.isfinite(L) or not np.isfinite(mu) or not np.isfinite(U) or C <= 1e-12:
            continue
        indices.append(entry)
        dates.append(event_dates.iloc[entry])
        lowers.append(L)
        means.append(mu)
        uppers.append(U)

    if not indices:
        raise RuntimeError("no valid C/Q labels produced")

    L = np.asarray(lowers, dtype=float)
    mu = np.asarray(means, dtype=float)
    U = np.asarray(uppers, dtype=float)
    C = U - L
    Q = (U - mu) / C
    return CQLabels(
        raw_indices=np.asarray(indices, dtype=int),
        dates=np.asarray(dates),
        L=L,
        mu=mu,
        U=U,
        C=C,
        Q=Q,
    )

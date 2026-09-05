from __future__ import annotations

import numpy as np
import pandas as pd

from .strategy1_exit_window_cq_audit import classify_causal, final_exit_index
from .strategy1_layer2_consensus_group_audit import consensus_label
from .strategy1_representation_a import _periodic_baseline

EXTREMA_CONFIRMATION_LAG = 10


def add_path_availability(paths: pd.DataFrame, *, confirmation_lag: int = EXTREMA_CONFIRMATION_LAG) -> pd.DataFrame:
    if confirmation_lag < 0:
        raise ValueError("confirmation_lag must be non-negative")
    p = paths.copy()
    p["final_exit_index"] = final_exit_index(p).astype(int)
    p["available_index"] = p["final_exit_index"].astype(int) + int(confirmation_lag)
    return p


def build_causal_cq(
    df: pd.DataFrame,
    paths: pd.DataFrame,
    *,
    membership: str,
    window: int,
    confirmation_lag: int = EXTREMA_CONFIRMATION_LAG,
) -> pd.DataFrame:
    """Build causal entry/exit C/Q using NumPy arrays in the hot loop."""
    if membership not in {"entry", "exit"}:
        raise ValueError("membership must be entry or exit")
    if window <= 0:
        raise ValueError("window must be positive")

    close = df["close"].to_numpy(dtype=np.float64, copy=False)
    p = add_path_availability(paths, confirmation_lag=confirmation_lag)
    member_idx = p["entry_index" if membership == "entry" else "final_exit_index"].to_numpy(np.int64, copy=False)
    available = p["available_index"].to_numpy(np.int64, copy=False)
    returns = p["campaign_return"].to_numpy(np.float64, copy=False)

    starts, ends, us, bs, qs, counts, max_avails = [], [], [], [], [], [], []
    for start in range(0, len(df) - window + 1):
        end = start + window - 1
        mask = (member_idx >= start) & (member_idx <= end) & (available <= end)
        if not np.any(mask):
            continue
        r = returns[mask]
        u = float(np.max(r))
        b = float(_periodic_baseline(close, start, end))
        starts.append(start); ends.append(end); us.append(u); bs.append(b)
        qs.append(float(np.std(r, ddof=0))); counts.append(int(r.size))
        max_avails.append(int(np.max(available[mask])))

    return pd.DataFrame(
        {
            "start_index": np.asarray(starts, dtype=np.int32),
            "end_index": np.asarray(ends, dtype=np.int32),
            "membership": membership,
            "U": np.asarray(us, dtype=np.float64),
            "B": np.asarray(bs, dtype=np.float64),
            "C": np.asarray(us, dtype=np.float64) - np.asarray(bs, dtype=np.float64),
            "Q": np.asarray(qs, dtype=np.float64),
            "path_count": np.asarray(counts, dtype=np.int32),
            "max_member_available_index": np.asarray(max_avails, dtype=np.int32),
        }
    )


def build_causal_consensus_states(
    df: pd.DataFrame,
    paths: pd.DataFrame,
    *,
    window: int,
    confirmation_lag: int = EXTREMA_CONFIRMATION_LAG,
) -> pd.DataFrame:
    entry = build_causal_cq(df, paths, membership="entry", window=window, confirmation_lag=confirmation_lag)
    exit_ = build_causal_cq(df, paths, membership="exit", window=window, confirmation_lag=confirmation_lag)
    ce = classify_causal(entry.rename(columns={"B": "B_periodic"}))
    cx = classify_causal(exit_.rename(columns={"B": "B_periodic"}))
    states = ce[["start_index", "end_index", "state", "max_member_available_index"]].merge(
        cx[["start_index", "end_index", "state", "max_member_available_index"]],
        on=["start_index", "end_index"], suffixes=("_entry", "_exit")
    ).sort_values("end_index").reset_index(drop=True)
    states["consensus"] = [consensus_label(a, b) for a, b in zip(states.state_entry, states.state_exit)]
    return states


def mature_train_indices(cutoffs: np.ndarray | pd.Series, *, block_start: int, horizon: int, memory: int) -> np.ndarray:
    """Return most recent training rows whose targets are fully mature.

    Uses searchsorted for sorted cutoff arrays instead of scanning all rows.
    """
    if horizon <= 0 or memory <= 0:
        raise ValueError("horizon and memory must be positive")
    c = np.asarray(cutoffs, dtype=np.int64)
    if c.ndim != 1 or (c.size > 1 and np.any(c[1:] < c[:-1])):
        raise ValueError("cutoffs must be sorted ascending")
    # Need cutoff+h < block_start => cutoff <= block_start-h-1.
    limit = int(block_start) - int(horizon) - 1
    stop = int(np.searchsorted(c, limit, side="right"))
    if stop < memory:
        return np.asarray([], dtype=np.int64)
    return np.arange(stop - memory, stop, dtype=np.int64)


def assert_causal_states(states: pd.DataFrame) -> None:
    if states.empty:
        raise RuntimeError("no causal Layer1 states")
    end = states.end_index.to_numpy(np.int64, copy=False)
    bad_entry = states.max_member_available_index_entry.to_numpy(np.int64, copy=False) > end
    bad_exit = states.max_member_available_index_exit.to_numpy(np.int64, copy=False) > end
    if np.any(bad_entry) or np.any(bad_exit):
        raise AssertionError("Layer1 state contains a path outcome unavailable at window end")

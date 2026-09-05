from __future__ import annotations

import numpy as np
import pandas as pd

from .strategy1_exit_window_cq_audit import classify_causal, final_exit_index
from .strategy1_layer2_consensus_group_audit import consensus_label
from .strategy1_representation_a import _periodic_baseline

# The historical deterministic path definition uses retrospective 5D/10D extrema.
# Rather than changing the Strategy semantics, a path outcome becomes usable by
# Layer1 only after its exit plus the maximum 10-session extrema confirmation lag.
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
    """Build entry/exit C/Q using only path outcomes knowable by each window end.

    Membership keeps the historical definition (entry date or final-exit date in
    the window).  The additional availability gate is the causal information
    boundary: campaign_return may be used only when final_exit+confirmation_lag
    is no later than the current window end.
    """
    if membership not in {"entry", "exit"}:
        raise ValueError("membership must be entry or exit")
    if window <= 0:
        raise ValueError("window must be positive")

    close = df["close"].to_numpy(dtype=float)
    p = add_path_availability(paths, confirmation_lag=confirmation_lag)
    key = "entry_index" if membership == "entry" else "final_exit_index"
    rows: list[dict[str, object]] = []

    for start in range(0, len(df) - window + 1):
        end = start + window - 1
        g = p.loc[
            (p[key].astype(int) >= start)
            & (p[key].astype(int) <= end)
            & (p["available_index"].astype(int) <= end)
        ]
        if g.empty:
            continue
        r = g["campaign_return"].to_numpy(dtype=float)
        u = float(np.max(r))
        b = float(_periodic_baseline(close, start, end))
        rows.append(
            {
                "start_index": start,
                "end_index": end,
                "membership": membership,
                "U": u,
                "B": b,
                "C": u - b,
                "Q": float(np.std(r, ddof=0)),
                "path_count": int(len(g)),
                "max_member_available_index": int(g["available_index"].max()),
            }
        )
    return pd.DataFrame(rows)


def build_causal_consensus_states(
    df: pd.DataFrame,
    paths: pd.DataFrame,
    *,
    window: int,
    confirmation_lag: int = EXTREMA_CONFIRMATION_LAG,
) -> pd.DataFrame:
    entry = build_causal_cq(
        df, paths, membership="entry", window=window, confirmation_lag=confirmation_lag
    )
    exit_ = build_causal_cq(
        df, paths, membership="exit", window=window, confirmation_lag=confirmation_lag
    )
    ce = classify_causal(entry.rename(columns={"B": "B_periodic"}))
    cx = classify_causal(exit_.rename(columns={"B": "B_periodic"}))
    states = ce[["start_index", "end_index", "state", "max_member_available_index"]].merge(
        cx[["start_index", "end_index", "state", "max_member_available_index"]],
        on=["start_index", "end_index"],
        suffixes=("_entry", "_exit"),
    )
    states = states.sort_values("end_index").reset_index(drop=True)
    states["consensus"] = [
        consensus_label(a, b) for a, b in zip(states.state_entry, states.state_exit)
    ]
    return states


def mature_train_indices(
    cutoffs: np.ndarray | pd.Series,
    *,
    block_start: int,
    horizon: int,
    memory: int,
) -> np.ndarray:
    """Return the most recent training rows whose labels are fully mature."""
    if horizon <= 0 or memory <= 0:
        raise ValueError("horizon and memory must be positive")
    c = np.asarray(cutoffs, dtype=np.int64)
    eligible = np.flatnonzero(c + int(horizon) < int(block_start))
    if len(eligible) < memory:
        return np.asarray([], dtype=np.int64)
    return eligible[-memory:]


def assert_causal_states(states: pd.DataFrame) -> None:
    if states.empty:
        raise RuntimeError("no causal Layer1 states")
    bad_entry = states.max_member_available_index_entry.astype(int) > states.end_index.astype(int)
    bad_exit = states.max_member_available_index_exit.astype(int) > states.end_index.astype(int)
    if bool(bad_entry.any()) or bool(bad_exit.any()):
        raise AssertionError("Layer1 state contains a path outcome unavailable at window end")

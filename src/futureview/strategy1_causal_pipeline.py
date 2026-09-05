from __future__ import annotations

import numpy as np
import pandas as pd

from .strategy1_exit_window_cq_audit import classify_causal, final_exit_index
from .strategy1_representation_a import _periodic_baseline


def consensus_label(a: str, b: str) -> str:
    """Pure Layer1 state combiner; intentionally has no torch/Layer2 dependency."""
    a = str(a)
    b = str(b)
    if a == "neutral" and b == "neutral":
        return "neutral"
    if {a, b} == {"high", "low"}:
        return "neutral"
    if a == "high" or b == "high":
        return "high"
    if a == "low" or b == "low":
        return "low"
    return "neutral"


def build_complete_window_cq(
    df: pd.DataFrame,
    paths: pd.DataFrame,
    *,
    membership: str,
    window: int,
) -> pd.DataFrame:
    """Build C/Q/U only from Strategy paths fully contained in the window.

    Approved rule for [start, end]:
        start <= path.entry_index <= path.final_exit_index <= end

    Q follows the approved definition:
        Q(e) = U_W - R(e)
        Q_W  = mean_e Q(e)
    """
    if membership not in {"entry", "exit"}:
        raise ValueError("membership must be entry or exit")
    if window <= 0:
        raise ValueError("window must be positive")

    close = df["close"].to_numpy(dtype=np.float64, copy=False)
    p = paths.copy()
    p["final_exit_index"] = final_exit_index(p).astype(int)

    entry_idx = p["entry_index"].to_numpy(dtype=np.int64, copy=False)
    exit_idx = p["final_exit_index"].to_numpy(dtype=np.int64, copy=False)
    returns = p["campaign_return"].to_numpy(dtype=np.float64, copy=False)

    starts: list[int] = []
    ends: list[int] = []
    us: list[float] = []
    bs: list[float] = []
    qs: list[float] = []
    counts: list[int] = []
    min_entries: list[int] = []
    max_exits: list[int] = []

    for start in range(0, len(df) - window + 1):
        end = start + window - 1
        legal = (entry_idx >= start) & (exit_idx <= end)
        if not np.any(legal):
            continue
        r = returns[legal]
        u = float(np.max(r))
        b = float(_periodic_baseline(close, start, end))
        q = float(np.mean(u - r))
        starts.append(start)
        ends.append(end)
        us.append(u)
        bs.append(b)
        qs.append(q)
        counts.append(int(r.size))
        min_entries.append(int(np.min(entry_idx[legal])))
        max_exits.append(int(np.max(exit_idx[legal])))

    ua = np.asarray(us, dtype=np.float64)
    ba = np.asarray(bs, dtype=np.float64)
    return pd.DataFrame(
        {
            "start_index": np.asarray(starts, dtype=np.int32),
            "end_index": np.asarray(ends, dtype=np.int32),
            "membership": membership,
            "U": ua,
            "B": ba,
            "C": ua - ba,
            "Q": np.asarray(qs, dtype=np.float64),
            "path_count": np.asarray(counts, dtype=np.int32),
            "min_member_entry_index": np.asarray(min_entries, dtype=np.int32),
            "max_member_exit_index": np.asarray(max_exits, dtype=np.int32),
        }
    )


def build_complete_window_consensus_states(
    df: pd.DataFrame,
    paths: pd.DataFrame,
    *,
    window: int,
) -> pd.DataFrame:
    entry = build_complete_window_cq(df, paths, membership="entry", window=window)
    exit_ = build_complete_window_cq(df, paths, membership="exit", window=window)
    ce = classify_causal(entry.rename(columns={"B": "B_periodic"}))
    cx = classify_causal(exit_.rename(columns={"B": "B_periodic"}))
    cols = ["start_index", "end_index", "state", "min_member_entry_index", "max_member_exit_index"]
    states = ce[cols].merge(
        cx[cols],
        on=["start_index", "end_index"],
        suffixes=("_entry", "_exit"),
    ).sort_values("end_index").reset_index(drop=True)
    states["consensus"] = [
        consensus_label(a, b) for a, b in zip(states.state_entry, states.state_exit)
    ]
    return states


def assert_complete_window_states(states: pd.DataFrame) -> None:
    if states.empty:
        raise RuntimeError("no complete-window Layer1 states")
    start = states.start_index.to_numpy(np.int64, copy=False)
    end = states.end_index.to_numpy(np.int64, copy=False)
    for side in ("entry", "exit"):
        min_entry = states[f"min_member_entry_index_{side}"].to_numpy(np.int64, copy=False)
        max_exit = states[f"max_member_exit_index_{side}"].to_numpy(np.int64, copy=False)
        if np.any(min_entry < start):
            raise AssertionError(f"{side} C/Q includes a path whose entry is before the window")
        if np.any(max_exit > end):
            raise AssertionError(f"{side} C/Q includes an unfinished path")


# Temporary compatibility aliases while downstream scripts are migrated.
build_causal_cq = build_complete_window_cq
build_causal_consensus_states = build_complete_window_consensus_states
assert_causal_states = assert_complete_window_states

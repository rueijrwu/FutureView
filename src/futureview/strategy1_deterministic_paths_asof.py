from __future__ import annotations

from dataclasses import dataclass
import weakref

import numpy as np
import pandas as pd

from .strategy1_cq_data import HORIZON
from .strategy1_deterministic_paths import (
    MERGE_GAP,
    _most_recent_before,
    build_extrema_sets,
    preprocess_legal_points,
    simulate_deterministic_path,
)


@dataclass(frozen=True)
class AsOfDeterministicPath:
    entry_index: int
    base_min_index: int
    base_distance: float
    addon1_index: int
    addon2_index: int
    exit5_index: int
    exit10_index: int
    horizon_exit_index: int
    forced_asof_exit_index: int
    campaign_return: float


@dataclass
class _HistoryCache:
    source_ref: weakref.ReferenceType[pd.DataFrame]
    prepared: pd.DataFrame
    local_mins: np.ndarray
    local_maxs: np.ndarray
    entries: np.ndarray
    canonical_rows: dict[int, dict[str, int | float | str]]


_HISTORY_CACHE: dict[int, _HistoryCache] = {}


def _row_from_completed(path) -> dict[str, int | float | str]:
    exit_mode = "exit10" if path.exit10_index >= 0 else "horizon"
    return {
        "entry_index": path.entry_index,
        "base_min_index": path.base_min_index,
        "base_distance": path.base_distance,
        "addon1_index": path.addon1_index,
        "addon2_index": path.addon2_index,
        "exit5_index": path.exit5_index,
        "exit10_index": path.exit10_index,
        "horizon_exit_index": path.horizon_exit_index,
        "forced_asof_exit_index": -1,
        "exit_mode": exit_mode,
        "campaign_return": path.campaign_return,
        "executed_addons": int(path.addon1_index >= 0) + int(path.addon2_index >= 0),
    }


def _completed_exit_index(row: dict[str, int | float | str]) -> int:
    exit10 = int(row["exit10_index"])
    return exit10 if exit10 >= 0 else int(row["horizon_exit_index"])


def _get_history_cache(events: pd.DataFrame) -> _HistoryCache:
    """Prepare the historical Strategy data once for rolling reuse."""
    key = id(events)
    cached = _HISTORY_CACHE.get(key)
    if cached is not None and cached.source_ref() is events:
        return cached

    prepared = preprocess_legal_points(events, gap=MERGE_GAP)
    local_mins, local_maxs = build_extrema_sets(prepared)
    entries = np.flatnonzero(prepared["entry_candidate"].to_numpy(dtype=bool)).astype(np.int32)

    canonical_rows: dict[int, dict[str, int | float | str]] = {}
    for raw_entry in entries:
        path = simulate_deterministic_path(prepared, int(raw_entry), local_mins, local_maxs)
        if path is not None:
            canonical_rows[int(raw_entry)] = _row_from_completed(path)

    def _drop(_: object, *, cache_key: int = key) -> None:
        _HISTORY_CACHE.pop(cache_key, None)

    cache = _HistoryCache(
        source_ref=weakref.ref(events, _drop),
        prepared=prepared,
        local_mins=local_mins,
        local_maxs=local_maxs,
        entries=entries,
        canonical_rows=canonical_rows,
    )
    _HISTORY_CACHE[key] = cache
    return cache


def simulate_deterministic_path_asof(
    events: pd.DataFrame,
    entry: int,
    local_mins: np.ndarray,
    local_maxs: np.ndarray,
    *,
    asof_index: int,
    horizon: int = HORIZON,
) -> AsOfDeterministicPath | None:
    """Replay one path through the cutoff and close any remaining shares there.

    Entry, Addons, and partial exits at or before the cutoff are preserved.  The
    only rolling-specific rule is that a path whose final exit is after the
    cutoff is closed at the cutoff close.
    """
    if asof_index >= len(events):
        raise ValueError("asof_index must be inside events")
    if entry > asof_index:
        return None

    natural_end = entry + horizon - 1
    end = min(natural_end, asof_index)
    close = events["close"].to_numpy(dtype=float)
    base_min = _most_recent_before(local_mins, entry)
    if base_min < 0:
        return None

    entry_price = float(close[entry])
    d_b = entry_price - float(close[base_min])
    if not np.isfinite(d_b) or d_b <= 0.0:
        return None

    cash = 1.0
    shares = 0.0
    tranche = 1.0 / 3.0
    shares += tranche / entry_price
    cash -= tranche
    last_buy_price = entry_price
    entries_used = 1
    addon1 = addon2 = exit5 = exit10 = -1
    horizon_exit = forced_asof_exit = -1

    local_max_mask = np.zeros(len(events), dtype=np.bool_)
    local_max_mask[local_maxs] = True

    for i in range(entry + 1, end + 1):
        price = float(close[i])
        if bool(events.at[i, "exit10_event"]):
            cash += shares * price
            shares = 0.0
            exit10 = i
            break
        if exit5 < 0 and bool(events.at[i, "exit5_event"]):
            sold = 0.40 * shares
            cash += sold * price
            shares -= sold
            exit5 = i
            continue
        if entries_used < 3 and bool(local_max_mask[i]) and price - last_buy_price > d_b:
            if cash + 1e-12 < tranche:
                raise RuntimeError("Strategy attempted to exceed its fixed total-capital budget")
            shares += tranche / price
            cash -= tranche
            last_buy_price = price
            entries_used += 1
            if entries_used == 2:
                addon1 = i
            else:
                addon2 = i

    if shares > 0.0:
        cash += shares * float(close[end])
        if end < natural_end:
            forced_asof_exit = end
        else:
            horizon_exit = end

    return AsOfDeterministicPath(
        entry_index=int(entry),
        base_min_index=int(base_min),
        base_distance=float(d_b),
        addon1_index=int(addon1),
        addon2_index=int(addon2),
        exit5_index=int(exit5),
        exit10_index=int(exit10),
        horizon_exit_index=int(horizon_exit),
        forced_asof_exit_index=int(forced_asof_exit),
        campaign_return=float(cash - 1.0),
    )


def build_deterministic_path_table_asof(events: pd.DataFrame, *, asof_index: int) -> pd.DataFrame:
    """Return historical paths at a rolling cutoff with minimal recomputation.

    Completed paths are reused exactly.  A path is replayed only when its final
    exit is later than the cutoff (or the full-data path cannot yet complete),
    in which case remaining shares are closed at the cutoff close.
    """
    if asof_index < 0 or asof_index >= len(events):
        raise ValueError("asof_index must be inside events")

    cache = _get_history_cache(events)
    rows: list[dict[str, int | float | str]] = []

    for raw_entry in cache.entries[cache.entries <= asof_index]:
        entry = int(raw_entry)
        completed = cache.canonical_rows.get(entry)
        if completed is not None and _completed_exit_index(completed) <= asof_index:
            rows.append(completed.copy())
            continue

        path = simulate_deterministic_path_asof(
            cache.prepared,
            entry,
            cache.local_mins,
            cache.local_maxs,
            asof_index=asof_index,
        )
        if path is None:
            continue
        if path.exit10_index >= 0:
            exit_mode = "exit10"
        elif path.horizon_exit_index >= 0:
            exit_mode = "horizon"
        else:
            exit_mode = "forced_asof"
        rows.append({
            "entry_index": path.entry_index,
            "base_min_index": path.base_min_index,
            "base_distance": path.base_distance,
            "addon1_index": path.addon1_index,
            "addon2_index": path.addon2_index,
            "exit5_index": path.exit5_index,
            "exit10_index": path.exit10_index,
            "horizon_exit_index": path.horizon_exit_index,
            "forced_asof_exit_index": path.forced_asof_exit_index,
            "exit_mode": exit_mode,
            "campaign_return": path.campaign_return,
            "executed_addons": int(path.addon1_index >= 0) + int(path.addon2_index >= 0),
        })

    table = pd.DataFrame(rows)
    if table.empty:
        raise RuntimeError("No eligible as-of deterministic Strategy paths were produced")
    table = table.sort_values("entry_index").reset_index(drop=True)
    if table["entry_index"].duplicated().any():
        raise RuntimeError("as-of path table must contain at most one path per cleaned Entry")
    return table

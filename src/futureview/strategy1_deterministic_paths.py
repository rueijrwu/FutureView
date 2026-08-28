from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .strategy1_cq_data import HORIZON

MERGE_GAP = 3


@dataclass(frozen=True)
class DeterministicPath:
    entry_index: int
    base_min_index: int
    base_distance: float
    addon1_index: int
    addon2_index: int
    exit5_index: int
    exit10_index: int
    horizon_exit_index: int
    campaign_return: float


def retrospective_local_extrema(close: np.ndarray, radius: int, *, kind: str) -> np.ndarray:
    """Return retrospective local-extremum indices using radius sessions on each side."""
    if radius <= 0:
        raise ValueError("radius must be positive")
    if kind not in {"min", "max"}:
        raise ValueError("kind must be 'min' or 'max'")

    indices: list[int] = []
    for i in range(radius, len(close) - radius):
        window = close[i - radius : i + radius + 1]
        center = close[i]
        target = np.min(window) if kind == "min" else np.max(window)
        if center == target:
            indices.append(i)
    return np.asarray(indices, dtype=np.int32)


def build_extrema_sets(events: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    close = events["close"].to_numpy(dtype=float)
    mins = np.unique(
        np.concatenate(
            [
                retrospective_local_extrema(close, 5, kind="min"),
                retrospective_local_extrema(close, 10, kind="min"),
            ]
        )
    )
    maxs = np.unique(
        np.concatenate(
            [
                retrospective_local_extrema(close, 5, kind="max"),
                retrospective_local_extrema(close, 10, kind="max"),
            ]
        )
    )
    return mins.astype(np.int32), maxs.astype(np.int32)


def merge_legal_points_after_scan(indices: np.ndarray, *, gap: int = MERGE_GAP) -> np.ndarray:
    """Return cleaned legal points after a complete raw scan.

    The earliest unconsumed raw point is the anchor. Every raw point within
    anchor+gap trading sessions is merged into that anchor. Merged members never
    propagate the cluster farther forward. The scan then resumes at the next
    unconsumed raw point.
    """
    if gap < 0:
        raise ValueError("gap must be non-negative")
    raw = np.unique(np.asarray(indices, dtype=np.int64))
    if len(raw) == 0:
        return np.asarray([], dtype=np.int32)

    kept: list[int] = []
    i = 0
    while i < len(raw):
        anchor = int(raw[i])
        kept.append(anchor)
        i += 1
        while i < len(raw) and int(raw[i]) - anchor <= gap:
            i += 1
    return np.asarray(kept, dtype=np.int32)


def preprocess_legal_points(events: pd.DataFrame, *, gap: int = MERGE_GAP) -> pd.DataFrame:
    """Scan all raw legal Entry/Exit points, then create cleaned legal-point data."""
    out = events.copy()

    raw_entry = np.flatnonzero(out["entry_candidate"].to_numpy(dtype=bool))
    raw_exit5 = np.flatnonzero(out["exit5_event"].to_numpy(dtype=bool))
    raw_exit10 = np.flatnonzero(out["exit10_event"].to_numpy(dtype=bool))

    clean_entry = merge_legal_points_after_scan(raw_entry, gap=gap)
    clean_exit5 = merge_legal_points_after_scan(raw_exit5, gap=gap)
    clean_exit10 = merge_legal_points_after_scan(raw_exit10, gap=gap)

    out["raw_entry_candidate"] = out["entry_candidate"].astype(bool)
    out["raw_exit5_event"] = out["exit5_event"].astype(bool)
    out["raw_exit10_event"] = out["exit10_event"].astype(bool)

    out["entry_candidate"] = False
    out["exit5_event"] = False
    out["exit10_event"] = False
    out.loc[clean_entry, "entry_candidate"] = True
    out.loc[clean_exit5, "exit5_event"] = True
    out.loc[clean_exit10, "exit10_event"] = True

    return out


def _most_recent_before(indices: np.ndarray, index: int) -> int:
    pos = int(np.searchsorted(indices, index, side="left")) - 1
    return -1 if pos < 0 else int(indices[pos])


def simulate_deterministic_path(
    events: pd.DataFrame,
    entry: int,
    local_mins: np.ndarray,
    local_maxs: np.ndarray,
    *,
    horizon: int = HORIZON,
) -> DeterministicPath | None:
    """Simulate the current deterministic Strategy path from one cleaned legal Entry."""
    end = entry + horizon - 1
    if end >= len(events):
        return None

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

    addon1 = -1
    addon2 = -1
    exit5 = -1
    exit10 = -1
    horizon_exit = -1

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

        if (
            entries_used < 3
            and bool(local_max_mask[i])
            and price - last_buy_price > d_b
        ):
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
        shares = 0.0
        horizon_exit = end

    return DeterministicPath(
        entry_index=int(entry),
        base_min_index=int(base_min),
        base_distance=float(d_b),
        addon1_index=int(addon1),
        addon2_index=int(addon2),
        exit5_index=int(exit5),
        exit10_index=int(exit10),
        horizon_exit_index=int(horizon_exit),
        campaign_return=float(cash - 1.0),
    )


def build_deterministic_path_table(events: pd.DataFrame) -> pd.DataFrame:
    """Build one deterministic Strategy outcome per cleaned legal Entry."""
    events = preprocess_legal_points(events, gap=MERGE_GAP)
    local_mins, local_maxs = build_extrema_sets(events)
    entries = np.flatnonzero(events["entry_candidate"].to_numpy(dtype=bool))

    rows: list[dict[str, int | float]] = []
    for raw_entry in entries:
        path = simulate_deterministic_path(events, int(raw_entry), local_mins, local_maxs)
        if path is None:
            continue
        rows.append(
            {
                "entry_index": path.entry_index,
                "base_min_index": path.base_min_index,
                "base_distance": path.base_distance,
                "addon1_index": path.addon1_index,
                "addon2_index": path.addon2_index,
                "exit5_index": path.exit5_index,
                "exit10_index": path.exit10_index,
                "horizon_exit_index": path.horizon_exit_index,
                "campaign_return": path.campaign_return,
                "executed_addons": int(path.addon1_index >= 0) + int(path.addon2_index >= 0),
            }
        )

    table = pd.DataFrame(rows).sort_values("entry_index").reset_index(drop=True)
    if table.empty:
        raise RuntimeError("No eligible deterministic Strategy paths were produced")
    if table["entry_index"].duplicated().any():
        raise RuntimeError("deterministic path table must contain at most one path per cleaned Entry")
    return table

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .strategy1_cq_data import HORIZON
from .strategy1_deterministic_paths import (
    MERGE_GAP,
    build_extrema_sets,
    preprocess_legal_points,
    _most_recent_before,
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


def simulate_deterministic_path_asof(
    events: pd.DataFrame,
    entry: int,
    local_mins: np.ndarray,
    local_maxs: np.ndarray,
    *,
    asof_index: int,
    horizon: int = HORIZON,
) -> AsOfDeterministicPath | None:
    """Simulate Strategy using only information available through ``asof_index``.

    If an Entry is still open at the as-of cutoff, all remaining shares are
    liquidated at that session's close. This is only for rolling/as-of labels;
    it does not change the canonical full-history deterministic Strategy path.
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

    addon1 = -1
    addon2 = -1
    exit5 = -1
    exit10 = -1
    horizon_exit = -1
    forced_asof_exit = -1

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
    """Build causal as-of Strategy outcomes through ``asof_index``.

    The input is truncated before preprocessing/extrema detection so no event or
    retrospective extremum after the cutoff can affect the as-of path table.
    Open positions at the cutoff are force-closed at the cutoff close.
    """
    if asof_index < 0 or asof_index >= len(events):
        raise ValueError("asof_index must be inside events")

    truncated = events.iloc[: asof_index + 1].copy().reset_index(drop=True)
    truncated = preprocess_legal_points(truncated, gap=MERGE_GAP)
    local_mins, local_maxs = build_extrema_sets(truncated)
    entries = np.flatnonzero(truncated["entry_candidate"].to_numpy(dtype=bool))

    rows: list[dict[str, int | float | str]] = []
    for raw_entry in entries:
        path = simulate_deterministic_path_asof(
            truncated,
            int(raw_entry),
            local_mins,
            local_maxs,
            asof_index=asof_index,
        )
        if path is None:
            continue
        if path.exit10_index >= 0:
            exit_mode = "exit10"
        elif path.horizon_exit_index >= 0:
            exit_mode = "horizon"
        elif path.forced_asof_exit_index >= 0:
            exit_mode = "forced_asof"
        else:
            exit_mode = "closed"
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
                "forced_asof_exit_index": path.forced_asof_exit_index,
                "exit_mode": exit_mode,
                "campaign_return": path.campaign_return,
                "executed_addons": int(path.addon1_index >= 0) + int(path.addon2_index >= 0),
            }
        )

    table = pd.DataFrame(rows)
    if table.empty:
        raise RuntimeError("No eligible as-of deterministic Strategy paths were produced")
    table = table.sort_values("entry_index").reset_index(drop=True)
    if table["entry_index"].duplicated().any():
        raise RuntimeError("as-of path table must contain at most one path per cleaned Entry")
    return table

from __future__ import annotations

import os
from functools import lru_cache

import numpy as np

from . import strategy1_reference_distribution as base
from . import strategy1_reference_distribution_formal as formal
from .strategy1 import COOLDOWN_SESSIONS

try:
    from numba import njit
except ImportError as exc:  # pragma: no cover - environment dependent
    raise RuntimeError(
        "fast reference distribution requires numba; install once with: "
        "python -m pip install numba"
    ) from exc

_FAST_EVENTS_ID: int | None = None
_FAST_EXIT5: np.ndarray | None = None
_FAST_EXIT10: np.ndarray | None = None
FAST_SIM_CACHE_SIZE = 32768


@njit(cache=True)
def _simulate_numeric(
    close: np.ndarray,
    exit5_event: np.ndarray,
    exit10_event: np.ndarray,
    start: int,
    end: int,
    addon_count: int,
    addon_level_1: float,
    addon_level_2: float,
    addon2_spacing_tolerance: float,
) -> tuple[float, float, float, int, int, int, int, int, int]:
    cash = 1.0
    shares = 0.0
    exposure_fraction = 0.0
    exposure_days = 0.0
    entries_used = 1
    partial_exit_used = False
    last_entry_index = start
    last_partial_exit_index = -1
    entry_price = close[start]
    addon1_price = 0.0
    addon1_index = -1
    addon2_index = -1
    exit5_index = -1
    exit10_index = -1
    horizon_exit_index = -1

    amount = 1.0 / 3.0
    shares += amount / entry_price
    cash -= amount
    exposure_fraction += amount

    for i in range(start + 1, end + 1):
        if exposure_fraction > 1e-12:
            exposure_days += exposure_fraction

        price = close[i]
        exit_eligible = i - last_entry_index > COOLDOWN_SESSIONS

        if exit_eligible and exit10_event[i]:
            cash += shares * price
            shares = 0.0
            exposure_fraction = 0.0
            exit10_index = i
            break

        if exit_eligible and exit5_event[i] and (not partial_exit_used) and shares > 0.0:
            sold = 0.5 * shares
            cash += sold * price
            shares -= sold
            exposure_fraction *= 0.5
            partial_exit_used = True
            last_partial_exit_index = i
            exit5_index = i
            continue

        addon_eligible = last_partial_exit_index < 0 or i - last_partial_exit_index > COOLDOWN_SESSIONS
        next_addon = entries_used - 1
        if addon_eligible and entries_used < 3 and next_addon < addon_count:
            level = addon_level_1 if next_addon == 0 else addon_level_2
            prev_price = close[i - 1]
            crossed = price > level and prev_price <= level
            spacing_ok = True
            if crossed and next_addon == 1 and addon2_spacing_tolerance >= 0.0:
                first_gap = addon1_price - entry_price
                second_gap = price - addon1_price
                spacing_ok = (
                    first_gap > 0.0
                    and second_gap > 0.0
                    and abs(second_gap / first_gap - 1.0) <= addon2_spacing_tolerance
                )
            if crossed and spacing_ok:
                amount = 1.0 / 3.0
                shares += amount / price
                cash -= amount
                exposure_fraction += amount
                entries_used += 1
                last_entry_index = i
                if entries_used == 2:
                    addon1_price = price
                    addon1_index = i
                elif entries_used == 3:
                    addon2_index = i

    if shares > 0.0:
        cash += shares * close[end]
        horizon_exit_index = end

    final_return = cash - 1.0
    efficiency = final_return / exposure_days if exposure_days > 0.0 else 0.0
    return (
        final_return,
        efficiency,
        exposure_days,
        entries_used - 1,
        addon1_index,
        addon2_index,
        exit5_index,
        exit10_index,
        horizon_exit_index,
    )


def _fast_event_arrays() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    global _FAST_EVENTS_ID, _FAST_EXIT5, _FAST_EXIT10
    events, close, _, _, _, _ = base._require_state()
    events_id = id(events)
    if events_id != _FAST_EVENTS_ID or _FAST_EXIT5 is None or _FAST_EXIT10 is None:
        _FAST_EVENTS_ID = events_id
        _FAST_EXIT5 = events["exit5_event"].to_numpy(dtype=np.bool_)
        _FAST_EXIT10 = events["exit10_event"].to_numpy(dtype=np.bool_)
    return close, _FAST_EXIT5, _FAST_EXIT10


@lru_cache(maxsize=FAST_SIM_CACHE_SIZE)
def _simulate_path_fast(
    entry: int,
    end: int,
    addon_level_indices: tuple[int, ...],
    addon2_spacing_tolerance: float | None,
) -> formal.PathResult:
    close, exit5_event, exit10_event = _fast_event_arrays()
    addon_count = len(addon_level_indices)
    if addon_count > 2:
        raise ValueError("Strategy 1 supports at most two addon levels")

    level1 = float(close[addon_level_indices[0]]) if addon_count >= 1 else 0.0
    level2 = float(close[addon_level_indices[1]]) if addon_count >= 2 else 0.0
    spacing_tolerance = -1.0 if addon2_spacing_tolerance is None else float(addon2_spacing_tolerance)

    (
        ret,
        efficiency,
        exposure,
        executed_addons,
        addon1_index,
        addon2_index,
        exit5_index,
        exit10_index,
        horizon_exit_index,
    ) = _simulate_numeric(
        close,
        exit5_event,
        exit10_event,
        int(entry),
        int(end),
        int(addon_count),
        level1,
        level2,
        spacing_tolerance,
    )
    path = (
        int(entry),
        int(addon1_index),
        int(addon2_index),
        int(exit5_index),
        int(exit10_index),
        int(horizon_exit_index),
    )
    return float(ret), float(efficiency), float(exposure), int(executed_addons), path


def main() -> None:
    formal._simulate_path = _simulate_path_fast
    previous_workers = os.environ.get("FUTUREVIEW_WORKERS")
    os.environ["FUTUREVIEW_WORKERS"] = "1"
    try:
        print(
            "S1 REFERENCE_DISTRIBUTION FAST backend=numba_jit workers=1 "
            f"cache_size={FAST_SIM_CACHE_SIZE} research_version=formal_max2_spacing20 "
            "distribution_weighting=unique_realized_paths"
        )
        formal.main()
    finally:
        if previous_workers is None:
            os.environ.pop("FUTUREVIEW_WORKERS", None)
        else:
            os.environ["FUTUREVIEW_WORKERS"] = previous_workers


if __name__ == "__main__":
    main()

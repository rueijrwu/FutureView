from __future__ import annotations

from functools import lru_cache

import numpy as np

from . import strategy1_reference_distribution as base
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
) -> tuple[float, float, float]:
    """Numeric equivalent of Strategy 1's deterministic campaign simulation."""
    cash = 1.0
    shares = 0.0
    exposure_fraction = 0.0
    exposure_days = 0.0
    entries_used = 0
    partial_exit_used = False
    last_entry_index = start
    last_partial_exit_index = -1

    # Entry1: fixed one-third capital tranche.
    amount = 1.0 / 3.0
    shares += amount / close[start]
    cash -= amount
    exposure_fraction += amount
    entries_used = 1

    for i in range(start + 1, end + 1):
        if exposure_fraction > 1e-12:
            exposure_days += exposure_fraction

        price = close[i]
        exit_eligible = i - last_entry_index > COOLDOWN_SESSIONS

        if exit_eligible and exit10_event[i]:
            cash += shares * price
            shares = 0.0
            exposure_fraction = 0.0
            break

        if exit_eligible and exit5_event[i] and (not partial_exit_used) and shares > 0.0:
            sold = 0.5 * shares
            cash += sold * price
            shares -= sold
            exposure_fraction *= 0.5
            partial_exit_used = True
            last_partial_exit_index = i
            continue

        addon_eligible = last_partial_exit_index < 0 or i - last_partial_exit_index > COOLDOWN_SESSIONS
        next_addon = entries_used - 1
        if addon_eligible and entries_used < 3 and next_addon < addon_count:
            level = addon_level_1 if next_addon == 0 else addon_level_2
            prev_price = close[i - 1]
            if price > level and prev_price <= level:
                amount = 1.0 / 3.0
                shares += amount / price
                cash -= amount
                exposure_fraction += amount
                entries_used += 1
                last_entry_index = i

    if shares > 0.0:
        cash += shares * close[end]

    final_return = cash - 1.0
    efficiency = final_return / exposure_days if exposure_days > 0.0 else 0.0
    return final_return, efficiency, exposure_days


def _fast_event_arrays() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    global _FAST_EVENTS_ID, _FAST_EXIT5, _FAST_EXIT10
    events, close, _, _, _, _ = base._require_state()
    current_id = id(events)
    if _FAST_EVENTS_ID != current_id or _FAST_EXIT5 is None or _FAST_EXIT10 is None:
        _FAST_EVENTS_ID = current_id
        _FAST_EXIT5 = events["exit5_event"].to_numpy(dtype=np.bool_)
        _FAST_EXIT10 = events["exit10_event"].to_numpy(dtype=np.bool_)
    return close, _FAST_EXIT5, _FAST_EXIT10


@lru_cache(maxsize=None)
def _simulate_cached_fast(
    entry: int,
    end: int,
    addon_level_indices: tuple[int, ...],
) -> tuple[float, float, float]:
    close, exit5_event, exit10_event = _fast_event_arrays()
    count = len(addon_level_indices)
    if count > 2:
        raise ValueError("Strategy 1 supports at most two addon levels")
    level1 = float(close[addon_level_indices[0]]) if count >= 1 else 0.0
    level2 = float(close[addon_level_indices[1]]) if count >= 2 else 0.0
    ret, efficiency, exposure = _simulate_numeric(
        close,
        exit5_event,
        exit10_event,
        int(entry),
        int(end),
        int(count),
        level1,
        level2,
    )
    return float(ret), float(efficiency), float(exposure)


def main() -> None:
    # Patch only the hot simulation function. Candidate generation, bounds,
    # statistics, multiprocessing, and printed research definitions remain the
    # same as the audited reference-distribution runner.
    base._simulate_cached = _simulate_cached_fast
    print("S1 REFERENCE_DISTRIBUTION FAST backend=numba_jit semantics=unchanged")
    base.main()


if __name__ == "__main__":
    main()

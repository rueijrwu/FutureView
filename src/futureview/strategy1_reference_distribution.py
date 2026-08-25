from __future__ import annotations

import numpy as np
import pandas as pd

from .strategy1 import LOCAL_MAX_MIN_GAP, add_strategy1_events

_WORKER_EVENTS: pd.DataFrame | None = None
_CLOSE: np.ndarray | None = None
_ENTRY_INDICES: np.ndarray | None = None
_LOCAL_MAX_INDICES: np.ndarray | None = None
_EXIT5_PREFIX: np.ndarray | None = None
_EXIT10_PREFIX: np.ndarray | None = None


def _prepare_worker_state(events: pd.DataFrame) -> None:
    global _WORKER_EVENTS, _CLOSE, _ENTRY_INDICES, _LOCAL_MAX_INDICES
    global _EXIT5_PREFIX, _EXIT10_PREFIX

    _WORKER_EVENTS = events
    _CLOSE = events["close"].to_numpy(dtype=float)
    _ENTRY_INDICES = np.flatnonzero(events["entry_candidate"].to_numpy(dtype=bool))

    close = _CLOSE
    if len(close) >= 3:
        local_mask = (close[1:-1] > close[:-2]) & (close[1:-1] >= close[2:])
        _LOCAL_MAX_INDICES = np.flatnonzero(local_mask) + 1
    else:
        _LOCAL_MAX_INDICES = np.empty(0, dtype=int)

    exit5 = events["exit5_candidate"].to_numpy(dtype=np.int64)
    exit10 = events["exit10_candidate"].to_numpy(dtype=np.int64)
    _EXIT5_PREFIX = np.concatenate(([0], np.cumsum(exit5, dtype=np.int64)))
    _EXIT10_PREFIX = np.concatenate(([0], np.cumsum(exit10, dtype=np.int64)))


def _require_state() -> tuple[
    pd.DataFrame,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    state = (
        _WORKER_EVENTS,
        _CLOSE,
        _ENTRY_INDICES,
        _LOCAL_MAX_INDICES,
        _EXIT5_PREFIX,
        _EXIT10_PREFIX,
    )
    if any(value is None for value in state):
        raise RuntimeError("reference-distribution worker state was not initialized")
    return state  # type: ignore[return-value]


def _slice_indices(indices: np.ndarray, lower: int, upper_inclusive: int) -> np.ndarray:
    left = int(np.searchsorted(indices, lower, side="left"))
    right = int(np.searchsorted(indices, upper_inclusive, side="right"))
    return indices[left:right]


def _window_local_maxima(start: int, entry: int) -> tuple[int, ...]:
    _, _, _, maxima, _, _ = _require_state()
    if entry - start < 2:
        return ()
    subset = _slice_indices(maxima, max(start + 1, 1), entry - 1)
    return tuple(int(index) for index in subset)


def _addon_reference_sets(
    start: int,
    entry: int,
) -> tuple[tuple[tuple[int, float], ...], ...]:
    _, close, _, _, _, _ = _require_state()
    maxima = _window_local_maxima(start, entry)
    levels = tuple((index, float(close[index])) for index in maxima)

    configs: list[tuple[tuple[int, float], ...]] = [()]
    configs.extend((level,) for level in levels)
    for recent_pos in range(len(levels) - 1, -1, -1):
        recent = levels[recent_pos]
        for older_pos in range(recent_pos - 1, -1, -1):
            older = levels[older_pos]
            if recent[0] - older[0] > LOCAL_MAX_MIN_GAP:
                configs.append((recent, older))
    return tuple(configs)


def _candidate_count(prefix: np.ndarray, start: int, end: int) -> int:
    return int(prefix[end + 1] - prefix[start])


def _stats(values: np.ndarray) -> dict[str, float]:
    if len(values) == 0:
        fields = ("lower", "upper", "mean", "median", "std", "p25", "p75", "iqr", "positive_rate")
        return {field: float("nan") for field in fields} | {"n": 0.0}

    p25 = float(np.quantile(values, 0.25))
    p75 = float(np.quantile(values, 0.75))
    return {
        "n": float(len(values)),
        "lower": float(values.min()),
        "upper": float(values.max()),
        "mean": float(values.mean()),
        "median": float(np.median(values)),
        "std": float(values.std(ddof=0)),
        "p25": p25,
        "p75": p75,
        "iqr": p75 - p25,
        "positive_rate": float((values > 0.0).mean()),
    }


def _group_summary(
    returns: list[float],
    efficiencies: list[float],
    exposures: list[float],
) -> dict[str, object]:
    return_array = np.asarray(returns, dtype=float)
    efficiency_array = np.asarray(efficiencies, dtype=float)
    exposure_array = np.asarray(exposures, dtype=float)
    total_exposure = float(exposure_array.sum())
    return {
        "return": _stats(return_array),
        "efficiency": _stats(efficiency_array),
        "total_exposure_days": total_exposure,
        "aggregate_efficiency": (
            float(return_array.sum() / total_exposure) if total_exposure > 0.0 else 0.0
        ),
    }

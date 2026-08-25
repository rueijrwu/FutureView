from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache

import numpy as np
import pandas as pd

from .data import download_spy_daily, validate_daily_ohlcv
from .strategy1 import LOCAL_MAX_MIN_GAP, _simulate_from_start, add_strategy1_events

DATA_PERIOD = "5y"
WINDOWS = (30, 45, 60, 90)

_WORKER_EVENTS: pd.DataFrame | None = None
_CLOSE: np.ndarray | None = None
_ENTRY_INDICES: np.ndarray | None = None
_LOCAL_MAX_INDICES: np.ndarray | None = None
_EXIT5_PREFIX: np.ndarray | None = None
_EXIT10_PREFIX: np.ndarray | None = None


def _prepare_worker_state(events: pd.DataFrame) -> None:
    """Precompute immutable candidate arrays once per process."""
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
    _simulate_cached.cache_clear()


def _require_state() -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    if (
        _WORKER_EVENTS is None
        or _CLOSE is None
        or _ENTRY_INDICES is None
        or _LOCAL_MAX_INDICES is None
        or _EXIT5_PREFIX is None
        or _EXIT10_PREFIX is None
    ):
        raise RuntimeError("reference-distribution worker state was not initialized")
    return (
        _WORKER_EVENTS,
        _CLOSE,
        _ENTRY_INDICES,
        _LOCAL_MAX_INDICES,
        _EXIT5_PREFIX,
        _EXIT10_PREFIX,
    )


def _slice_indices(indices: np.ndarray, lower: int, upper_inclusive: int) -> np.ndarray:
    """Sorted index slice without rescanning the source series."""
    left = int(np.searchsorted(indices, lower, side="left"))
    right = int(np.searchsorted(indices, upper_inclusive, side="right"))
    return indices[left:right]


def _window_local_maxima(start: int, entry: int) -> tuple[int, ...]:
    """Precomputed confirmed local maxima inside window and before entry."""
    _, _, _, maxima, _, _ = _require_state()
    if entry - start < 2:
        return ()
    subset = _slice_indices(maxima, max(start + 1, 1), entry - 1)
    return tuple(int(i) for i in subset)


def _addon_reference_sets(start: int, entry: int) -> tuple[tuple[tuple[int, float], ...], ...]:
    """All zero/one/two-addon reference configurations legal at this entry."""
    _, close, _, _, _, _ = _require_state()
    maxima = _window_local_maxima(start, entry)
    levels = tuple((i, float(close[i])) for i in maxima)
    configs: list[tuple[tuple[int, float], ...]] = [()]
    configs.extend((level,) for level in levels)

    for recent_pos in range(len(levels) - 1, -1, -1):
        recent = levels[recent_pos]
        for older_pos in range(recent_pos - 1, -1, -1):
            older = levels[older_pos]
            if recent[0] - older[0] > LOCAL_MAX_MIN_GAP:
                configs.append((recent, older))

    return tuple(configs)


@lru_cache(maxsize=None)
def _simulate_cached(
    entry: int,
    end: int,
    addon_level_indices: tuple[int, ...],
) -> tuple[float, float, float]:
    """Memoize identical Strategy 1 paths encountered across overlapping anchors."""
    events, close, _, _, _, _ = _require_state()
    addon_levels = tuple((i, float(close[i])) for i in addon_level_indices)
    run = _simulate_from_start(events, entry, end, addon_levels=addon_levels)
    return float(run.final_return), float(run.return_per_exposure_day), float(run.exposure_days)


def _candidate_count(prefix: np.ndarray, start: int, end: int) -> int:
    return int(prefix[end + 1] - prefix[start])


def _stats(values: np.ndarray) -> dict[str, float]:
    if len(values) == 0:
        return {
            "n": 0.0,
            "lower": float("nan"),
            "upper": float("nan"),
            "mean": float("nan"),
            "median": float("nan"),
            "std": float("nan"),
            "p25": float("nan"),
            "p75": float("nan"),
            "iqr": float("nan"),
            "positive_rate": float("nan"),
        }
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
        "iqr": float(p75 - p25),
        "positive_rate": float((values > 0.0).mean()),
    }


def _summarize_window(
    start: int,
    end: int,
    entries: np.ndarray,
    config_cache: dict[int, tuple[tuple[tuple[int, float], ...], ...]],
    local_max_count_cache: dict[int, int],
) -> dict[str, object]:
    _, _, _, _, exit5_prefix, exit10_prefix = _require_state()

    returns: list[float] = []
    efficiencies: list[float] = []
    exposure_days: list[float] = []
    legal_combinations = 0
    local_max_candidate_count = 0

    for raw_entry in entries:
        entry = int(raw_entry)
        configs = config_cache[entry]
        local_max_candidate_count += local_max_count_cache[entry]
        legal_combinations += len(configs)
        for addon_levels in configs:
            level_indices = tuple(level[0] for level in addon_levels)
            ret, efficiency, exposure = _simulate_cached(entry, end, level_indices)
            returns.append(ret)
            efficiencies.append(efficiency)
            exposure_days.append(exposure)

    returns_a = np.asarray(returns, dtype=float)
    efficiencies_a = np.asarray(efficiencies, dtype=float)
    exposure_a = np.asarray(exposure_days, dtype=float)
    return_stats = _stats(returns_a)
    efficiency_stats = _stats(efficiencies_a)
    total_exposure = float(exposure_a.sum())
    aggregate_efficiency = float(returns_a.sum() / total_exposure) if total_exposure > 0.0 else 0.0

    return {
        "return": return_stats,
        "efficiency": efficiency_stats,
        "aggregate_efficiency": aggregate_efficiency,
        "total_exposure_days": total_exposure,
        "entry_count": float(len(entries)),
        "local_max_candidates": float(local_max_candidate_count),
        "exit5_candidates": float(_candidate_count(exit5_prefix, start, end)),
        "exit10_candidates": float(_candidate_count(exit10_prefix, start, end)),
        "legal_combinations": float(legal_combinations),
    }


def _summarize_anchor(start: int) -> tuple[int, dict[int, dict[str, object]]]:
    """Compute all windows for one anchor while reusing candidate/config scans."""
    _, _, entry_indices, _, _, _ = _require_state()
    max_end = start + max(WINDOWS) - 1
    all_entries = _slice_indices(entry_indices, start, max_end)

    config_cache: dict[int, tuple[tuple[tuple[int, float], ...], ...]] = {}
    local_max_count_cache: dict[int, int] = {}
    for raw_entry in all_entries:
        entry = int(raw_entry)
        maxima = _window_local_maxima(start, entry)
        local_max_count_cache[entry] = len(maxima)
        config_cache[entry] = _addon_reference_sets(start, entry)

    rows: dict[int, dict[str, object]] = {}
    for w in WINDOWS:
        end = start + w - 1
        right = int(np.searchsorted(all_entries, end, side="right"))
        entries = all_entries[:right]
        rows[w] = _summarize_window(
            start,
            end,
            entries,
            config_cache,
            local_max_count_cache,
        )
    return start, rows


def _init_worker(events: pd.DataFrame) -> None:
    _prepare_worker_state(events)


def _worker_task(start: int) -> tuple[int, dict[int, dict[str, object]]]:
    return _summarize_anchor(start)


def _worker_count() -> int:
    override = os.environ.get("FUTUREVIEW_WORKERS")
    if override is not None:
        workers = int(override)
        if workers < 1:
            raise ValueError("FUTUREVIEW_WORKERS must be >= 1")
        return workers
    return max(1, os.cpu_count() or 1)


def main() -> None:
    df = download_spy_daily(period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    max_window = max(WINDOWS)
    workers = _worker_count()
    anchor_count = len(events) - max_window + 1

    print(
        "S1 REFERENCE_DISTRIBUTION DATA "
        f"period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"windows={','.join(str(w) for w in WINDOWS)} model=false target=false workers={workers} "
        "precompute=true cache_simulations=true anchor_task=true"
    )
    print(
        "S1 REFERENCE_DISTRIBUTION RULE "
        "entry_set=all_sessions_satisfying_entry_condition_inside_fixed_window "
        "local_max_set=all_confirmed_local_maxima_inside_window_before_each_entry "
        f"local_max_pair_gap=gt_{LOCAL_MAX_MIN_GAP} "
        "addon_paths=optional_none_single_pair "
        "exit_set=all_exit_condition_sessions_for_audit "
        "exit_execution=existing_strategy1_first_eligible_signal_priority "
        "combination=entry_x_legal_addon_reference_set "
        "lower_bound=min_legal_combination_return upper_bound=max_legal_combination_return "
        "efficiency=combination_return_per_capital_weighted_exposure_day"
    )

    aggregate: dict[int, list[dict[str, object]]] = {w: [] for w in WINDOWS}
    starts = list(range(anchor_count))

    if workers == 1:
        _prepare_worker_state(events)
        results = map(_worker_task, starts)
        for _, rows_by_window in results:
            for w in WINDOWS:
                aggregate[w].append(rows_by_window[w])
    else:
        chunksize = max(1, len(starts) // (workers * 8))
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_worker,
            initargs=(events,),
        ) as pool:
            for _, rows_by_window in pool.map(_worker_task, starts, chunksize=chunksize):
                for w in WINDOWS:
                    aggregate[w].append(rows_by_window[w])

    for w in WINDOWS:
        rows = aggregate[w]
        nonempty = [row for row in rows if int(row["return"]["n"]) > 0]  # type: ignore[index]
        if not nonempty:
            raise RuntimeError(f"no non-empty legal combination sets for {w}D")

        def mean_field(group: str, name: str) -> float:
            return float(np.mean([row[group][name] for row in nonempty]))  # type: ignore[index]

        def median_field(group: str, name: str) -> float:
            return float(np.median([row[group][name] for row in nonempty]))  # type: ignore[index]

        def mean_scalar(name: str) -> float:
            return float(np.mean([row[name] for row in rows]))

        def median_scalar(name: str) -> float:
            return float(np.median([row[name] for row in rows]))

        aggregate_efficiencies = np.asarray(
            [row["aggregate_efficiency"] for row in nonempty], dtype=float
        )
        total_returns = 0.0
        total_exposure = 0.0
        for row in nonempty:
            exposure = float(row["total_exposure_days"])
            total_returns += float(row["aggregate_efficiency"]) * exposure
            total_exposure += exposure
        pooled_efficiency = total_returns / total_exposure if total_exposure > 0.0 else 0.0

        print(
            f"S1 REFERENCE_DISTRIBUTION WINDOW w={w} "
            f"anchors={len(rows)} nonempty={len(nonempty)} nonempty_rate={len(nonempty)/len(rows):.3f} "
            f"entry_candidates_mean={mean_scalar('entry_count'):.3f} "
            f"entry_candidates_median={median_scalar('entry_count'):.3f} "
            f"local_max_candidates_mean={mean_scalar('local_max_candidates'):.3f} "
            f"exit5_candidates_mean={mean_scalar('exit5_candidates'):.3f} "
            f"exit10_candidates_mean={mean_scalar('exit10_candidates'):.3f} "
            f"legal_combinations_mean={mean_scalar('legal_combinations'):.3f} "
            f"legal_combinations_median={median_scalar('legal_combinations'):.3f}"
        )
        print(
            f"S1 REFERENCE_DISTRIBUTION RETURN w={w} "
            f"lower_mean={mean_field('return', 'lower'):.6f} lower_median={median_field('return', 'lower'):.6f} "
            f"upper_mean={mean_field('return', 'upper'):.6f} upper_median={median_field('return', 'upper'):.6f} "
            f"mean_mean={mean_field('return', 'mean'):.6f} median_mean={mean_field('return', 'median'):.6f} "
            f"std_mean={mean_field('return', 'std'):.6f} std_median={median_field('return', 'std'):.6f} "
            f"p25_mean={mean_field('return', 'p25'):.6f} p75_mean={mean_field('return', 'p75'):.6f} "
            f"iqr_mean={mean_field('return', 'iqr'):.6f} iqr_median={median_field('return', 'iqr'):.6f} "
            f"win_rate_mean={mean_field('return', 'positive_rate'):.3f}"
        )
        print(
            f"S1 REFERENCE_DISTRIBUTION EFFICIENCY w={w} "
            f"lower_mean={mean_field('efficiency', 'lower'):.6f} lower_median={median_field('efficiency', 'lower'):.6f} "
            f"upper_mean={mean_field('efficiency', 'upper'):.6f} upper_median={median_field('efficiency', 'upper'):.6f} "
            f"mean_mean={mean_field('efficiency', 'mean'):.6f} median_mean={mean_field('efficiency', 'median'):.6f} "
            f"std_mean={mean_field('efficiency', 'std'):.6f} std_median={median_field('efficiency', 'std'):.6f} "
            f"p25_mean={mean_field('efficiency', 'p25'):.6f} p75_mean={mean_field('efficiency', 'p75'):.6f} "
            f"iqr_mean={mean_field('efficiency', 'iqr'):.6f} iqr_median={median_field('efficiency', 'iqr'):.6f} "
            f"positive_rate_mean={mean_field('efficiency', 'positive_rate'):.3f} "
            f"aggregate_efficiency_mean={aggregate_efficiencies.mean():.6f} "
            f"aggregate_efficiency_median={np.median(aggregate_efficiencies):.6f} "
            f"pooled_efficiency={pooled_efficiency:.6f}"
        )

    print("S1 REFERENCE_DISTRIBUTION COMPLETE")


if __name__ == "__main__":
    main()

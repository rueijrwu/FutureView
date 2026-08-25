from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from . import strategy1_reference_distribution as base
from .data import download_spy_daily, validate_daily_ohlcv
from .strategy1 import _simulate_from_start

DATA_PERIOD = "5y"
WINDOWS = (30, 45, 60, 90)
ADDON2_SPACING_TOLERANCE = 0.20
ADDON_GROUPS = (0, 1, 2)

PathSignature = tuple[int, int, int, int, int, int]
PathResult = tuple[float, float, float, int, PathSignature]


def _python_simulate_path(
    entry: int,
    end: int,
    addon_level_indices: tuple[int, ...],
    addon2_spacing_tolerance: float | None,
) -> PathResult:
    events, close, _, _, _, _ = base._require_state()
    addon_levels = tuple((index, float(close[index])) for index in addon_level_indices)
    run = _simulate_from_start(
        events,
        entry,
        end,
        addon_levels=addon_levels,
        addon2_spacing_tolerance=addon2_spacing_tolerance,
    )
    actions = {action.action: int(action.index) for action in run.actions}
    path = (
        int(entry),
        actions.get("addon1", -1),
        actions.get("addon2", -1),
        actions.get("exit5_half", -1),
        actions.get("exit10_full", -1),
        actions.get("horizon_exit", -1),
    )
    return (
        float(run.final_return),
        float(run.return_per_exposure_day),
        float(run.exposure_days),
        max(0, int(run.entries_used) - 1),
        path,
    )


# Fast runner replaces this with the Numba implementation at runtime.
_simulate_path = _python_simulate_path


def _summarize_window(
    start: int,
    end: int,
    entries: np.ndarray,
    config_cache: dict[int, tuple[tuple[tuple[int, float], ...], ...]],
    local_max_count_cache: dict[int, int],
) -> dict[str, object]:
    _, _, _, _, exit5_prefix, exit10_prefix = base._require_state()
    by_path: dict[PathSignature, tuple[float, float, float, int]] = {}
    legal_combinations = 0
    local_max_candidates = 0

    for raw_entry in entries:
        entry = int(raw_entry)
        configs = config_cache[entry]
        legal_combinations += len(configs)
        local_max_candidates += local_max_count_cache[entry]

        for config in configs:
            level_indices = tuple(level[0] for level in config)
            ret, eff, exp, executed_addons, path = _simulate_path(
                entry,
                end,
                level_indices,
                ADDON2_SPACING_TOLERANCE,
            )
            by_path.setdefault(path, (ret, eff, exp, executed_addons))

    realized = list(by_path.values())
    overall = base._group_summary(
        [item[0] for item in realized],
        [item[1] for item in realized],
        [item[2] for item in realized],
    )

    addon_groups: dict[int, dict[str, object]] = {}
    for addon_count in ADDON_GROUPS:
        selected = [item for item in realized if item[3] == addon_count]
        addon_groups[addon_count] = base._group_summary(
            [item[0] for item in selected],
            [item[1] for item in selected],
            [item[2] for item in selected],
        )

    realized_paths = len(realized)
    addon2_paths = sum(item[3] == 2 for item in realized)
    return {
        **overall,
        "addon_groups": addon_groups,
        "entry_count": float(len(entries)),
        "local_max_candidates": float(local_max_candidates),
        "exit5_candidates": float(base._candidate_count(exit5_prefix, start, end)),
        "exit10_candidates": float(base._candidate_count(exit10_prefix, start, end)),
        "legal_combinations": float(legal_combinations),
        "realized_paths": float(realized_paths),
        "dedup_ratio": float(realized_paths / legal_combinations) if legal_combinations else 0.0,
        "addon2_path_rate": float(addon2_paths / realized_paths) if realized_paths else 0.0,
    }


def _summarize_anchor(start: int) -> tuple[int, dict[int, dict[str, object]]]:
    _, _, entry_indices, _, _, _ = base._require_state()
    all_entries = base._slice_indices(entry_indices, start, start + max(WINDOWS) - 1)

    config_cache: dict[int, tuple[tuple[tuple[int, float], ...], ...]] = {}
    local_max_count_cache: dict[int, int] = {}
    for raw_entry in all_entries:
        entry = int(raw_entry)
        maxima = base._window_local_maxima(start, entry)
        local_max_count_cache[entry] = len(maxima)
        config_cache[entry] = base._addon_reference_sets(start, entry)

    rows: dict[int, dict[str, object]] = {}
    for window in WINDOWS:
        end = start + window - 1
        entry_count = int(np.searchsorted(all_entries, end, side="right"))
        rows[window] = _summarize_window(
            start,
            end,
            all_entries[:entry_count],
            config_cache,
            local_max_count_cache,
        )
    return start, rows


def _init_worker(events: pd.DataFrame) -> None:
    base._prepare_worker_state(events)


def _worker_count() -> int:
    override = os.environ.get("FUTUREVIEW_WORKERS")
    if override is None:
        return max(1, os.cpu_count() or 1)
    workers = int(override)
    if workers < 1:
        raise ValueError("FUTUREVIEW_WORKERS must be >= 1")
    return workers


def _print_addon_group(window: int, addon_count: int, rows: list[dict[str, object]]) -> None:
    groups = [row["addon_groups"][addon_count] for row in rows]  # type: ignore[index]
    nonempty = [group for group in groups if int(group["return"]["n"]) > 0]  # type: ignore[index]
    if not nonempty:
        return

    def mean_field(section: str, field: str) -> float:
        return float(np.mean([group[section][field] for group in nonempty]))  # type: ignore[index]

    counts = np.asarray([group["return"]["n"] for group in groups], dtype=float)  # type: ignore[index]
    total_exposure = sum(float(group["total_exposure_days"]) for group in nonempty)
    total_return = sum(
        float(group["aggregate_efficiency"]) * float(group["total_exposure_days"])
        for group in nonempty
    )
    pooled = total_return / total_exposure if total_exposure > 0.0 else 0.0

    print(
        f"S1 REFERENCE_DISTRIBUTION ADDON_GROUP w={window} executed_addons={addon_count} "
        f"realized_paths_mean={counts.mean():.3f} realized_paths_median={np.median(counts):.3f} "
        f"return_lower_mean={mean_field('return','lower'):.6f} "
        f"return_upper_mean={mean_field('return','upper'):.6f} "
        f"return_mean={mean_field('return','mean'):.6f} "
        f"return_median={mean_field('return','median'):.6f} "
        f"return_std_mean={mean_field('return','std'):.6f} "
        f"return_iqr_mean={mean_field('return','iqr'):.6f} "
        f"win_rate_mean={mean_field('return','positive_rate'):.3f} "
        f"efficiency_mean={mean_field('efficiency','mean'):.6f} "
        f"efficiency_median={mean_field('efficiency','median'):.6f} "
        f"efficiency_pooled={pooled:.6f}"
    )


def main() -> None:
    df = download_spy_daily(period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = base.add_strategy1_events(df).reset_index(drop=True)
    workers = _worker_count()
    anchor_count = len(events) - max(WINDOWS) + 1

    print(
        "S1 REFERENCE_DISTRIBUTION DATA "
        f"period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"windows={','.join(str(window) for window in WINDOWS)} model=false target=false workers={workers} "
        "research_version=formal_max2_spacing20 distribution_weighting=unique_realized_paths"
    )
    print(
        "S1 REFERENCE_DISTRIBUTION RULE "
        "entry_set=all_sessions_satisfying_entry_condition_inside_fixed_window "
        "local_max_set=all_confirmed_local_maxima_inside_window_before_each_entry "
        f"local_max_pair_gap=gt_{base.LOCAL_MAX_MIN_GAP} addon_paths=optional_none_single_pair "
        "max_addons=2 addon2_spacing_tolerance=0.20 "
        "addon2_spacing_rule=abs((addon2_price-addon1_price)/(addon1_price-entry_price)-1)<=0.20 "
        "addon2_requires_positive_price_steps=true "
        "exit_set=all_exit_condition_sessions_for_audit "
        "exit_execution=existing_strategy1_first_eligible_signal_priority "
        "distribution_weighting=unique_realized_paths "
        "lower_bound=min_formal_legal_realized_path_return "
        "upper_bound=max_formal_legal_realized_path_return "
        "efficiency=realized_path_return_per_capital_weighted_exposure_day"
    )

    aggregate: dict[int, list[dict[str, object]]] = {window: [] for window in WINDOWS}
    starts = list(range(anchor_count))
    if workers == 1:
        base._prepare_worker_state(events)
        results = map(_summarize_anchor, starts)
        for _, rows_by_window in results:
            for window in WINDOWS:
                aggregate[window].append(rows_by_window[window])
    else:
        chunksize = max(1, len(starts) // (workers * 8))
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_worker,
            initargs=(events,),
        ) as pool:
            for _, rows_by_window in pool.map(_summarize_anchor, starts, chunksize=chunksize):
                for window in WINDOWS:
                    aggregate[window].append(rows_by_window[window])

    for window in WINDOWS:
        rows = aggregate[window]
        nonempty = [row for row in rows if int(row["return"]["n"]) > 0]  # type: ignore[index]
        if not nonempty:
            raise RuntimeError(f"no non-empty formal realized path sets for {window}D")

        def mean_field(section: str, field: str) -> float:
            return float(np.mean([row[section][field] for row in nonempty]))  # type: ignore[index]

        def median_field(section: str, field: str) -> float:
            return float(np.median([row[section][field] for row in nonempty]))  # type: ignore[index]

        def mean_scalar(field: str) -> float:
            return float(np.mean([row[field] for row in rows]))

        def median_scalar(field: str) -> float:
            return float(np.median([row[field] for row in rows]))

        aggregate_efficiencies = np.asarray(
            [row["aggregate_efficiency"] for row in nonempty], dtype=float
        )
        total_exposure = sum(float(row["total_exposure_days"]) for row in nonempty)
        total_return = sum(
            float(row["aggregate_efficiency"]) * float(row["total_exposure_days"])
            for row in nonempty
        )
        pooled = total_return / total_exposure if total_exposure > 0.0 else 0.0

        print(
            f"S1 REFERENCE_DISTRIBUTION WINDOW w={window} anchors={len(rows)} "
            f"nonempty={len(nonempty)} nonempty_rate={len(nonempty)/len(rows):.3f} "
            f"entry_candidates_mean={mean_scalar('entry_count'):.3f} "
            f"entry_candidates_median={median_scalar('entry_count'):.3f} "
            f"local_max_candidates_mean={mean_scalar('local_max_candidates'):.3f} "
            f"exit5_candidates_mean={mean_scalar('exit5_candidates'):.3f} "
            f"exit10_candidates_mean={mean_scalar('exit10_candidates'):.3f} "
            f"legal_combinations_mean={mean_scalar('legal_combinations'):.3f} "
            f"realized_paths_mean={mean_scalar('realized_paths'):.3f} "
            f"dedup_ratio_mean={mean_scalar('dedup_ratio'):.4f} "
            f"addon2_path_rate_mean={mean_scalar('addon2_path_rate'):.4f}"
        )
        print(
            f"S1 REFERENCE_DISTRIBUTION RETURN w={window} "
            f"lower_mean={mean_field('return','lower'):.6f} "
            f"lower_median={median_field('return','lower'):.6f} "
            f"upper_mean={mean_field('return','upper'):.6f} "
            f"upper_median={median_field('return','upper'):.6f} "
            f"mean_mean={mean_field('return','mean'):.6f} "
            f"median_mean={mean_field('return','median'):.6f} "
            f"std_mean={mean_field('return','std'):.6f} "
            f"std_median={median_field('return','std'):.6f} "
            f"p25_mean={mean_field('return','p25'):.6f} "
            f"p75_mean={mean_field('return','p75'):.6f} "
            f"iqr_mean={mean_field('return','iqr'):.6f} "
            f"iqr_median={median_field('return','iqr'):.6f} "
            f"win_rate_mean={mean_field('return','positive_rate'):.3f}"
        )
        print(
            f"S1 REFERENCE_DISTRIBUTION EFFICIENCY w={window} "
            f"lower_mean={mean_field('efficiency','lower'):.6f} "
            f"lower_median={median_field('efficiency','lower'):.6f} "
            f"upper_mean={mean_field('efficiency','upper'):.6f} "
            f"upper_median={median_field('efficiency','upper'):.6f} "
            f"mean_mean={mean_field('efficiency','mean'):.6f} "
            f"median_mean={mean_field('efficiency','median'):.6f} "
            f"std_mean={mean_field('efficiency','std'):.6f} "
            f"std_median={median_field('efficiency','std'):.6f} "
            f"p25_mean={mean_field('efficiency','p25'):.6f} "
            f"p75_mean={mean_field('efficiency','p75'):.6f} "
            f"iqr_mean={mean_field('efficiency','iqr'):.6f} "
            f"iqr_median={median_field('efficiency','iqr'):.6f} "
            f"positive_rate_mean={mean_field('efficiency','positive_rate'):.3f} "
            f"aggregate_efficiency_mean={aggregate_efficiencies.mean():.6f} "
            f"aggregate_efficiency_median={np.median(aggregate_efficiencies):.6f} "
            f"pooled_efficiency={pooled:.6f}"
        )
        for addon_count in ADDON_GROUPS:
            _print_addon_group(window, addon_count, rows)

    print("S1 REFERENCE_DISTRIBUTION COMPLETE")


if __name__ == "__main__":
    main()

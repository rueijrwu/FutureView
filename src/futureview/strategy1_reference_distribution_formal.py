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
FORMAL_MAX_ADDONS = 2
FORMAL_ADDON2_SPACING_TOLERANCE = 0.20
ADDON_GROUPS = (0, 1, 2)


def _python_simulate_path(
    entry: int,
    end: int,
    addon_level_indices: tuple[int, ...],
    addon2_spacing_tolerance: float | None,
) -> tuple[float, float, float, int, tuple[int, int, int, int, int, int]]:
    events, close, _, _, _, _ = base._require_state()
    addon_levels = tuple((i, float(close[i])) for i in addon_level_indices)
    run = _simulate_from_start(
        events,
        entry,
        end,
        addon_levels=addon_levels,
        addon2_spacing_tolerance=addon2_spacing_tolerance,
    )
    action_index = {action.action: int(action.index) for action in run.actions}
    path = (
        int(entry),
        action_index.get("addon1", -1),
        action_index.get("addon2", -1),
        action_index.get("exit5_half", -1),
        action_index.get("exit10_full", -1),
        action_index.get("horizon_exit", -1),
    )
    return (
        float(run.final_return),
        float(run.return_per_exposure_day),
        float(run.exposure_days),
        max(0, int(run.entries_used) - 1),
        path,
    )


_simulate_path = _python_simulate_path


def _summarize_formal_window(
    start: int,
    end: int,
    entries: np.ndarray,
    config_cache: dict[int, tuple[tuple[tuple[int, float], ...], ...]],
    local_max_count_cache: dict[int, int],
) -> dict[str, object]:
    _, _, _, _, exit5_prefix, exit10_prefix = base._require_state()

    legal_combinations = 0
    local_max_candidate_count = 0
    by_path: dict[tuple[int, int, int, int, int, int], tuple[float, float, float, int]] = {}

    for raw_entry in entries:
        entry = int(raw_entry)
        configs = tuple(config for config in config_cache[entry] if len(config) <= FORMAL_MAX_ADDONS)
        local_max_candidate_count += local_max_count_cache[entry]
        legal_combinations += len(configs)
        for config in configs:
            level_indices = tuple(level[0] for level in config)
            ret, eff, exp, executed_addons, path = _simulate_path(
                entry,
                end,
                level_indices,
                FORMAL_ADDON2_SPACING_TOLERANCE,
            )
            by_path.setdefault(path, (ret, eff, exp, executed_addons))

    realized = list(by_path.values())
    returns = [item[0] for item in realized]
    efficiencies = [item[1] for item in realized]
    exposures = [item[2] for item in realized]
    overall = base._group_summary(returns, efficiencies, exposures)

    addon_groups: dict[int, dict[str, object]] = {}
    for addon_count in ADDON_GROUPS:
        selected = [item for item in realized if item[3] == addon_count]
        addon_groups[addon_count] = base._group_summary(
            [item[0] for item in selected],
            [item[1] for item in selected],
            [item[2] for item in selected],
        )

    realized_paths = len(realized)
    addon2_paths = sum(1 for item in realized if item[3] == 2)
    return {
        **overall,
        "addon_groups": addon_groups,
        "entry_count": float(len(entries)),
        "local_max_candidates": float(local_max_candidate_count),
        "exit5_candidates": float(base._candidate_count(exit5_prefix, start, end)),
        "exit10_candidates": float(base._candidate_count(exit10_prefix, start, end)),
        "legal_combinations": float(legal_combinations),
        "realized_paths": float(realized_paths),
        "dedup_ratio": float(realized_paths / legal_combinations) if legal_combinations > 0 else 0.0,
        "addon2_path_rate": float(addon2_paths / realized_paths) if realized_paths > 0 else 0.0,
    }


def _summarize_anchor(start: int) -> tuple[int, dict[int, dict[str, object]]]:
    _, _, entry_indices, _, _, _ = base._require_state()
    max_end = start + max(WINDOWS) - 1
    all_entries = base._slice_indices(entry_indices, start, max_end)

    config_cache: dict[int, tuple[tuple[tuple[int, float], ...], ...]] = {}
    local_max_count_cache: dict[int, int] = {}
    for raw_entry in all_entries:
        entry = int(raw_entry)
        maxima = base._window_local_maxima(start, entry)
        local_max_count_cache[entry] = len(maxima)
        config_cache[entry] = base._addon_reference_sets(start, entry)

    rows: dict[int, dict[str, object]] = {}
    for w in WINDOWS:
        end = start + w - 1
        right = int(np.searchsorted(all_entries, end, side="right"))
        rows[w] = _summarize_formal_window(
            start,
            end,
            all_entries[:right],
            config_cache,
            local_max_count_cache,
        )
    return start, rows


def _init_worker(events: pd.DataFrame) -> None:
    base._prepare_worker_state(events)


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


def _print_addon_group(w: int, addon_count: int, rows: list[dict[str, object]]) -> None:
    groups = [row["addon_groups"][addon_count] for row in rows]  # type: ignore[index]
    nonempty = [group for group in groups if int(group["return"]["n"]) > 0]  # type: ignore[index]
    if not nonempty:
        return

    def mf(section: str, field: str) -> float:
        return float(np.mean([group[section][field] for group in nonempty]))  # type: ignore[index]

    counts = np.asarray([group["return"]["n"] for group in groups], dtype=float)  # type: ignore[index]
    total_return = 0.0
    total_exposure = 0.0
    for group in nonempty:
        exposure = float(group["total_exposure_days"])
        total_return += float(group["aggregate_efficiency"]) * exposure
        total_exposure += exposure
    pooled = total_return / total_exposure if total_exposure > 0.0 else 0.0

    print(
        f"S1 REFERENCE_DISTRIBUTION ADDON_GROUP w={w} executed_addons={addon_count} "
        f"realized_paths_mean={counts.mean():.3f} realized_paths_median={np.median(counts):.3f} "
        f"return_lower_mean={mf('return','lower'):.6f} return_upper_mean={mf('return','upper'):.6f} "
        f"return_mean={mf('return','mean'):.6f} return_median={mf('return','median'):.6f} "
        f"return_std_mean={mf('return','std'):.6f} return_iqr_mean={mf('return','iqr'):.6f} "
        f"win_rate_mean={mf('return','positive_rate'):.3f} "
        f"efficiency_mean={mf('efficiency','mean'):.6f} efficiency_median={mf('efficiency','median'):.6f} "
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
        f"windows={','.join(str(w) for w in WINDOWS)} model=false target=false workers={workers} "
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
        "combination=entry_x_legal_addon_reference_set "
        "distribution_weighting=unique_realized_paths "
        "lower_bound=min_formal_legal_realized_path_return "
        "upper_bound=max_formal_legal_realized_path_return "
        "efficiency=realized_path_return_per_capital_weighted_exposure_day"
    )

    aggregate: dict[int, list[dict[str, object]]] = {w: [] for w in WINDOWS}
    starts = list(range(anchor_count))
    if workers == 1:
        base._prepare_worker_state(events)
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
            raise RuntimeError(f"no non-empty formal realized path sets for {w}D")

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
        total_return = 0.0
        total_exposure = 0.0
        for row in nonempty:
            exposure = float(row["total_exposure_days"])
            total_return += float(row["aggregate_efficiency"]) * exposure
            total_exposure += exposure
        pooled = total_return / total_exposure if total_exposure > 0.0 else 0.0

        print(
            f"S1 REFERENCE_DISTRIBUTION WINDOW w={w} anchors={len(rows)} "
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
            f"S1 REFERENCE_DISTRIBUTION RETURN w={w} "
            f"lower_mean={mean_field('return','lower'):.6f} lower_median={median_field('return','lower'):.6f} "
            f"upper_mean={mean_field('return','upper'):.6f} upper_median={median_field('return','upper'):.6f} "
            f"mean_mean={mean_field('return','mean'):.6f} median_mean={mean_field('return','median'):.6f} "
            f"std_mean={mean_field('return','std'):.6f} std_median={median_field('return','std'):.6f} "
            f"p25_mean={mean_field('return','p25'):.6f} p75_mean={mean_field('return','p75'):.6f} "
            f"iqr_mean={mean_field('return','iqr'):.6f} iqr_median={median_field('return','iqr'):.6f} "
            f"win_rate_mean={mean_field('return','positive_rate'):.3f}"
        )
        print(
            f"S1 REFERENCE_DISTRIBUTION EFFICIENCY w={w} "
            f"lower_mean={mean_field('efficiency','lower'):.6f} lower_median={median_field('efficiency','lower'):.6f} "
            f"upper_mean={mean_field('efficiency','upper'):.6f} upper_median={median_field('efficiency','upper'):.6f} "
            f"mean_mean={mean_field('efficiency','mean'):.6f} median_mean={mean_field('efficiency','median'):.6f} "
            f"std_mean={mean_field('efficiency','std'):.6f} std_median={median_field('efficiency','std'):.6f} "
            f"p25_mean={mean_field('efficiency','p25'):.6f} p75_mean={mean_field('efficiency','p75'):.6f} "
            f"iqr_mean={mean_field('efficiency','iqr'):.6f} iqr_median={median_field('efficiency','iqr'):.6f} "
            f"positive_rate_mean={mean_field('efficiency','positive_rate'):.3f} "
            f"aggregate_efficiency_mean={aggregate_efficiencies.mean():.6f} "
            f"aggregate_efficiency_median={np.median(aggregate_efficiencies):.6f} "
            f"pooled_efficiency={pooled:.6f}"
        )
        for addon_count in ADDON_GROUPS:
            _print_addon_group(w, addon_count, rows)

    print("S1 REFERENCE_DISTRIBUTION COMPLETE")


if __name__ == "__main__":
    main()

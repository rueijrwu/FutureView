from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from .data import download_spy_daily, validate_daily_ohlcv
from . import strategy1_reference_distribution as base

DATA_PERIOD = "5y"
WINDOWS = (30, 45, 60, 90)
POLICIES: tuple[tuple[str, int, float | None], ...] = (
    ("max1", 1, None),
    ("unrestricted", 2, None),
    ("spacing10", 2, 0.10),
    ("spacing20", 2, 0.20),
    ("spacing30", 2, 0.30),
)


def _policy_configs(
    configs: tuple[tuple[tuple[int, float], ...], ...],
    max_addons: int,
) -> tuple[tuple[tuple[int, float], ...], ...]:
    return tuple(config for config in configs if len(config) <= max_addons)


def _summarize_policy_window(
    start: int,
    end: int,
    entries: np.ndarray,
    config_cache: dict[int, tuple[tuple[tuple[int, float], ...], ...]],
    max_addons: int,
    tolerance: float | None,
) -> dict[str, object]:
    returns: list[float] = []
    efficiencies: list[float] = []
    exposures: list[float] = []
    executed2 = 0
    combinations = 0

    for raw_entry in entries:
        entry = int(raw_entry)
        configs = _policy_configs(config_cache[entry], max_addons)
        combinations += len(configs)
        for config in configs:
            level_indices = tuple(level[0] for level in config)
            ret, eff, exp, executed_addons = base._simulate_cached(
                entry,
                end,
                level_indices,
                tolerance,
            )
            returns.append(ret)
            efficiencies.append(eff)
            exposures.append(exp)
            if executed_addons == 2:
                executed2 += 1

    summary = base._group_summary(returns, efficiencies, exposures)
    return {
        **summary,
        "legal_combinations": float(combinations),
        "executed2": float(executed2),
        "executed2_rate": float(executed2 / combinations) if combinations > 0 else 0.0,
    }


def _summarize_anchor(start: int) -> tuple[int, dict[int, dict[str, dict[str, object]]]]:
    _, _, entry_indices, _, _, _ = base._require_state()
    max_end = start + max(WINDOWS) - 1
    all_entries = base._slice_indices(entry_indices, start, max_end)

    config_cache: dict[int, tuple[tuple[tuple[int, float], ...], ...]] = {}
    for raw_entry in all_entries:
        entry = int(raw_entry)
        config_cache[entry] = base._addon_reference_sets(start, entry)

    rows: dict[int, dict[str, dict[str, object]]] = {}
    for w in WINDOWS:
        end = start + w - 1
        right = int(np.searchsorted(all_entries, end, side="right"))
        entries = all_entries[:right]
        rows[w] = {}
        for name, max_addons, tolerance in POLICIES:
            rows[w][name] = _summarize_policy_window(
                start,
                end,
                entries,
                config_cache,
                max_addons,
                tolerance,
            )
    return start, rows


def _init_worker(events: pd.DataFrame) -> None:
    base._prepare_worker_state(events)


def _worker_task(start: int) -> tuple[int, dict[int, dict[str, dict[str, object]]]]:
    return _summarize_anchor(start)


def _worker_count() -> int:
    override = os.environ.get("FUTUREVIEW_WORKERS")
    if override is not None:
        workers = int(override)
        if workers < 1:
            raise ValueError("FUTUREVIEW_WORKERS must be >= 1")
        return workers
    return max(1, os.cpu_count() or 1)


def _print_policy(w: int, name: str, rows: list[dict[str, object]], baseline: list[dict[str, object]]) -> None:
    nonempty = [row for row in rows if int(row["return"]["n"]) > 0]  # type: ignore[index]
    if not nonempty:
        return

    def mf(section: str, field: str) -> float:
        return float(np.mean([row[section][field] for row in nonempty]))  # type: ignore[index]

    def medf(section: str, field: str) -> float:
        return float(np.median([row[section][field] for row in nonempty]))  # type: ignore[index]

    combo_mean = float(np.mean([row["legal_combinations"] for row in rows]))
    executed2_rate = float(
        sum(float(row["executed2"]) for row in rows)
        / max(1.0, sum(float(row["legal_combinations"]) for row in rows))
    )

    total_return = 0.0
    total_exposure = 0.0
    for row in nonempty:
        exposure = float(row["total_exposure_days"])
        total_return += float(row["aggregate_efficiency"]) * exposure
        total_exposure += exposure
    pooled = total_return / total_exposure if total_exposure > 0.0 else 0.0

    baseline_nonempty = [row for row in baseline if int(row["return"]["n"]) > 0]  # type: ignore[index]
    base_upper = float(np.mean([row["return"]["upper"] for row in baseline_nonempty]))  # type: ignore[index]
    base_lower = float(np.mean([row["return"]["lower"] for row in baseline_nonempty]))  # type: ignore[index]
    upper_delta = mf("return", "upper") - base_upper
    lower_delta = mf("return", "lower") - base_lower

    print(
        f"S1 POLICY_COMPARE w={w} policy={name} "
        f"legal_combinations_mean={combo_mean:.3f} addon2_execute_rate={executed2_rate:.4f} "
        f"lower_mean={mf('return','lower'):.6f} upper_mean={mf('return','upper'):.6f} "
        f"upper_vs_max1={upper_delta:.6f} lower_vs_max1={lower_delta:.6f} "
        f"mean_return={mf('return','mean'):.6f} median_return={mf('return','median'):.6f} "
        f"win_rate={mf('return','positive_rate'):.3f} std_mean={mf('return','std'):.6f} "
        f"iqr_mean={mf('return','iqr'):.6f} "
        f"efficiency_mean={mf('efficiency','mean'):.6f} "
        f"efficiency_median={mf('efficiency','median'):.6f} "
        f"efficiency_pooled={pooled:.6f} "
        f"upper_median={medf('return','upper'):.6f} lower_median={medf('return','lower'):.6f}"
    )


def main() -> None:
    df = download_spy_daily(period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = base.add_strategy1_events(df).reset_index(drop=True)
    max_window = max(WINDOWS)
    anchor_count = len(events) - max_window + 1
    workers = _worker_count()

    print(
        "S1 POLICY_COMPARE DATA "
        f"period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"windows={','.join(str(w) for w in WINDOWS)} workers={workers} "
        "baseline=max1 policies=max1,unrestricted,spacing10,spacing20,spacing30"
    )
    print(
        "S1 POLICY_COMPARE RULE "
        "max1=legal_zero_or_one_addon_configs "
        "unrestricted=legal_zero_one_two_addon_configs "
        "spacing=full_config_universe_with_realized_addon2_equal_price_step_filter "
        "comparison=full_reference_distribution_all_anchors"
    )

    aggregate: dict[int, dict[str, list[dict[str, object]]]] = {
        w: {name: [] for name, _, _ in POLICIES} for w in WINDOWS
    }
    starts = list(range(anchor_count))

    if workers == 1:
        base._prepare_worker_state(events)
        results = map(_worker_task, starts)
        for _, rows_by_window in results:
            for w in WINDOWS:
                for name, _, _ in POLICIES:
                    aggregate[w][name].append(rows_by_window[w][name])
    else:
        chunksize = max(1, len(starts) // (workers * 8))
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_worker,
            initargs=(events,),
        ) as pool:
            for _, rows_by_window in pool.map(_worker_task, starts, chunksize=chunksize):
                for w in WINDOWS:
                    for name, _, _ in POLICIES:
                        aggregate[w][name].append(rows_by_window[w][name])

    for w in WINDOWS:
        baseline = aggregate[w]["max1"]
        for name, _, _ in POLICIES:
            _print_policy(w, name, aggregate[w][name], baseline)

    print("S1 POLICY_COMPARE COMPLETE")


if __name__ == "__main__":
    main()

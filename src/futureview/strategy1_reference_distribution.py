from __future__ import annotations

import numpy as np

from .data import download_spy_daily, validate_daily_ohlcv
from .strategy1 import LOCAL_MAX_MIN_GAP, _simulate_from_start, add_strategy1_events

DATA_PERIOD = "5y"
WINDOWS = (30, 45, 60, 90)


def _window_local_maxima(events, start: int, entry: int) -> tuple[int, ...]:
    """Confirmed local maxima inside the fixed window and strictly before entry."""
    if entry - start < 2:
        return ()
    close = events["close"].to_numpy(dtype=float)
    maxima: list[int] = []
    first = max(start + 1, 1)
    for i in range(first, entry):
        if close[i] > close[i - 1] and close[i] >= close[i + 1]:
            maxima.append(i)
    return tuple(maxima)


def _addon_reference_sets(events, start: int, entry: int) -> tuple[tuple[tuple[int, float], ...], ...]:
    """All zero/one/two-addon reference configurations legal at this entry."""
    maxima = _window_local_maxima(events, start, entry)
    levels = [(i, float(events.at[i, "close"])) for i in maxima]
    configs: list[tuple[tuple[int, float], ...]] = [()]

    # Optional one-addon paths.
    configs.extend(((level,),) for level in [])  # type marker; replaced below
    for level in levels:
        configs.append((level,))

    # Two-addon paths: first reference is the more recent local maximum; the
    # second is an earlier local maximum more than LOCAL_MAX_MIN_GAP sessions away.
    for recent_pos in range(len(levels) - 1, -1, -1):
        recent = levels[recent_pos]
        for older_pos in range(recent_pos - 1, -1, -1):
            older = levels[older_pos]
            if recent[0] - older[0] > LOCAL_MAX_MIN_GAP:
                configs.append((recent, older))

    return tuple(configs)


def _entry_set_outcomes(events, start: int, end: int) -> dict[str, object]:
    returns: list[float] = []
    efficiencies: list[float] = []
    exposure_days: list[float] = []
    entry_count = 0
    local_max_candidate_count = 0
    legal_combinations = 0

    for i in range(start, end + 1):
        if not bool(events.at[i, "entry_candidate"]):
            continue
        entry_count += 1
        maxima = _window_local_maxima(events, start, i)
        local_max_candidate_count += len(maxima)
        configs = _addon_reference_sets(events, start, i)
        legal_combinations += len(configs)

        for addon_levels in configs:
            run = _simulate_from_start(events, i, end, addon_levels=addon_levels)
            returns.append(float(run.final_return))
            efficiencies.append(float(run.return_per_exposure_day))
            exposure_days.append(float(run.exposure_days))

    exit5_candidates = int(events.loc[start:end, "exit5_candidate"].sum())
    exit10_candidates = int(events.loc[start:end, "exit10_candidate"].sum())
    return {
        "returns": np.asarray(returns, dtype=float),
        "efficiencies": np.asarray(efficiencies, dtype=float),
        "exposure_days": np.asarray(exposure_days, dtype=float),
        "entry_count": entry_count,
        "local_max_candidates": local_max_candidate_count,
        "exit5_candidates": exit5_candidates,
        "exit10_candidates": exit10_candidates,
        "legal_combinations": legal_combinations,
    }


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


def main() -> None:
    df = download_spy_daily(period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    max_window = max(WINDOWS)

    print(
        "S1 REFERENCE_DISTRIBUTION DATA "
        f"period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"windows={','.join(str(w) for w in WINDOWS)} model=false target=false"
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

    # Same anchor dates across all windows for direct comparison.
    for start in range(0, len(events) - max_window + 1):
        for w in WINDOWS:
            end = start + w - 1
            outcomes = _entry_set_outcomes(events, start, end)
            returns = outcomes["returns"]
            efficiencies = outcomes["efficiencies"]
            exposure_days = outcomes["exposure_days"]
            assert isinstance(returns, np.ndarray)
            assert isinstance(efficiencies, np.ndarray)
            assert isinstance(exposure_days, np.ndarray)
            return_stats = _stats(returns)
            efficiency_stats = _stats(efficiencies)
            total_exposure = float(exposure_days.sum())
            aggregate_efficiency = (
                float(returns.sum() / total_exposure) if total_exposure > 0.0 else 0.0
            )
            aggregate[w].append(
                {
                    "return": return_stats,
                    "efficiency": efficiency_stats,
                    "aggregate_efficiency": aggregate_efficiency,
                    "total_exposure_days": total_exposure,
                    "entry_count": float(outcomes["entry_count"]),
                    "local_max_candidates": float(outcomes["local_max_candidates"]),
                    "exit5_candidates": float(outcomes["exit5_candidates"]),
                    "exit10_candidates": float(outcomes["exit10_candidates"]),
                    "legal_combinations": float(outcomes["legal_combinations"]),
                }
            )

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

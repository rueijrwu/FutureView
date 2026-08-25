from __future__ import annotations

import numpy as np

from .data import download_spy_daily, validate_daily_ohlcv
from .strategy1 import _simulate_from_start, add_strategy1_events

DATA_PERIOD = "5y"
WINDOWS = (30, 45, 60, 90)


def _entry_set_outcomes(events, start: int, end: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    returns: list[float] = []
    efficiencies: list[float] = []
    exposure_days: list[float] = []
    for i in range(start, end + 1):
        if not bool(events.at[i, "entry1_event"]):
            continue
        run = _simulate_from_start(events, i, end)
        returns.append(float(run.final_return))
        efficiencies.append(float(run.return_per_exposure_day))
        exposure_days.append(float(run.exposure_days))
    return (
        np.asarray(returns, dtype=float),
        np.asarray(efficiencies, dtype=float),
        np.asarray(exposure_days, dtype=float),
    )


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
        "entry_set=all_legal_entry1_inside_fixed_window "
        "entry_return=same_strategy1_mechanics_to_common_window_end "
        "efficiency=entry_return_per_capital_weighted_exposure_day "
        "lower_bound=min_return upper_bound=max_return"
    )

    aggregate: dict[int, list[dict[str, object]]] = {w: [] for w in WINDOWS}

    # Use only anchors with a complete maximum future window so that all window
    # lengths are compared on the same anchor dates.
    for start in range(0, len(events) - max_window + 1):
        for w in WINDOWS:
            end = start + w - 1
            returns, efficiencies, exposure_days = _entry_set_outcomes(events, start, end)
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
                }
            )

    for w in WINDOWS:
        rows = aggregate[w]
        nonempty = [row for row in rows if int(row["return"]["n"]) > 0]  # type: ignore[index]
        if not nonempty:
            raise RuntimeError(f"no non-empty Entry Sets for {w}D")

        def mean_field(group: str, name: str) -> float:
            return float(np.mean([row[group][name] for row in nonempty]))  # type: ignore[index]

        def median_field(group: str, name: str) -> float:
            return float(np.median([row[group][name] for row in nonempty]))  # type: ignore[index]

        all_counts = np.asarray([row["return"]["n"] for row in rows], dtype=float)  # type: ignore[index]
        aggregate_efficiencies = np.asarray(
            [row["aggregate_efficiency"] for row in nonempty], dtype=float
        )
        total_returns = 0.0
        total_exposure = 0.0
        for row in nonempty:
            # Recover the pooled numerator from each window's aggregate efficiency.
            exposure = float(row["total_exposure_days"])
            total_returns += float(row["aggregate_efficiency"]) * exposure
            total_exposure += exposure
        pooled_efficiency = total_returns / total_exposure if total_exposure > 0.0 else 0.0

        print(
            f"S1 REFERENCE_DISTRIBUTION WINDOW w={w} "
            f"anchors={len(rows)} nonempty={len(nonempty)} nonempty_rate={len(nonempty)/len(rows):.3f} "
            f"entry_count_mean={all_counts.mean():.3f} entry_count_median={np.median(all_counts):.3f}"
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

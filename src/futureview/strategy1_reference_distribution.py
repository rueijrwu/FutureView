from __future__ import annotations

import numpy as np

from .data import download_spy_daily, validate_daily_ohlcv
from .strategy1 import _simulate_from_start, add_strategy1_events

DATA_PERIOD = "5y"
WINDOWS = (30, 45, 60, 90)


def _entry_set_returns(events, start: int, end: int) -> np.ndarray:
    values: list[float] = []
    for i in range(start, end + 1):
        if not bool(events.at[i, "entry1_event"]):
            continue
        run = _simulate_from_start(events, i, end)
        values.append(float(run.final_return))
    return np.asarray(values, dtype=float)


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
            "win_rate": float("nan"),
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
        "win_rate": float((values > 0.0).mean()),
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
        "lower_bound=min_return upper_bound=max_return"
    )

    aggregate: dict[int, list[dict[str, float]]] = {w: [] for w in WINDOWS}

    # Use only anchors with a complete maximum future window so that all window
    # lengths are compared on the same anchor dates.
    for start in range(0, len(events) - max_window + 1):
        for w in WINDOWS:
            end = start + w - 1
            values = _entry_set_returns(events, start, end)
            aggregate[w].append(_stats(values))

    for w in WINDOWS:
        rows = aggregate[w]
        nonempty = [row for row in rows if int(row["n"]) > 0]
        if not nonempty:
            raise RuntimeError(f"no non-empty Entry Sets for {w}D")

        def mean_field(name: str) -> float:
            return float(np.mean([row[name] for row in nonempty]))

        def median_field(name: str) -> float:
            return float(np.median([row[name] for row in nonempty]))

        all_counts = np.asarray([row["n"] for row in rows], dtype=float)
        print(
            f"S1 REFERENCE_DISTRIBUTION WINDOW w={w} "
            f"anchors={len(rows)} nonempty={len(nonempty)} nonempty_rate={len(nonempty)/len(rows):.3f} "
            f"entry_count_mean={all_counts.mean():.3f} entry_count_median={np.median(all_counts):.3f} "
            f"lower_mean={mean_field('lower'):.6f} lower_median={median_field('lower'):.6f} "
            f"upper_mean={mean_field('upper'):.6f} upper_median={median_field('upper'):.6f} "
            f"mean_return_mean={mean_field('mean'):.6f} median_return_mean={mean_field('median'):.6f} "
            f"std_mean={mean_field('std'):.6f} std_median={median_field('std'):.6f} "
            f"p25_mean={mean_field('p25'):.6f} p75_mean={mean_field('p75'):.6f} "
            f"iqr_mean={mean_field('iqr'):.6f} iqr_median={median_field('iqr'):.6f} "
            f"win_rate_mean={mean_field('win_rate'):.3f}"
        )

    print("S1 REFERENCE_DISTRIBUTION COMPLETE")


if __name__ == "__main__":
    main()

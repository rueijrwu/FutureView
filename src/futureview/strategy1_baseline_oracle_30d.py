from __future__ import annotations

import numpy as np
import pandas as pd

from .data import download_spy_daily
from .strategy1_entry_targets import make_entry_event_dataset

DATA_PERIOD = "5y"
LOOKBACK = 50
HORIZON = 30


def _rankdata(values: np.ndarray) -> np.ndarray:
    return pd.Series(values).rank(method="average").to_numpy(dtype=float)


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra = _rankdata(np.asarray(a, dtype=float))
    rb = _rankdata(np.asarray(b, dtype=float))
    if len(ra) < 2 or np.std(ra) < 1e-12 or np.std(rb) < 1e-12:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def _pearson(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if len(a) < 2 or np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _group_line(name: str, mask: np.ndarray, baseline: np.ndarray, oracle: np.ndarray) -> str:
    n = int(mask.sum())
    if n == 0:
        return f"S1 BASELINE_ORACLE GROUP name={name} n=0"
    b = baseline[mask]
    o = oracle[mask]
    gap = o - b
    return (
        f"S1 BASELINE_ORACLE GROUP name={name} n={n} share={n / len(mask):.3f} "
        f"baseline_mean={b.mean():.6f} baseline_win_rate={np.mean(b > 0.0):.3f} "
        f"oracle_mean={o.mean():.6f} oracle_positive_rate={np.mean(o > 0.0):.3f} "
        f"gap_mean={gap.mean():.6f} oracle_match_rate={np.mean(gap <= 1e-12):.3f}"
    )


def main() -> None:
    df = download_spy_daily(period=DATA_PERIOD)
    ds = make_entry_event_dataset(df, lookback=LOOKBACK, horizon=HORIZON)

    baseline = np.asarray(ds.entry_return, dtype=float)
    oracle = np.asarray(ds.oracle_benchmark, dtype=float)
    gap = oracle - baseline

    b_med = float(np.median(baseline))
    o_med = float(np.median(oracle))

    print(
        f"S1 BASELINE_ORACLE DATA period={DATA_PERIOD} horizon={HORIZON} lookback={LOOKBACK} "
        f"samples={len(baseline)} first={ds.dates[0].date()} last={ds.dates[-1].date()} "
        "model=false baseline_is_label=false oracle_is_label=false reference_frame=true"
    )
    print(
        "S1 BASELINE_ORACLE RULE "
        "baseline=this_legal_entry_realized_profit "
        "oracle=future_known_best_legal_profit_same_30d_window "
        "gap=oracle_minus_baseline training_use=false"
    )
    print(
        f"S1 BASELINE_ORACLE SUMMARY "
        f"baseline_mean={baseline.mean():.6f} baseline_median={b_med:.6f} "
        f"baseline_win_rate={np.mean(baseline > 0.0):.3f} "
        f"oracle_mean={oracle.mean():.6f} oracle_median={o_med:.6f} "
        f"oracle_positive_rate={np.mean(oracle > 0.0):.3f} "
        f"gap_mean={gap.mean():.6f} gap_median={np.median(gap):.6f} "
        f"gap_p90={np.quantile(gap, 0.90):.6f} oracle_match_rate={np.mean(gap <= 1e-12):.3f}"
    )
    print(
        f"S1 BASELINE_ORACLE CORRELATION "
        f"baseline_oracle_pearson={_pearson(baseline, oracle):.6f} "
        f"baseline_oracle_spearman={_spearman(baseline, oracle):.6f} "
        f"baseline_gap_pearson={_pearson(baseline, gap):.6f} "
        f"baseline_gap_spearman={_spearman(baseline, gap):.6f}"
    )

    quadrants = {
        "BASELINE_HIGH_ORACLE_HIGH": (baseline > b_med) & (oracle > o_med),
        "BASELINE_HIGH_ORACLE_LOW": (baseline > b_med) & (oracle <= o_med),
        "BASELINE_LOW_ORACLE_HIGH": (baseline <= b_med) & (oracle > o_med),
        "BASELINE_LOW_ORACLE_LOW": (baseline <= b_med) & (oracle <= o_med),
    }
    for name, mask in quadrants.items():
        print(_group_line(name, mask, baseline, oracle))

    timing_sensitive = (baseline <= 0.0) & (oracle > o_med)
    print(_group_line("TIMING_SENSITIVE_BASELINE_NONPOS_ORACLE_ABOVE_MEDIAN", timing_sensitive, baseline, oracle))

    # Opportunity-conditioned baseline behavior using untuned sample terciles.
    q1, q2 = np.quantile(oracle, [1.0 / 3.0, 2.0 / 3.0])
    bins = {
        "ORACLE_LOW_TERCILE": oracle <= q1,
        "ORACLE_MID_TERCILE": (oracle > q1) & (oracle <= q2),
        "ORACLE_HIGH_TERCILE": oracle > q2,
    }
    print(f"S1 BASELINE_ORACLE TERCILE_THRESHOLDS oracle_q33={q1:.6f} oracle_q67={q2:.6f}")
    for name, mask in bins.items():
        print(_group_line(name, mask, baseline, oracle))

    print("S1 BASELINE_ORACLE COMPLETE")


if __name__ == "__main__":
    main()

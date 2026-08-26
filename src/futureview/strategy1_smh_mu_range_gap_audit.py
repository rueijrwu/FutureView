from __future__ import annotations

import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1_success_training import DATA_PERIOD, HORIZON, make_success_dataset

TICKER = "SMH"


def _q(x: np.ndarray, p: float) -> float:
    return float(np.quantile(x, p))


def _stats(name: str, arr: np.ndarray) -> None:
    print(
        f"S1 SMH_MCQ DIST metric={name} mean={np.mean(arr):.6f} std={np.std(arr):.6f} "
        f"p10={_q(arr,0.10):.6f} p25={_q(arr,0.25):.6f} p50={_q(arr,0.50):.6f} "
        f"p75={_q(arr,0.75):.6f} p90={_q(arr,0.90):.6f}"
    )


def main() -> None:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    ds = make_success_dataset(df)

    raw_dates = pd.to_datetime(df["date"]).reset_index(drop=True)
    live_end = raw_dates.iloc[-1]
    live_start = live_end - pd.DateOffset(months=3)
    holdout_positions = np.flatnonzero(raw_dates.to_numpy() >= np.datetime64(live_start))
    holdout_start = int(holdout_positions[0]) if len(holdout_positions) else len(raw_dates)

    raw_idx = np.asarray(ds.raw_indices, dtype=int)
    target_end = raw_idx + HORIZON - 1
    keep = np.flatnonzero(target_end < holdout_start)

    L = np.asarray(ds.entry_lower, dtype=float)[keep]
    mu = np.asarray(ds.net_expected_return, dtype=float)[keep]
    U = np.asarray(ds.entry_upper, dtype=float)[keep]
    dates = pd.to_datetime(np.asarray(ds.dates)[keep])

    C = U - L
    valid = np.isfinite(L) & np.isfinite(mu) & np.isfinite(U) & np.isfinite(C) & (C > 1e-12)
    L, mu, U, C, dates = [x[valid] for x in (L, mu, U, C, dates)]
    Q = (U - mu) / C
    valid2 = np.isfinite(Q)
    L, mu, U, C, Q, dates = [x[valid2] for x in (L, mu, U, C, Q, dates)]

    print(
        "S1 SMH_MCQ DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"history_entries={len(mu)} horizon={HORIZON} "
        f"live_holdout_start={pd.Timestamp(live_start).date()} live_holdout_end={pd.Timestamp(live_end).date()} "
        "history_rule=target_end_strictly_before_live_start"
    )
    print("S1 SMH_MCQ DEF mu=historical_expected_return C=U-L capacity Q=(U-mu)/C quality lower_is_better")

    for name, arr in (("mu", mu), ("C", C), ("Q", Q), ("L", L), ("U", U)):
        _stats(name, arr)

    # Directly test whether small mu is associated with negative-return structure.
    # Use mu deciles so the threshold pattern is visible without assuming a cutoff.
    edges = np.quantile(mu, np.linspace(0.0, 1.0, 11))
    # Avoid duplicate edges causing ambiguous bins; rank-based deciles keep equal counts.
    order = np.argsort(mu, kind="stable")
    decile = np.empty(len(mu), dtype=int)
    for k, idxs in enumerate(np.array_split(order, 10), start=1):
        decile[idxs] = k

    print("S1 SMH_MCQ MU_DECILES fields=bin,n,mu_min,mu_max,mu_mean,Lneg_rate,muneg_rate,Uneg_rate,C_mean,Q_mean")
    for b in range(1, 11):
        m = decile == b
        print(
            f"S1 SMH_MCQ MU_DECILE bin={b} n={int(m.sum())} "
            f"mu_min={np.min(mu[m]):.6f} mu_max={np.max(mu[m]):.6f} mu_mean={np.mean(mu[m]):.6f} "
            f"Lneg_rate={np.mean(L[m] < 0):.6f} muneg_rate={np.mean(mu[m] < 0):.6f} "
            f"Uneg_rate={np.mean(U[m] < 0):.6f} C_mean={np.mean(C[m]):.6f} Q_mean={np.mean(Q[m]):.6f}"
        )

    # Candidate threshold scan: for each mu cutoff, measure the retained sample and downside structure.
    cutoffs = np.quantile(mu, [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90])
    for cutoff in cutoffs:
        m = mu >= cutoff
        print(
            f"S1 SMH_MCQ MU_GATE cutoff={cutoff:.6f} kept={int(m.sum())} kept_rate={np.mean(m):.6f} "
            f"Lneg_rate={np.mean(L[m] < 0):.6f} muneg_rate={np.mean(mu[m] < 0):.6f} "
            f"Uneg_rate={np.mean(U[m] < 0):.6f} mu_mean={np.mean(mu[m]):.6f} "
            f"C_mean={np.mean(C[m]):.6f} Q_mean={np.mean(Q[m]):.6f}"
        )

    print("S1 SMH_MCQ COMPLETE")


if __name__ == "__main__":
    main()

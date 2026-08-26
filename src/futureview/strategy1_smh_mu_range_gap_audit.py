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

    mu_cut = np.quantile(mu, [1/3, 2/3])
    c_cut = np.quantile(C, [1/3, 2/3])
    q_cut = np.quantile(Q, [1/3, 2/3])
    mu_bin = np.digitize(mu, mu_cut, right=True) + 1
    c_bin = np.digitize(C, c_cut, right=True) + 1
    q_bin = np.digitize(Q, q_cut, right=True) + 1
    print(
        f"S1 SMH_MCQ CUTS mu33={mu_cut[0]:.6f} mu67={mu_cut[1]:.6f} "
        f"C33={c_cut[0]:.6f} C67={c_cut[1]:.6f} Q33={q_cut[0]:.6f} Q67={q_cut[1]:.6f}"
    )

    # Within each historical-mu regime, summarize C x Q corners.
    for mb in (1, 2, 3):
        for cb, qb, label in ((3,1,"HIGH_C_LOW_Q"),(3,3,"HIGH_C_HIGH_Q"),(1,1,"LOW_C_LOW_Q"),(1,3,"LOW_C_HIGH_Q")):
            m = (mu_bin == mb) & (c_bin == cb) & (q_bin == qb)
            if not np.any(m):
                print(f"S1 SMH_MCQ CELL mu_bin={mb} name={label} n=0")
                continue
            print(
                f"S1 SMH_MCQ CELL mu_bin={mb} name={label} n={int(m.sum())} "
                f"mu_mean={np.mean(mu[m]):.6f} mu_median={np.median(mu[m]):.6f} "
                f"C_mean={np.mean(C[m]):.6f} Q_mean={np.mean(Q[m]):.6f} "
                f"L_mean={np.mean(L[m]):.6f} U_mean={np.mean(U[m]):.6f}"
            )

    # Overall economically interesting corners.
    cases = {
        "HIGH_MU_HIGH_C_LOW_Q": (mu_bin == 3) & (c_bin == 3) & (q_bin == 1),
        "HIGH_MU_HIGH_C_HIGH_Q": (mu_bin == 3) & (c_bin == 3) & (q_bin == 3),
        "LOW_MU_HIGH_C_LOW_Q": (mu_bin == 1) & (c_bin == 3) & (q_bin == 1),
        "LOW_MU_HIGH_C_HIGH_Q": (mu_bin == 1) & (c_bin == 3) & (q_bin == 3),
    }
    for label, m in cases.items():
        if not np.any(m):
            print(f"S1 SMH_MCQ CASE name={label} n=0")
            continue
        print(
            f"S1 SMH_MCQ CASE name={label} n={int(m.sum())} "
            f"mu_mean={np.mean(mu[m]):.6f} C_mean={np.mean(C[m]):.6f} Q_mean={np.mean(Q[m]):.6f} "
            f"L_mean={np.mean(L[m]):.6f} U_mean={np.mean(U[m]):.6f}"
        )

    for label, idxs in (
        ("LOWEST_Q", np.argsort(Q)[:5]),
        ("HIGHEST_C", np.argsort(C)[-5:][::-1]),
        ("HIGHEST_MU", np.argsort(mu)[-5:][::-1]),
    ):
        for rank, j in enumerate(idxs, start=1):
            print(
                f"S1 SMH_MCQ EXAMPLE side={label} rank={rank} date={pd.Timestamp(dates[j]).date()} "
                f"mu={mu[j]:.6f} C={C[j]:.6f} Q={Q[j]:.6f} L={L[j]:.6f} U={U[j]:.6f}"
            )

    print("S1 SMH_MCQ COMPLETE")


if __name__ == "__main__":
    main()

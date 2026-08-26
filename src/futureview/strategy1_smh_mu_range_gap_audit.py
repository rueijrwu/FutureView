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
        f"S1 SMH_DA DIST metric={name} mean={np.mean(arr):.6f} "
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

    D = np.abs(U - mu)
    A = U - L
    valid = np.isfinite(L) & np.isfinite(mu) & np.isfinite(U) & np.isfinite(D) & np.isfinite(A) & (A >= -1e-12)
    L, mu, U, D, A, dates = [x[valid] for x in (L, mu, U, D, A, dates)]

    print(
        "S1 SMH_DA DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"history_entries={len(mu)} horizon={HORIZON} "
        f"live_holdout_start={pd.Timestamp(live_start).date()} live_holdout_end={pd.Timestamp(live_end).date()} "
        "history_rule=target_end_strictly_before_live_start"
    )
    print("S1 SMH_DA DEF D=abs(U-mu) name=optimality_gap lower_is_better A=U-L name=profit_capacity higher_is_better")

    for name, arr in (("L", L), ("mu", mu), ("U", U), ("D", D), ("A", A)):
        _stats(name, arr)

    d_cut = np.quantile(D, [1/3, 2/3])
    a_cut = np.quantile(A, [1/3, 2/3])
    d_bin = np.digitize(D, d_cut, right=True) + 1
    a_bin = np.digitize(A, a_cut, right=True) + 1
    print(f"S1 SMH_DA CUTS D33={d_cut[0]:.6f} D67={d_cut[1]:.6f} A33={a_cut[0]:.6f} A67={a_cut[1]:.6f}")

    for db in (1, 2, 3):
        for ab in (1, 2, 3):
            m = (d_bin == db) & (a_bin == ab)
            if not np.any(m):
                continue
            print(
                f"S1 SMH_DA CELL Dbin={db} Abin={ab} n={int(m.sum())} "
                f"D_mean={np.mean(D[m]):.6f} A_mean={np.mean(A[m]):.6f} "
                f"mu_mean={np.mean(mu[m]):.6f} mu_median={np.median(mu[m]):.6f} mu_positive_rate={np.mean(mu[m] > 0):.6f} "
                f"L_mean={np.mean(L[m]):.6f} U_mean={np.mean(U[m]):.6f}"
            )

    cases = {
        "LOW_D_HIGH_A": (d_bin == 1) & (a_bin == 3),
        "LOW_D_LOW_A": (d_bin == 1) & (a_bin == 1),
        "HIGH_D_HIGH_A": (d_bin == 3) & (a_bin == 3),
        "HIGH_D_LOW_A": (d_bin == 3) & (a_bin == 1),
    }
    for label, m in cases.items():
        if not np.any(m):
            print(f"S1 SMH_DA CASE name={label} n=0")
            continue
        print(
            f"S1 SMH_DA CASE name={label} n={int(m.sum())} "
            f"D_mean={np.mean(D[m]):.6f} A_mean={np.mean(A[m]):.6f} "
            f"mu_mean={np.mean(mu[m]):.6f} L_mean={np.mean(L[m]):.6f} U_mean={np.mean(U[m]):.6f}"
        )

    for label, idxs in (
        ("BEST_D", np.argsort(D)[:5]),
        ("BEST_A", np.argsort(A)[-5:][::-1]),
        ("TOP_MU", np.argsort(mu)[-5:][::-1]),
    ):
        for rank, j in enumerate(idxs, start=1):
            print(
                f"S1 SMH_DA EXAMPLE side={label} rank={rank} date={pd.Timestamp(dates[j]).date()} "
                f"L={L[j]:.6f} mu={mu[j]:.6f} U={U[j]:.6f} D={D[j]:.6f} A={A[j]:.6f}"
            )

    print("S1 SMH_DA COMPLETE")


if __name__ == "__main__":
    main()

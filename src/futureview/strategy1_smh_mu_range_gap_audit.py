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
        f"S1 SMH_ME DIST metric={name} mean={np.mean(arr):.6f} "
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

    span = U - L
    valid = np.isfinite(L) & np.isfinite(mu) & np.isfinite(U) & (span > 1e-12)
    L, mu, U, span, dates = [x[valid] for x in (L, mu, U, span, dates)]
    E = (mu - L) / span

    print(
        "S1 SMH_ME DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"history_entries={len(mu)} horizon={HORIZON} "
        f"live_holdout_start={pd.Timestamp(live_start).date()} live_holdout_end={pd.Timestamp(live_end).date()} "
        "history_rule=target_end_strictly_before_live_start"
    )
    print("S1 SMH_ME DEF mu=expected_return E=(mu-L)/(U-L) no_composite_indicator=true")

    for name, arr in (("L",L),("mu",mu),("U",U),("E",E)):
        _stats(name, arr)

    mu_cut = np.quantile(mu, [1/3, 2/3])
    e_cut = np.quantile(E, [1/3, 2/3])
    mu_bin = np.digitize(mu, mu_cut, right=True) + 1
    e_bin = np.digitize(E, e_cut, right=True) + 1
    print(f"S1 SMH_ME CUTS mu33={mu_cut[0]:.6f} mu67={mu_cut[1]:.6f} E33={e_cut[0]:.6f} E67={e_cut[1]:.6f}")

    for mb in (1,2,3):
        for eb in (1,2,3):
            m = (mu_bin == mb) & (e_bin == eb)
            if not np.any(m):
                continue
            print(
                f"S1 SMH_ME CELL mubin={mb} Ebin={eb} n={int(m.sum())} "
                f"mu_mean={np.mean(mu[m]):.6f} mu_median={np.median(mu[m]):.6f} "
                f"E_mean={np.mean(E[m]):.6f} E_median={np.median(E[m]):.6f} "
                f"L_mean={np.mean(L[m]):.6f} U_mean={np.mean(U[m]):.6f} "
                f"mu_positive_rate={np.mean(mu[m] > 0):.6f}"
            )

    cases = {
        "HIGH_MU_HIGH_E": (mu_bin == 3) & (e_bin == 3),
        "HIGH_MU_LOW_E": (mu_bin == 3) & (e_bin == 1),
        "LOW_MU_HIGH_E": (mu_bin == 1) & (e_bin == 3),
        "LOW_MU_LOW_E": (mu_bin == 1) & (e_bin == 1),
    }
    for label, m in cases.items():
        if not np.any(m):
            print(f"S1 SMH_ME CASE name={label} n=0")
            continue
        print(
            f"S1 SMH_ME CASE name={label} n={int(m.sum())} "
            f"mu_mean={np.mean(mu[m]):.6f} E_mean={np.mean(E[m]):.6f} "
            f"L_mean={np.mean(L[m]):.6f} U_mean={np.mean(U[m]):.6f}"
        )

    for label, idxs in (
        ("TOP_MU", np.argsort(mu)[-5:][::-1]),
        ("TOP_E", np.argsort(E)[-5:][::-1]),
    ):
        for rank, j in enumerate(idxs, start=1):
            print(
                f"S1 SMH_ME EXAMPLE side={label} rank={rank} date={pd.Timestamp(dates[j]).date()} "
                f"L={L[j]:.6f} mu={mu[j]:.6f} U={U[j]:.6f} E={E[j]:.6f}"
            )

    print("S1 SMH_ME COMPLETE")


if __name__ == "__main__":
    main()

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
        f"S1 SMH_MRG DIST metric={name} mean={np.mean(arr):.6f} "
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

    R = U - L
    G = U - mu
    valid = np.isfinite(L) & np.isfinite(mu) & np.isfinite(U) & (R >= 0) & (G >= -1e-12)
    L, mu, U, R, G, dates = [x[valid] for x in (L, mu, U, R, G, dates)]

    print(
        "S1 SMH_MRG DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"history_entries={len(mu)} horizon={HORIZON} "
        f"live_holdout_start={pd.Timestamp(live_start).date()} live_holdout_end={pd.Timestamp(live_end).date()} "
        "history_rule=target_end_strictly_before_live_start"
    )
    print("S1 SMH_MRG DEF mu=expected_return R=U-L G=U-mu no_composite_indicator=true")

    for name, arr in (("L",L),("mu",mu),("U",U),("R",R),("G",G)):
        _stats(name, arr)

    # 3 x 3 descriptive grid: R tertile x G tertile.
    r_cut = np.quantile(R, [1/3, 2/3])
    g_cut = np.quantile(G, [1/3, 2/3])
    r_bin = np.digitize(R, r_cut, right=True) + 1
    g_bin = np.digitize(G, g_cut, right=True) + 1
    print(f"S1 SMH_MRG CUTS R33={r_cut[0]:.6f} R67={r_cut[1]:.6f} G33={g_cut[0]:.6f} G67={g_cut[1]:.6f}")

    for rb in (1,2,3):
        for gb in (1,2,3):
            m = (r_bin == rb) & (g_bin == gb)
            if not np.any(m):
                continue
            print(
                f"S1 SMH_MRG CELL Rbin={rb} Gbin={gb} n={int(m.sum())} "
                f"mu_mean={np.mean(mu[m]):.6f} mu_median={np.median(mu[m]):.6f} mu_positive_rate={np.mean(mu[m]>0):.6f} "
                f"L_mean={np.mean(L[m]):.6f} U_mean={np.mean(U[m]):.6f} R_mean={np.mean(R[m]):.6f} G_mean={np.mean(G[m]):.6f}"
            )

    # Direct economic cases.
    cases = {
        "POS_MU_HIGH_R_LOW_G": (mu > 0) & (r_bin == 3) & (g_bin == 1),
        "NEG_MU_HIGH_R_LOW_G": (mu <= 0) & (r_bin == 3) & (g_bin == 1),
        "POS_MU_HIGH_R_HIGH_G": (mu > 0) & (r_bin == 3) & (g_bin == 3),
        "POS_MU_LOW_R_LOW_G": (mu > 0) & (r_bin == 1) & (g_bin == 1),
    }
    for label, m in cases.items():
        if not np.any(m):
            print(f"S1 SMH_MRG CASE name={label} n=0")
            continue
        print(
            f"S1 SMH_MRG CASE name={label} n={int(m.sum())} mu_mean={np.mean(mu[m]):.6f} "
            f"L_mean={np.mean(L[m]):.6f} U_mean={np.mean(U[m]):.6f} R_mean={np.mean(R[m]):.6f} G_mean={np.mean(G[m]):.6f}"
        )

    # Examples: largest positive mu, and high-R/low-G examples.
    for label, idxs in (
        ("TOP_MU", np.argsort(mu)[-5:][::-1]),
        ("HIGH_R_LOW_G", np.flatnonzero((r_bin==3)&(g_bin==1))[:5]),
    ):
        for rank, j in enumerate(idxs, start=1):
            print(
                f"S1 SMH_MRG EXAMPLE side={label} rank={rank} date={pd.Timestamp(dates[j]).date()} "
                f"L={L[j]:.6f} mu={mu[j]:.6f} U={U[j]:.6f} R={R[j]:.6f} G={G[j]:.6f}"
            )

    print("S1 SMH_MRG COMPLETE")


if __name__ == "__main__":
    main()

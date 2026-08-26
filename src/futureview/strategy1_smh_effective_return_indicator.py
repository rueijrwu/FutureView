from __future__ import annotations

import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1_success_training import DATA_PERIOD, HORIZON, make_success_dataset

TICKER = "SMH"


def _q(x: np.ndarray, p: float) -> float:
    return float(np.quantile(x, p))


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
    amount = mu - L
    valid = span > 1e-12
    efficiency = np.full_like(mu, np.nan, dtype=float)
    indicator = np.full_like(mu, np.nan, dtype=float)
    efficiency[valid] = amount[valid] / span[valid]
    indicator[valid] = amount[valid] * efficiency[valid]

    valid_idx = np.flatnonzero(np.isfinite(indicator))
    L = L[valid_idx]
    mu = mu[valid_idx]
    U = U[valid_idx]
    dates = dates[valid_idx]
    span = span[valid_idx]
    amount = amount[valid_idx]
    efficiency = efficiency[valid_idx]
    indicator = indicator[valid_idx]

    print(
        "S1 SMH_IND DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"history_entries={len(indicator)} horizon={HORIZON} "
        f"live_holdout_start={pd.Timestamp(live_start).date()} live_holdout_end={pd.Timestamp(live_end).date()} "
        "history_rule=target_end_strictly_before_live_start"
    )
    print(
        "S1 SMH_IND DEF "
        "amount=mu-L efficiency=(mu-L)/(U-L) indicator=(mu-L)^2/(U-L) "
        "indicator_is_derived_not_model_target=true"
    )

    for name, arr in (
        ("L", L), ("mu", mu), ("U", U), ("span", span),
        ("amount", amount), ("efficiency", efficiency), ("indicator", indicator),
    ):
        print(
            f"S1 SMH_IND DIST metric={name} mean={np.mean(arr):.6f} "
            f"p10={_q(arr,0.10):.6f} p25={_q(arr,0.25):.6f} p50={_q(arr,0.50):.6f} "
            f"p75={_q(arr,0.75):.6f} p90={_q(arr,0.90):.6f}"
        )

    # Quintiles are descriptive only: they show what the derived indicator selects.
    order = np.argsort(indicator, kind="stable")
    groups = np.array_split(order, 5)
    for i, g in enumerate(groups, start=1):
        print(
            f"S1 SMH_IND QUINTILE q={i} n={len(g)} "
            f"indicator_mean={np.mean(indicator[g]):.6f} "
            f"L_mean={np.mean(L[g]):.6f} mu_mean={np.mean(mu[g]):.6f} U_mean={np.mean(U[g]):.6f} "
            f"amount_mean={np.mean(amount[g]):.6f} efficiency_mean={np.mean(efficiency[g]):.6f} "
            f"span_mean={np.mean(span[g]):.6f} mu_positive_rate={np.mean(mu[g] > 0.0):.6f}"
        )

    # Print the strongest and weakest examples for interpretation.
    for label, idxs in (("LOW", order[:5]), ("HIGH", order[-5:][::-1])):
        for rank, j in enumerate(idxs, start=1):
            print(
                f"S1 SMH_IND EXAMPLE side={label} rank={rank} date={pd.Timestamp(dates[j]).date()} "
                f"L={L[j]:.6f} mu={mu[j]:.6f} U={U[j]:.6f} amount={amount[j]:.6f} "
                f"efficiency={efficiency[j]:.6f} indicator={indicator[j]:.6f}"
            )

    print("S1 SMH_IND COMPLETE")


if __name__ == "__main__":
    main()

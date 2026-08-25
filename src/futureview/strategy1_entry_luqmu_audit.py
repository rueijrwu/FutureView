from __future__ import annotations

import os

import numpy as np

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1_success_training import DATA_PERIOD, make_success_dataset


def _pct(values: np.ndarray, q: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=float), q))


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if len(a) < 2 or np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _fmt(v: float) -> str:
    return "nan" if not np.isfinite(v) else f"{v:.6f}"


def main() -> None:
    ticker = os.environ.get("FUTUREVIEW_TICKER", "QQQ").strip().upper()
    if not ticker:
        raise ValueError("FUTUREVIEW_TICKER must be non-empty")

    df = download_ticker_daily(ticker, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    ds = make_success_dataset(df)

    q = np.asarray(ds.success_probability, dtype=float)
    mu = np.asarray(ds.net_expected_return, dtype=float)
    l = np.asarray(ds.entry_lower, dtype=float)
    u = np.asarray(ds.entry_upper, dtype=float)
    spread = u - l
    n = np.asarray(ds.path_count, dtype=int)

    print(
        "S1 ENTRY_LUQMU DATA "
        f"ticker={ticker} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"entries={len(q)} horizon=60 weighting=unique_legal_realized_paths model=false"
    )
    print(
        "S1 ENTRY_LUQMU SUMMARY "
        f"L_mean={np.mean(l):.6f} L_median={np.median(l):.6f} L_p10={_pct(l,0.10):.6f} L_p90={_pct(l,0.90):.6f} "
        f"U_mean={np.mean(u):.6f} U_median={np.median(u):.6f} U_p10={_pct(u,0.10):.6f} U_p90={_pct(u,0.90):.6f} "
        f"Q_mean={np.mean(q):.6f} Q_median={np.median(q):.6f} Q_p10={_pct(q,0.10):.6f} Q_p90={_pct(q,0.90):.6f} "
        f"mu_mean={np.mean(mu):.6f} mu_median={np.median(mu):.6f} mu_p10={_pct(mu,0.10):.6f} mu_p90={_pct(mu,0.90):.6f} "
        f"spread_mean={np.mean(spread):.6f} spread_median={np.median(spread):.6f} "
        f"paths_mean={np.mean(n):.3f} paths_median={np.median(n):.3f}"
    )

    robust_good = l > 0.0
    no_opportunity = u <= 0.0
    mixed = (l <= 0.0) & (u > 0.0)
    q_high_mu_pos = (q >= 0.75) & (mu > 0.0)
    q_high_mu_nonpos = (q >= 0.75) & (mu <= 0.0)
    q_low_mu_pos = (q <= 0.25) & (mu > 0.0)
    q_low_mu_nonpos = (q <= 0.25) & (mu <= 0.0)

    def count_rate(mask: np.ndarray) -> tuple[int, float]:
        c = int(np.sum(mask))
        return c, float(c / len(q))

    for name, mask in (
        ("robust_good_L_gt_0", robust_good),
        ("no_opportunity_U_le_0", no_opportunity),
        ("mixed_L_le_0_U_gt_0", mixed),
        ("Q_ge_075_mu_gt_0", q_high_mu_pos),
        ("Q_ge_075_mu_le_0", q_high_mu_nonpos),
        ("Q_le_025_mu_gt_0", q_low_mu_pos),
        ("Q_le_025_mu_le_0", q_low_mu_nonpos),
    ):
        c, r = count_rate(mask)
        if c:
            print(
                f"S1 ENTRY_LUQMU GROUP name={name} n={c} rate={r:.6f} "
                f"L_mean={np.mean(l[mask]):.6f} U_mean={np.mean(u[mask]):.6f} "
                f"Q_mean={np.mean(q[mask]):.6f} mu_mean={np.mean(mu[mask]):.6f} "
                f"spread_mean={np.mean(spread[mask]):.6f}"
            )
        else:
            print(f"S1 ENTRY_LUQMU GROUP name={name} n=0 rate=0.000000")

    print(
        "S1 ENTRY_LUQMU RELATION "
        f"corr_L_Q={_fmt(_corr(l,q))} corr_U_Q={_fmt(_corr(u,q))} "
        f"corr_L_mu={_fmt(_corr(l,mu))} corr_U_mu={_fmt(_corr(u,mu))} "
        f"corr_Q_mu={_fmt(_corr(q,mu))} corr_spread_Q={_fmt(_corr(spread,q))} "
        f"corr_spread_mu={_fmt(_corr(spread,mu))}"
    )
    print("S1 ENTRY_LUQMU PASS")


if __name__ == "__main__":
    main()

from __future__ import annotations

import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_causal_pipeline import build_complete_window_cq
from .strategy1_exit_window_cq_audit import classify_causal

TICKER = "TSLA"
PERIOD = "8y"
W = 30
RETRAIN_DAYS = 15
L2_TRAIN_W = 30
LAGS = (15, 30)


def corr_line(df: pd.DataFrame, a: str, b: str, scope: str) -> None:
    x = df[a].to_numpy(float)
    y = df[b].to_numpy(float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3:
        print(f"S1 W30 CORR scope={scope} a={a} b={b} n={ok.sum()} pearson=nan spearman=nan")
        return
    xa = pd.Series(x[ok])
    ya = pd.Series(y[ok])
    print(
        f"S1 W30 CORR scope={scope} a={a} b={b} n={ok.sum()} "
        f"pearson={xa.corr(ya, method='pearson'):.6f} "
        f"spearman={xa.corr(ya, method='spearman'):.6f}"
    )


def lag_pairs(frame: pd.DataFrame, lag: int) -> pd.DataFrame:
    left = frame[["end_index", "U", "C", "Q"]].copy()
    right = frame[["end_index", "U", "C", "Q"]].copy()
    right["end_index"] = right["end_index"].astype(int) - lag
    right = right.rename(columns={"U": "U_f", "C": "C_f", "Q": "Q_f"})
    return left.merge(right, on="end_index", how="inner")


def main() -> None:
    df = download_ticker_daily(TICKER, period=PERIOD).reset_index(drop=True)
    req = ["open", "high", "low", "close", "volume"]
    bad = df[req].isna().any(axis=1)
    if bad.any():
        print(f"S1 W30 DATA dropped_missing_rows={int(bad.sum())}")
        df = df.loc[~bad].reset_index(drop=True)
    validate_daily_ohlcv(df, minimum_rows=1800)

    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    cq = build_complete_window_cq(df, paths, membership="entry", window=W)
    cq = cq.sort_values("end_index").reset_index(drop=True)
    if cq.empty:
        raise RuntimeError("no complete-path W30 windows")

    # Verify approved complete-path boundary directly.
    if np.any(cq.min_member_entry_index.to_numpy(int) < cq.start_index.to_numpy(int)):
        raise AssertionError("window contains path entry before start")
    if np.any(cq.max_member_exit_index.to_numpy(int) > cq.end_index.to_numpy(int)):
        raise AssertionError("window contains path exit after end")
    if np.any(cq.Q.to_numpy(float) < -1e-12):
        raise AssertionError("approved Q must be non-negative")

    print(
        f"S1 W30 CONFIG ticker={TICKER} period={PERIOD} W={W} "
        f"retrain_days={RETRAIN_DAYS} l2_train_w={L2_TRAIN_W}"
    )
    print(
        f"S1 W30 SUPPORT rows={len(df)} paths={len(paths)} windows={len(cq)} "
        f"path_count_mean={cq.path_count.mean():.6f} path_count_median={cq.path_count.median():.6f} "
        f"path_count_min={int(cq.path_count.min())} path_count_max={int(cq.path_count.max())}"
    )
    for k in ("U", "C", "Q"):
        s = cq[k]
        print(
            f"S1 W30 DIST var={k} mean={s.mean():.6f} std={s.std(ddof=0):.6f} "
            f"p10={s.quantile(.1):.6f} p50={s.quantile(.5):.6f} p90={s.quantile(.9):.6f}"
        )

    for a, b in (("U", "C"), ("U", "Q"), ("C", "Q")):
        corr_line(cq, a, b, "all")

    # State counts use the existing Layer1 classifier, but the C/Q/U values above
    # are the rebuilt complete-path definitions.
    states = classify_causal(cq.rename(columns={"B": "B_periodic"}))
    print(
        "S1 W30 STATE " + " ".join(
            f"{name}={int((states.state == name).sum())}" for name in ("high", "neutral", "low")
        )
    )
    for name in ("high", "neutral", "low"):
        sub = states.loc[states.state.eq(name)]
        if len(sub) >= 3:
            for a, b in (("U", "C"), ("U", "Q"), ("C", "Q")):
                corr_line(sub, a, b, name)

    # Temporal dependence at the proposed 15D retrain cadence and the 30D
    # Layer2 training lookback. These are descriptive structure checks only.
    for lag in LAGS:
        p = lag_pairs(cq, lag)
        print(
            f"S1 W30 LAG lag={lag} pairs={len(p)} window_overlap_sessions={max(W-lag, 0)}"
        )
        for k in ("U", "C", "Q"):
            corr_line(p.rename(columns={f"{k}_f": "future"}), k, "future", f"lag{lag}_{k}_self")
        for a in ("U", "C", "Q"):
            for b in ("U", "C", "Q"):
                corr_line(p.rename(columns={f"{b}_f": "future"}), a, "future", f"lag{lag}_{a}_to_{b}")

    print("S1 W30 COMPLETE")


if __name__ == "__main__":
    main()

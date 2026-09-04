from __future__ import annotations

import os
import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import _periodic_baseline

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
SHORT_REF = int(os.environ.get("FUTUREVIEW_SHORT_REF", "90"))
LONG_REF = int(os.environ.get("FUTUREVIEW_LONG_REF", "756"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-exit-window-cq-audit.csv")


def final_exit_index(paths: pd.DataFrame) -> pd.Series:
    e10 = paths["exit10_index"].astype(int)
    hor = paths["horizon_exit_index"].astype(int)
    out = np.where(e10 >= 0, e10, hor)
    if np.any(out < 0):
        raise RuntimeError("every deterministic path must have a final exit")
    return pd.Series(out, index=paths.index, dtype=int)


def build_exit_window_cq(df: pd.DataFrame, paths: pd.DataFrame, *, window: int) -> pd.DataFrame:
    close = df["close"].to_numpy(dtype=float)
    p = paths.copy()
    p["final_exit_index"] = final_exit_index(p)
    rows: list[dict[str, object]] = []
    for start in range(0, len(df) - window + 1):
        end = start + window - 1
        g = p.loc[(p.final_exit_index >= start) & (p.final_exit_index <= end)]
        if g.empty:
            continue
        r = g["campaign_return"].to_numpy(dtype=float)
        u = float(np.max(r))
        b = float(_periodic_baseline(close, start, end))
        q = float(np.std(r, ddof=0))
        rows.append({
            "start_index": start,
            "end_index": end,
            "start_date": str(pd.Timestamp(df.at[start, "date"]).date()),
            "end_date": str(pd.Timestamp(df.at[end, "date"]).date()),
            "U": u,
            "B_periodic": b,
            "C": u - b,
            "Q": q,
            "path_return_mean": float(np.mean(r)),
            "path_return_median": float(np.median(r)),
            "path_return_min": float(np.min(r)),
            "path_return_max": float(np.max(r)),
            "path_count": int(len(g)),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError("no exit-window observations")
    return out


def classify_causal(wq: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for row in wq.sort_values("start_index").itertuples(index=False):
        s = int(row.start_index)
        prior = wq.loc[wq.end_index.astype(int) < s]
        short = prior.loc[prior.end_index.astype(int) >= s - SHORT_REF]
        long = prior.loc[prior.end_index.astype(int) >= s - LONG_REF]
        if s < LONG_REF or len(short) < 20 or len(long) < 100:
            continue
        c40, c60 = short.C.quantile([0.4, 0.6]).tolist()
        q40, q60 = short.Q.quantile([0.4, 0.6]).tolist()
        c50, q50 = float(long.C.median()), float(long.Q.median())
        high = row.C >= c60 and row.Q <= q60 and row.C > c50 and row.Q < q50
        low = row.C <= c40 and row.Q >= q40 and row.C < c50 and row.Q > q50
        state = "high" if high else "low" if low else "neutral"
        rows.append({**row._asdict(), "state": state})
    return pd.DataFrame(rows)


def main() -> None:
    if W != 30:
        raise ValueError("audit locked to W30")
    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    wq = build_exit_window_cq(df, paths, window=W)
    classified = classify_causal(wq)

    print(f"S1 EXITCQ START ticker={TICKER} rows={audit.rows} paths={len(paths)} usable_windows={len(wq)} classified={len(classified)}")
    print("S1 EXITCQ DEFINITION membership=final_exit_in_W unfinished_paths=excluded U=max_completed_path_return C=U-B_periodic Q=population_std(completed_path_returns)")
    print(f"S1 EXITCQ COVERAGE total_possible={len(df)-W+1} usable={len(wq)} zero_path={(len(df)-W+1)-len(wq)} path_count_mean={wq.path_count.mean():.3f} path_count_median={wq.path_count.median():.3f}")
    for col in ("U", "C", "Q"):
        v = wq[col]
        print(f"S1 EXITCQ DIST metric={col} mean={v.mean():.6f} median={v.median():.6f} p10={v.quantile(.1):.6f} p90={v.quantile(.9):.6f}")
    if len(classified):
        counts = classified.state.value_counts().to_dict()
        print(f"S1 EXITCQ STATES high={counts.get('high',0)} neutral={counts.get('neutral',0)} low={counts.get('low',0)}")
        for state in ("high", "neutral", "low"):
            g = classified[classified.state == state]
            if len(g):
                print(f"S1 EXITCQ STATE state={state} n={len(g)} C_mean={g.C.mean():.6f} Q_mean={g.Q.mean():.6f} U_mean={g.U.mean():.6f} paths_mean={g.path_count.mean():.3f}")

        ordered = classified.sort_values("start_index").reset_index(drop=True)
        pairs = []
        for _, r in ordered.iterrows():
            nxt = ordered.loc[ordered.start_index.astype(int) > int(r.end_index)]
            if nxt.empty:
                continue
            n = nxt.iloc[0]
            pairs.append({"state": r.state, "C": r.C, "Q": r.Q, "U": r.U,
                          "future_C": n.C, "future_Q": n.Q, "future_U": n.U})
        p = pd.DataFrame(pairs)
        if len(p):
            for x in ("C", "Q", "U"):
                for y in ("future_C", "future_Q", "future_U"):
                    rho = p[x].corr(p[y], method="spearman")
                    print(f"S1 EXITCQ FORWARD spearman x={x} y={y} n={len(p)} rho={rho:.6f}")
            for state in ("high", "neutral", "low"):
                g = p[p.state == state]
                if len(g):
                    print(f"S1 EXITCQ FORWARD_STATE state={state} n={len(g)} future_C_mean={g.future_C.mean():.6f} future_Q_mean={g.future_Q.mean():.6f} future_U_mean={g.future_U.mean():.6f}")

    wq.to_csv(OUTPUT, index=False)
    print(f"S1 EXITCQ OUTPUT file={OUTPUT} rows={len(wq)}")
    print("S1 EXITCQ COMPLETE")

if __name__ == "__main__":
    main()

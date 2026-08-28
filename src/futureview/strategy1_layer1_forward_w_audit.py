from __future__ import annotations

import os
import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table
from .strategy1_cq_90d_rank_audit import build_window_q

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
SHORT_REF = int(os.environ.get("FUTUREVIEW_SHORT_REF", "90"))
LONG_REF = int(os.environ.get("FUTUREVIEW_LONG_REF", "756"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer1-forward-w-audit.csv")
LOW_QTL = 0.441
HIGH_QTL = 0.559


def _classify(wq: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in wq.itertuples(index=False):
        s = int(r.start_index)
        prior = wq.loc[wq["end_index"].astype(int) < s]
        short = prior.loc[prior["end_index"].astype(int) >= s - SHORT_REF]
        long = prior.loc[prior["end_index"].astype(int) >= s - LONG_REF]
        if s < LONG_REF or len(short) < 20 or len(long) < 100:
            continue
        c_lo, c_hi = (float(short["C"].quantile(q)) for q in (LOW_QTL, HIGH_QTL))
        q_lo, q_hi = (float(short["Q"].quantile(q)) for q in (LOW_QTL, HIGH_QTL))
        c50 = float(long["C"].median())
        q50 = float(long["Q"].median())
        high = float(r.C) >= c_hi and float(r.Q) <= q_hi and float(r.C) > c50 and float(r.Q) < q50
        low = float(r.C) <= c_lo and float(r.Q) >= q_lo and float(r.C) < c50 and float(r.Q) > q50
        state = "high" if high else ("low" if low else "neutral")
        rows.append({
            "start_index": s,
            "end_index": int(r.end_index),
            "state": state,
            "past_C": float(r.C),
            "past_Q": float(r.Q),
            "past_entries": int(r.entry_count),
        })
    return pd.DataFrame(rows)


def _corr(a: pd.Series, b: pd.Series, method: str) -> float:
    x = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(x) < 3 or x.a.nunique() < 2 or x.b.nunique() < 2:
        return float("nan")
    return float(x.a.corr(x.b, method=method))


def main() -> None:
    if W != 30 or SHORT_REF != 90 or LONG_REF != 756:
        raise ValueError("audit locked to W=30, rolling90, rolling3Y")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    entry_idx = paths["entry_index"].astype(int).to_numpy()

    windows = build_representation_a_table(df, paths, window=W, stride=1, random_samples=20, random_seed=SEED)
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)
    classified = _classify(wq)
    future_by_start = wq.set_index("start_index")

    rows = []
    for r in classified.itertuples(index=False):
        future_start = int(r.end_index) + 1
        future_end = future_start + W - 1
        if future_end >= len(df):
            continue

        future_entries = int(((entry_idx >= future_start) & (entry_idx <= future_end)).sum())
        future_C = float("nan")
        future_Q = float("nan")
        if future_start in future_by_start.index:
            f = future_by_start.loc[future_start]
            if isinstance(f, pd.DataFrame):
                f = f.iloc[0]
            future_C = float(f.C)
            future_Q = float(f.Q)

        rows.append({
            **r._asdict(),
            "future_start": future_start,
            "future_end": future_end,
            "future_C": future_C,
            "future_Q": future_Q,
            "future_entries": future_entries,
        })

    out = pd.DataFrame(rows)
    cq = out.dropna(subset=["future_C", "future_Q"])
    out.to_csv(OUTPUT, index=False)

    print(
        f"S1 L1FW START ticker={TICKER} rows={audit.rows} W={W} "
        f"classified={len(classified)} full_future_W={len(out)} cq_pairs={len(cq)} "
        f"short_qlo={LOW_QTL:.3f} short_qhi={HIGH_QTL:.3f}"
    )
    print(
        "S1 L1FW CORR overall "
        f"C_pearson={_corr(cq.past_C,cq.future_C,'pearson'):.6f} "
        f"C_spearman={_corr(cq.past_C,cq.future_C,'spearman'):.6f} "
        f"Q_pearson={_corr(cq.past_Q,cq.future_Q,'pearson'):.6f} "
        f"Q_spearman={_corr(cq.past_Q,cq.future_Q,'spearman'):.6f} "
        f"entries_pearson={_corr(out.past_entries,out.future_entries,'pearson'):.6f} "
        f"entries_spearman={_corr(out.past_entries,out.future_entries,'spearman'):.6f}"
    )

    for state in ("high", "neutral", "low"):
        g = out.loc[out.state == state]
        gcq = g.dropna(subset=["future_C", "future_Q"])
        if g.empty:
            continue
        print(
            f"S1 L1FW STATE state={state} n={len(g)} cq_n={len(gcq)} "
            f"past_C_mean={g.past_C.mean():.6f} future_C_mean={gcq.future_C.mean():.6f} "
            f"past_Q_mean={g.past_Q.mean():.6f} future_Q_mean={gcq.future_Q.mean():.6f} "
            f"past_entries_mean={g.past_entries.mean():.3f} future_entries_mean={g.future_entries.mean():.3f} "
            f"future_entries_median={g.future_entries.median():.3f} future_entries_zero={(g.future_entries==0).mean():.6f}"
        )
        print(
            f"S1 L1FW STATECORR state={state} "
            f"C_pearson={_corr(gcq.past_C,gcq.future_C,'pearson'):.6f} "
            f"C_spearman={_corr(gcq.past_C,gcq.future_C,'spearman'):.6f} "
            f"Q_pearson={_corr(gcq.past_Q,gcq.future_Q,'pearson'):.6f} "
            f"Q_spearman={_corr(gcq.past_Q,gcq.future_Q,'spearman'):.6f} "
            f"entries_pearson={_corr(g.past_entries,g.future_entries,'pearson'):.6f} "
            f"entries_spearman={_corr(g.past_entries,g.future_entries,'spearman'):.6f}"
        )

    print(f"S1 L1FW OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 L1FW COMPLETE")


if __name__ == "__main__":
    main()

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


def _classify(wq: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in wq.itertuples(index=False):
        s = int(r.start_index)
        prior = wq.loc[wq["end_index"].astype(int) < s]
        short = prior.loc[prior["end_index"].astype(int) >= s - SHORT_REF]
        long = prior.loc[prior["end_index"].astype(int) >= s - LONG_REF]
        if s < LONG_REF or len(short) < 20 or len(long) < 100:
            continue
        c40, c60 = (float(short["C"].quantile(q)) for q in (0.40, 0.60))
        q40, q60 = (float(short["Q"].quantile(q)) for q in (0.40, 0.60))
        c50 = float(long["C"].median())
        q50 = float(long["Q"].median())
        high = float(r.C) >= c60 and float(r.Q) <= q60 and float(r.C) > c50 and float(r.Q) < q50
        low = float(r.C) <= c40 and float(r.Q) >= q40 and float(r.C) < c50 and float(r.Q) > q50
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
    if len(a) < 3 or a.nunique() < 2 or b.nunique() < 2:
        return float("nan")
    return float(a.corr(b, method=method))


def main() -> None:
    if W != 30 or SHORT_REF != 90 or LONG_REF != 756:
        raise ValueError("audit locked to W=30, rolling90, rolling3Y")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(df, paths, window=W, stride=1, random_samples=20, random_seed=SEED)
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)
    classified = _classify(wq)

    future_by_start = wq.set_index("start_index")
    rows = []
    for r in classified.itertuples(index=False):
        future_start = int(r.end_index) + 1
        future_end = future_start + W - 1
        if future_start not in future_by_start.index or future_end >= len(df):
            continue
        f = future_by_start.loc[future_start]
        if isinstance(f, pd.DataFrame):
            f = f.iloc[0]
        rows.append({
            **r._asdict(),
            "future_start": future_start,
            "future_end": future_end,
            "future_C": float(f.C),
            "future_Q": float(f.Q),
            "future_entries": int(f.entry_count),
        })

    out = pd.DataFrame(rows)
    out.to_csv(OUTPUT, index=False)

    print(
        f"S1 L1FW START ticker={TICKER} rows={audit.rows} W={W} "
        f"classified={len(classified)} paired_nonoverlap={len(out)}"
    )
    print(
        "S1 L1FW CORR overall "
        f"C_pearson={_corr(out.past_C,out.future_C,'pearson'):.6f} "
        f"C_spearman={_corr(out.past_C,out.future_C,'spearman'):.6f} "
        f"Q_pearson={_corr(out.past_Q,out.future_Q,'pearson'):.6f} "
        f"Q_spearman={_corr(out.past_Q,out.future_Q,'spearman'):.6f} "
        f"entries_pearson={_corr(out.past_entries,out.future_entries,'pearson'):.6f} "
        f"entries_spearman={_corr(out.past_entries,out.future_entries,'spearman'):.6f}"
    )

    for state in ("high", "neutral", "low"):
        g = out.loc[out.state == state]
        if g.empty:
            continue
        print(
            f"S1 L1FW STATE state={state} n={len(g)} "
            f"past_C_mean={g.past_C.mean():.6f} future_C_mean={g.future_C.mean():.6f} "
            f"past_Q_mean={g.past_Q.mean():.6f} future_Q_mean={g.future_Q.mean():.6f} "
            f"past_entries_mean={g.past_entries.mean():.3f} future_entries_mean={g.future_entries.mean():.3f} "
            f"future_entries_median={g.future_entries.median():.3f} future_entries_zero={(g.future_entries==0).mean():.6f}"
        )
        print(
            f"S1 L1FW STATECORR state={state} "
            f"C_pearson={_corr(g.past_C,g.future_C,'pearson'):.6f} "
            f"C_spearman={_corr(g.past_C,g.future_C,'spearman'):.6f} "
            f"Q_pearson={_corr(g.past_Q,g.future_Q,'pearson'):.6f} "
            f"Q_spearman={_corr(g.past_Q,g.future_Q,'spearman'):.6f} "
            f"entries_pearson={_corr(g.past_entries,g.future_entries,'pearson'):.6f} "
            f"entries_spearman={_corr(g.past_entries,g.future_entries,'spearman'):.6f}"
        )

    print(f"S1 L1FW OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 L1FW COMPLETE")


if __name__ == "__main__":
    main()

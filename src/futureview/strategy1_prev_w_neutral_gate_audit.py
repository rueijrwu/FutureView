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
SHORT_REF = 90
LONG_REF = 756
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-prev-w-neutral-gate-audit.csv")
EPS = 1e-12


def classify_layer1(wq: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in wq.itertuples(index=False):
        s = int(row.start_index)
        prior = wq.loc[wq["end_index"].astype(int) < s]
        short = prior.loc[prior["end_index"].astype(int) >= s - SHORT_REF]
        long = prior.loc[prior["end_index"].astype(int) >= s - LONG_REF]
        if s < LONG_REF or len(short) < 20 or len(long) < 100:
            continue
        c40 = float(short.C.quantile(.40)); c60 = float(short.C.quantile(.60))
        q40 = float(short.Q.quantile(.40)); q60 = float(short.Q.quantile(.60))
        c50 = float(long.C.quantile(.50)); q50 = float(long.Q.quantile(.50))
        high = float(row.C) >= c60 and float(row.Q) <= q60 and float(row.C) > c50 and float(row.Q) < q50
        low = float(row.C) <= c40 and float(row.Q) >= q40 and float(row.C) < c50 and float(row.Q) > q50
        state = "high" if high else "low" if low else "neutral"
        rows.append({"start_index": s, "end_index": int(row.end_index), "state": state,
                     "past_C": float(row.C), "past_Q": float(row.Q)})
    return pd.DataFrame(rows)


def build_centered_entries(df: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    windows = build_representation_a_table(df, paths, window=2*W, stride=1,
                                           random_samples=20, random_seed=SEED)
    by_start = windows.set_index("start_index")
    ret = paths.set_index("entry_index")["campaign_return"]
    rows = []
    for t in paths.entry_index.astype(int):
        s, e = t-W+1, t+W
        if s < 0 or e >= len(df) or s not in by_start.index:
            continue
        wr = by_start.loc[s]
        if isinstance(wr, pd.DataFrame): wr = wr.iloc[0]
        u = float(wr.U); q = u - float(ret.loc[t])
        if q < -EPS: raise RuntimeError(f"Q invariant violated entry={t}")
        if abs(q) <= EPS: q = 0.0
        rows.append({"entry_index": t, "entry_date": str(pd.Timestamp(df.loc[t,"date"]).date()),
                     "C": float(u-wr.B_periodic), "Q": q})
    out = pd.DataFrame(rows).sort_values("entry_index").reset_index(drop=True)
    c40,c60 = float(out.C.quantile(.40)),float(out.C.quantile(.60))
    q40,q60 = float(out.Q.quantile(.40)),float(out.Q.quantile(.60))
    out["label"] = "neutral"
    out.loc[(out.C >= c60) & (out.Q <= q40), "label"] = "good"
    out.loc[(out.C <= c40) & (out.Q >= q60), "label"] = "bad"
    out["non_neutral"] = (out.label != "neutral").astype(int)
    print(f"S1 PWG TARGET thresholds C40={c40:.6f} C60={c60:.6f} Q40={q40:.6f} Q60={q60:.6f} good={(out.label=='good').sum()} bad={(out.label=='bad').sum()} neutral={(out.label=='neutral').sum()}")
    return out


def summarize(name: str, g: pd.DataFrame) -> None:
    if g.empty:
        print(f"S1 PWG GROUP gate={name} n=0")
        return
    print(f"S1 PWG GROUP gate={name} n={len(g)} non_neutral_rate={g.non_neutral.mean():.6f} neutral_rate={(g.label=='neutral').mean():.6f} good_rate={(g.label=='good').mean():.6f} bad_rate={(g.label=='bad').mean():.6f} C_mean={g.C.mean():.6f} Q_mean={g.Q.mean():.6f}")


def main() -> None:
    if W != 30: raise ValueError("audit locked to W=30")
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)

    w30 = build_representation_a_table(df, paths, window=W, stride=1,
                                       random_samples=20, random_seed=SEED)
    wq = build_window_q(w30, paths).sort_values("start_index").reset_index(drop=True)
    gate = classify_layer1(wq)
    centered = build_centered_entries(df, paths)

    # Exact previous W window for Entry t is [t-W, t-1].
    prev = gate.rename(columns={"start_index":"prev_start","end_index":"prev_end","state":"prev_state"}).copy()
    prev["entry_index"] = prev["prev_end"].astype(int) + 1
    merged = centered.merge(prev[["entry_index","prev_start","prev_end","prev_state","past_C","past_Q"]],
                            on="entry_index", how="left")
    matched = merged.loc[merged.prev_state.notna()].copy()
    matched["decision"] = np.where(matched.prev_state.eq("neutral"), "block", "pass")

    print(f"S1 PWG START ticker={TICKER} rows={audit.rows} W={W} centered_entries={len(centered)} layer1_windows={len(gate)} exact_prevW_matches={len(matched)}")
    if matched.empty: raise RuntimeError("no exact previous-W gate matches")
    print(f"S1 PWG BASE n={len(matched)} non_neutral_rate={matched.non_neutral.mean():.6f} neutral_rate={(matched.label=='neutral').mean():.6f}")
    summarize("pass", matched.loc[matched.decision.eq("pass")])
    summarize("block", matched.loc[matched.decision.eq("block")])
    for st in ("high","neutral","low"):
        summarize(st, matched.loc[matched.prev_state.eq(st)])

    p = matched.loc[matched.decision.eq("pass")]
    b = matched.loc[matched.decision.eq("block")]
    pass_lift = p.non_neutral.mean()/matched.non_neutral.mean() if len(p) else np.nan
    block_neutral_lift = (b.label.eq("neutral").mean())/(matched.label.eq("neutral").mean()) if len(b) else np.nan
    print(f"S1 PWG EFFECT pass_non_neutral_lift={pass_lift:.6f} block_neutral_lift={block_neutral_lift:.6f} pass_rate={(matched.decision=='pass').mean():.6f} block_rate={(matched.decision=='block').mean():.6f}")
    print("S1 PWG NOTE association_only=true previous_W_uses_original_layer1_retrospective_CQ=true deployment_causality_not_claimed=true")
    matched.to_csv(OUTPUT,index=False)
    print(f"S1 PWG OUTPUT file={OUTPUT} rows={len(matched)}")
    print("S1 PWG COMPLETE")

if __name__ == "__main__":
    main()

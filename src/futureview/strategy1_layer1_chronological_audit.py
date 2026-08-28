from __future__ import annotations

import os
import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table
from .strategy1_cq_90d_rank_audit import build_window_q
from .strategy1_layer1_forward_w_audit import _classify, _corr

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
SHORT_REF = int(os.environ.get("FUTUREVIEW_SHORT_REF", "90"))
LONG_REF = int(os.environ.get("FUTUREVIEW_LONG_REF", "756"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
FOLDS = int(os.environ.get("FUTUREVIEW_CHRONO_FOLDS", "3"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer1-chronological-audit.csv")


def _q(s: pd.Series, q: float) -> float:
    s = pd.to_numeric(s, errors="coerce").dropna()
    return float(s.quantile(q)) if len(s) else float("nan")


def _fmt_stats(g: pd.DataFrame, c_col: str, q_col: str) -> str:
    return (
        f"C_mean={g[c_col].mean():.6f} C_median={g[c_col].median():.6f} "
        f"C_p25={_q(g[c_col],0.25):.6f} C_p75={_q(g[c_col],0.75):.6f} "
        f"Q_mean={g[q_col].mean():.6f} Q_median={g[q_col].median():.6f} "
        f"Q_p25={_q(g[q_col],0.25):.6f} Q_p75={_q(g[q_col],0.75):.6f}"
    )


def main() -> None:
    if W != 30 or SHORT_REF != 90 or LONG_REF != 756:
        raise ValueError("audit locked to W=30, rolling90 40/60, rolling3Y median")
    if FOLDS < 2:
        raise ValueError("chronological audit requires at least 2 folds")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    entry_idx = paths["entry_index"].astype(int).to_numpy()

    windows = build_representation_a_table(
        df, paths, window=W, stride=1, random_samples=20, random_seed=SEED
    )
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)
    classified = _classify(wq).sort_values("start_index").reset_index(drop=True)
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

    out = pd.DataFrame(rows).sort_values("start_index").reset_index(drop=True)
    if len(out) < FOLDS:
        raise RuntimeError("not enough classified states for requested folds")

    fold_ids = np.empty(len(out), dtype=int)
    for i, idx in enumerate(np.array_split(np.arange(len(out)), FOLDS), start=1):
        fold_ids[idx] = i
    out["fold"] = fold_ids
    out.to_csv(OUTPUT, index=False)

    cq = out.dropna(subset=["future_C", "future_Q"])
    print(
        f"S1 L1CHRONO START ticker={TICKER} rows={audit.rows} W={W} folds={FOLDS} "
        f"classified={len(classified)} complete_future={len(out)} cq_pairs={len(cq)}"
    )
    print(
        "S1 L1CHRONO OVERALL "
        f"high={(out.state=='high').sum()} neutral={(out.state=='neutral').sum()} low={(out.state=='low').sum()} "
        f"C_pearson={_corr(cq.past_C,cq.future_C,'pearson'):.6f} "
        f"C_spearman={_corr(cq.past_C,cq.future_C,'spearman'):.6f} "
        f"Q_pearson={_corr(cq.past_Q,cq.future_Q,'pearson'):.6f} "
        f"Q_spearman={_corr(cq.past_Q,cq.future_Q,'spearman'):.6f}"
    )

    for fold in range(1, FOLDS + 1):
        gfold = out.loc[out.fold == fold]
        start = int(gfold.start_index.min())
        end = int(gfold.end_index.max())
        print(
            f"S1 L1CHRONO FOLD fold={fold} n={len(gfold)} start_index={start} end_index={end} "
            f"high={(gfold.state=='high').sum()} neutral={(gfold.state=='neutral').sum()} low={(gfold.state=='low').sum()}"
        )
        for state in ("high", "neutral", "low"):
            g = gfold.loc[gfold.state == state]
            gcq = g.dropna(subset=["future_C", "future_Q"])
            if g.empty:
                print(f"S1 L1CHRONO STATE fold={fold} state={state} n=0")
                continue
            print(
                f"S1 L1CHRONO STATE fold={fold} state={state} n={len(g)} "
                f"PAST {_fmt_stats(g,'past_C','past_Q')}"
            )
            if gcq.empty:
                print(f"S1 L1CHRONO FUTURE fold={fold} state={state} n=0")
                continue
            print(
                f"S1 L1CHRONO FUTURE fold={fold} state={state} n={len(gcq)} "
                f"{_fmt_stats(gcq,'future_C','future_Q')}"
            )
            print(
                f"S1 L1CHRONO DELTA fold={fold} state={state} "
                f"dC_mean={(gcq.future_C.mean()-gcq.past_C.mean()):.6f} "
                f"dQ_mean={(gcq.future_Q.mean()-gcq.past_Q.mean()):.6f} "
                f"C_pearson={_corr(gcq.past_C,gcq.future_C,'pearson'):.6f} "
                f"Q_pearson={_corr(gcq.past_Q,gcq.future_Q,'pearson'):.6f}"
            )

    print(f"S1 L1CHRONO OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 L1CHRONO COMPLETE")


if __name__ == "__main__":
    main()

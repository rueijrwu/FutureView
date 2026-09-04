from __future__ import annotations

import os
import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_exit_window_cq_audit import final_exit_index, classify_causal
from .strategy1_representation_a import _periodic_baseline

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-entry-exit-cq-compare.csv")


def build_cq(df: pd.DataFrame, paths: pd.DataFrame, *, membership: str) -> pd.DataFrame:
    if membership not in {"entry", "exit"}:
        raise ValueError("membership must be entry or exit")
    close = df["close"].to_numpy(dtype=float)
    p = paths.copy()
    p["final_exit_index"] = final_exit_index(p)
    key = "entry_index" if membership == "entry" else "final_exit_index"
    rows: list[dict[str, object]] = []
    for start in range(0, len(df) - W + 1):
        end = start + W - 1
        g = p.loc[(p[key].astype(int) >= start) & (p[key].astype(int) <= end)]
        if g.empty:
            continue
        r = g["campaign_return"].to_numpy(dtype=float)
        u = float(np.max(r))
        b = float(_periodic_baseline(close, start, end))
        rows.append({
            "start_index": start,
            "end_index": end,
            "start_date": str(pd.Timestamp(df.at[start, "date"]).date()),
            "end_date": str(pd.Timestamp(df.at[end, "date"]).date()),
            "membership": membership,
            "U": u,
            "B": b,
            "C": u - b,
            "Q": float(np.std(r, ddof=0)),
            "path_count": int(len(g)),
            "path_mean": float(np.mean(r)),
            "path_median": float(np.median(r)),
            "path_p20": float(np.quantile(r, 0.20)),
            "path_p80": float(np.quantile(r, 0.80)),
        })
    return pd.DataFrame(rows)


def dist_line(prefix: str, frame: pd.DataFrame, col: str) -> None:
    x = frame[col].astype(float)
    print(
        f"S1 CQ2 DIST membership={prefix} metric={col} n={len(x)} "
        f"mean={x.mean():.6f} p20={x.quantile(.2):.6f} median={x.median():.6f} "
        f"p80={x.quantile(.8):.6f} std={x.std(ddof=0):.6f}"
    )


def main() -> None:
    if W != 30:
        raise ValueError("comparison locked to W30")
    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)

    entry = build_cq(df, paths, membership="entry")
    exit_ = build_cq(df, paths, membership="exit")
    print(
        f"S1 CQ2 START ticker={TICKER} rows={audit.rows} paths={len(paths)} W={W} "
        f"entry_windows={len(entry)} exit_windows={len(exit_)}"
    )
    print("S1 CQ2 DEFINITION common_U=max(path_return) common_B=periodic_W common_C=U-B common_Q=population_std(path_returns) only_membership_diff=entry_vs_final_exit")

    for name, frame in (("entry", entry), ("exit", exit_)):
        for col in ("U", "B", "C", "Q", "path_count"):
            dist_line(name, frame, col)

    paired = entry.merge(exit_, on=["start_index", "end_index"], suffixes=("_entry", "_exit"), how="inner")
    print(f"S1 CQ2 PAIRED n={len(paired)}")
    for col in ("U", "B", "C", "Q", "path_count"):
        a = paired[f"{col}_entry"].astype(float)
        b = paired[f"{col}_exit"].astype(float)
        d = b - a
        pearson = a.corr(b, method="pearson")
        spearman = a.corr(b, method="spearman")
        print(
            f"S1 CQ2 PAIR metric={col} pearson={pearson:.6f} spearman={spearman:.6f} "
            f"exit_minus_entry_mean={d.mean():.6f} median={d.median():.6f} "
            f"p20={d.quantile(.2):.6f} p80={d.quantile(.8):.6f}"
        )

    # Compare causal H/N/L states under identical threshold mechanics.
    ce = classify_causal(entry.rename(columns={"B": "B_periodic"}))
    cx = classify_causal(exit_.rename(columns={"B": "B_periodic"}))
    for name, frame in (("entry", ce), ("exit", cx)):
        counts = frame.state.value_counts().to_dict()
        print(
            f"S1 CQ2 STATES membership={name} classified={len(frame)} "
            f"high={counts.get('high',0)} neutral={counts.get('neutral',0)} low={counts.get('low',0)}"
        )
        for state in ("high", "neutral", "low"):
            g = frame.loc[frame.state == state]
            if len(g):
                print(
                    f"S1 CQ2 STATE membership={name} state={state} n={len(g)} "
                    f"U50={g.U.median():.6f} B50={g.B_periodic.median():.6f} "
                    f"C50={g.C.median():.6f} Q50={g.Q.median():.6f}"
                )

    states = ce[["start_index", "state"]].merge(
        cx[["start_index", "state"]], on="start_index", suffixes=("_entry", "_exit")
    )
    same = float((states.state_entry == states.state_exit).mean()) if len(states) else float("nan")
    nonneutral_entry = states.state_entry != "neutral"
    nonneutral_exit = states.state_exit != "neutral"
    both_non = int((nonneutral_entry & nonneutral_exit).sum())
    union_non = int((nonneutral_entry | nonneutral_exit).sum())
    jaccard = both_non / union_non if union_non else float("nan")
    print(f"S1 CQ2 STATE_OVERLAP n={len(states)} exact_same={same:.6f} nonneutral_jaccard={jaccard:.6f} both_nonneutral={both_non} union_nonneutral={union_non}")

    out = pd.concat([entry, exit_], ignore_index=True)
    out.to_csv(OUTPUT, index=False)
    print(f"S1 CQ2 OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 CQ2 COMPLETE")


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
import numpy as np
import pandas as pd
import torch

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_entry_exit_cq_compare import build_cq
from .strategy1_exit_window_cq_audit import classify_causal
from .strategy1_layer2_price_distribution import PriceDistributionData, MODEL_HISTORY
from .strategy1_layer2_probability_calibration_audit import build_samples
from .strategy1_layer2_loss_competition_audit import train

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
ROLL_DAYS = 15
TRAIN_MEMORY = 150
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer2-consensus-group-audit.csv")


def consensus_label(a: str, b: str) -> str:
    a = str(a); b = str(b)
    if a == "neutral" and b == "neutral":
        return "neutral"
    if {a, b} == {"high", "low"}:
        return "neutral"
    if a == "high" or b == "high":
        return "high"
    if a == "low" or b == "low":
        return "low"
    return "neutral"


def evaluate(out: pd.DataFrame, name: str) -> None:
    if out.empty:
        print(f"S1 GROUP SUMMARY model={name} n=0")
        return
    p = out.pred_p_up.to_numpy(float)
    y = (out.actual_r3.to_numpy(float) > 0).astype(float)
    lo, hi = out.pred_p_up.quantile([0.2, 0.8])
    bottom = out[out.pred_p_up <= lo]
    top = out[out.pred_p_up >= hi]
    rho = float(pd.Series(out.actual_r3).corr(pd.Series(out.pred_p_up), method="spearman"))
    print(
        f"S1 GROUP SUMMARY model={name} n={len(out)} folds={out.fold_id.nunique()} "
        f"pred_mean={p.mean():.6f} observed_up={y.mean():.6f} spearman={rho:.6f}"
    )
    print(
        f"S1 GROUP BUCKET model={name} bottom_n={len(bottom)} bottom_up={(bottom.actual_r3>0).mean():.6f} "
        f"bottom_ret={bottom.actual_r3.mean():.6f} top_n={len(top)} top_up={(top.actual_r3>0).mean():.6f} "
        f"top_ret={top.actual_r3.mean():.6f}"
    )


def main() -> None:
    if MODEL_HISTORY != 90:
        raise ValueError("audit requires established 90D normalized P/V input")
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    validate_daily_ohlcv(df, minimum_rows=1800)
    paths = build_deterministic_path_table(add_strategy1_events(df).reset_index(drop=True))
    ce = classify_causal(build_cq(df, paths, membership="entry").rename(columns={"B": "B_periodic"}))
    cx = classify_causal(build_cq(df, paths, membership="exit").rename(columns={"B": "B_periodic"}))
    states = ce[["start_index", "end_index", "state"]].merge(
        cx[["start_index", "end_index", "state"]],
        on=["start_index", "end_index"], suffixes=("_entry", "_exit")
    ).sort_values("end_index").reset_index(drop=True)
    states["consensus"] = [consensus_label(a,b) for a,b in zip(states.state_entry, states.state_exit)]
    pair_counts = states.groupby(["state_entry","state_exit"]).size().sort_values(ascending=False)
    for (a,b), n in pair_counts.items():
        print(f"S1 GROUP PAIR entry={a} exit={b} n={int(n)} consensus={consensus_label(a,b)}")
    print(f"S1 GROUP LABEL high={(states.consensus=='high').sum()} low={(states.consensus=='low').sum()} neutral={(states.consensus=='neutral').sum()}")

    # build_samples already drops dual-neutral; merge consensus back and explicitly drop any H/L conflicts too.
    data: PriceDistributionData = build_samples(df, states)
    rows = data.rows.copy().reset_index(drop=True)
    lab = states[["end_index","consensus"]].rename(columns={"end_index":"cutoff_index"})
    rows = rows.merge(lab, on="cutoff_index", how="left")
    keep = rows.consensus.isin(["high","low"]).to_numpy()
    rows = rows.loc[keep].reset_index(drop=True)
    x = data.x[torch.from_numpy(np.flatnonzero(keep))]
    yall = data.y[torch.from_numpy(np.flatnonzero(keep))]

    first_cut = int(rows.cutoff_index.min()); last_cut = int(rows.cutoff_index.max())
    all_out = []
    for mode in ("shared", "high", "low"):
        outs=[]; fid=0
        for block_start in range(first_cut, last_cut+1, ROLL_DAYS):
            block_end=min(block_start+ROLL_DAYS-1,last_cut)
            va = (rows.cutoff_index>=block_start)&(rows.cutoff_index<=block_end)
            if mode in ("high","low"):
                va = va & rows.consensus.eq(mode)
            if not va.any():
                continue
            trmask = rows.cutoff_index < block_start
            if mode in ("high","low"):
                trmask = trmask & rows.consensus.eq(mode)
            idx=np.flatnonzero(trmask.to_numpy())
            if len(idx)<TRAIN_MEMORY:
                continue
            tr_idx=idx[-TRAIN_MEMORY:]
            va_idx=np.flatnonzero(va.to_numpy())
            model=train(x[torch.from_numpy(tr_idx)], yall[torch.from_numpy(tr_idx)], 0.5, True)
            model.eval()
            with torch.no_grad():
                _,logit=model(x[torch.from_numpy(va_idx)])
                p=torch.sigmoid(logit).numpy()
            f=rows.iloc[va_idx].copy().reset_index(drop=True)
            f["pred_p_up"]=p; f["model_group"]=mode; f["fold_id"]=fid
            outs.append(f); fid+=1
        if outs:
            out=pd.concat(outs,ignore_index=True).sort_values("cutoff_index").reset_index(drop=True)
            evaluate(out,mode); all_out.append(out)
            if mode=="shared":
                for g in ("high","low"):
                    evaluate(out[out.consensus==g].reset_index(drop=True),f"shared_on_{g}")
    if not all_out:
        raise RuntimeError("no eligible group folds")
    pd.concat(all_out,ignore_index=True).to_csv(OUTPUT,index=False)
    print(f"S1 GROUP OUTPUT file={OUTPUT}")
    print("S1 GROUP COMPLETE")

if __name__ == "__main__":
    main()

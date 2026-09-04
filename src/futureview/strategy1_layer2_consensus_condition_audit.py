from __future__ import annotations

import os
import numpy as np
import pandas as pd
import torch
from torch import nn
import torch.nn.functional as F

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_entry_exit_cq_compare import build_cq
from .strategy1_exit_window_cq_audit import classify_causal
from .strategy1_layer2_price_distribution import MODEL_HISTORY, EPOCHS, LR, SEED, pinball_loss
from .strategy1_layer2_probability_calibration_audit import build_samples
from .strategy1_layer2_consensus_group_audit import consensus_label
from .strategy1_layer2_loss_competition_audit import train as train_baseline

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
ROLL_DAYS = int(os.environ.get("FUTUREVIEW_ROLL_DAYS", "15"))
TRAIN_MEMORY = 150
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer2-consensus-condition-audit.csv")


class ConditionedNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Conv1d(2, 16, 7, padding="same"), nn.GELU(),
            nn.Conv1d(16, 24, 5, padding="same"), nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.shared = nn.Sequential(nn.Linear(25, 24), nn.GELU())
        self.q_center = nn.Linear(24, 1)
        self.q_lower_gap = nn.Linear(24, 1)
        self.q_upper_gap = nn.Linear(24, 1)
        self.up_head = nn.Linear(24, 1)

    def forward(self, x: torch.Tensor, c: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        z = self.encoder(x).squeeze(-1)
        z = self.shared(torch.cat([z, c.view(-1, 1)], dim=1))
        q50 = self.q_center(z)
        q10 = q50 - F.softplus(self.q_lower_gap(z))
        q90 = q50 + F.softplus(self.q_upper_gap(z))
        return torch.cat([q10, q50, q90], dim=1), self.up_head(z).squeeze(1)


def train_conditioned(x: torch.Tensor, y: torch.Tensor, c: torch.Tensor) -> ConditionedNet:
    np.random.seed(SEED); torch.manual_seed(SEED)
    model = ConditionedNet()
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    bce = nn.BCEWithLogitsLoss()
    up = (y > 0).float()
    for _ in range(EPOCHS):
        model.train()
        q, logit = model(x, c)
        loss = pinball_loss(q, y) + 0.5 * bce(logit, up)
        opt.zero_grad(); loss.backward(); opt.step()
    return model


def evaluate(out: pd.DataFrame, name: str) -> None:
    if out.empty:
        print(f"S1 COND SUMMARY model={name} n=0")
        return
    p = out.pred_p_up.to_numpy(float)
    obs = (out.actual_r3.to_numpy(float) > 0).astype(float)
    rho = float(pd.Series(out.actual_r3).corr(pd.Series(out.pred_p_up), method="spearman"))
    brier = float(np.mean((p-obs)**2))
    lo, hi = out.pred_p_up.quantile([.2,.8])
    bottom = out[out.pred_p_up <= lo]; top = out[out.pred_p_up >= hi]
    print(f"S1 COND SUMMARY model={name} n={len(out)} folds={out.fold_id.nunique()} pred_mean={p.mean():.6f} observed_up={obs.mean():.6f} brier={brier:.6f} spearman={rho:.6f}")
    print(f"S1 COND BUCKET model={name} bottom_n={len(bottom)} bottom_up={(bottom.actual_r3>0).mean():.6f} bottom_ret={bottom.actual_r3.mean():.6f} top_n={len(top)} top_up={(top.actual_r3>0).mean():.6f} top_ret={top.actual_r3.mean():.6f}")


def main() -> None:
    if MODEL_HISTORY != 90:
        raise ValueError("audit requires established 90D normalized P/V input")
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    validate_daily_ohlcv(df, minimum_rows=1800)
    paths = build_deterministic_path_table(add_strategy1_events(df).reset_index(drop=True))
    ce = classify_causal(build_cq(df, paths, membership="entry").rename(columns={"B":"B_periodic"}))
    cx = classify_causal(build_cq(df, paths, membership="exit").rename(columns={"B":"B_periodic"}))
    states = ce[["start_index","end_index","state"]].merge(
        cx[["start_index","end_index","state"]], on=["start_index","end_index"], suffixes=("_entry","_exit")
    ).sort_values("end_index").reset_index(drop=True)
    states["consensus"] = [consensus_label(a,b) for a,b in zip(states.state_entry, states.state_exit)]

    data = build_samples(df, states)
    rows = data.rows.copy().reset_index(drop=True)
    labels = states[["end_index","consensus"]].rename(columns={"end_index":"cutoff_index"})
    rows = rows.merge(labels, on="cutoff_index", how="left")
    keep = rows.consensus.isin(["high","low"]).to_numpy()
    idx_keep = np.flatnonzero(keep)
    rows = rows.loc[keep].reset_index(drop=True)
    x = data.x[torch.from_numpy(idx_keep)]
    y = data.y[torch.from_numpy(idx_keep)]
    c = torch.tensor(np.where(rows.consensus.eq("high"), 1.0, -1.0), dtype=torch.float32)

    first_cut = int(rows.cutoff_index.min()); last_cut = int(rows.cutoff_index.max())
    results = []
    for mode in ("baseline", "conditioned"):
        outs=[]; fid=0
        for block_start in range(first_cut, last_cut+1, ROLL_DAYS):
            block_end=min(block_start+ROLL_DAYS-1,last_cut)
            va=(rows.cutoff_index>=block_start)&(rows.cutoff_index<=block_end)
            if not va.any(): continue
            tr_idx=np.flatnonzero((rows.cutoff_index<block_start).to_numpy())
            if len(tr_idx)<TRAIN_MEMORY: continue
            tr_idx=tr_idx[-TRAIN_MEMORY:]; va_idx=np.flatnonzero(va.to_numpy())
            if mode == "baseline":
                model=train_baseline(x[torch.from_numpy(tr_idx)], y[torch.from_numpy(tr_idx)], 0.5, True)
                model.eval()
                with torch.no_grad(): _,logit=model(x[torch.from_numpy(va_idx)])
            else:
                model=train_conditioned(x[torch.from_numpy(tr_idx)], y[torch.from_numpy(tr_idx)], c[torch.from_numpy(tr_idx)])
                model.eval()
                with torch.no_grad(): _,logit=model(x[torch.from_numpy(va_idx)], c[torch.from_numpy(va_idx)])
            f=rows.iloc[va_idx].copy().reset_index(drop=True)
            f["pred_p_up"]=torch.sigmoid(logit).numpy(); f["model"]=mode; f["fold_id"]=fid
            outs.append(f); fid+=1
        if not outs: continue
        out=pd.concat(outs,ignore_index=True).sort_values("cutoff_index").reset_index(drop=True)
        evaluate(out,mode)
        for g in ("high","low"):
            evaluate(out[out.consensus.eq(g)].reset_index(drop=True),f"{mode}_on_{g}")
        results.append(out)
    if not results: raise RuntimeError("no eligible conditioned folds")
    pd.concat(results,ignore_index=True).to_csv(OUTPUT,index=False)
    print(f"S1 COND CONFIG period={DATA_PERIOD} roll_days={ROLL_DAYS} memory={TRAIN_MEMORY}")
    print(f"S1 COND LABEL high={(rows.consensus=='high').sum()} low={(rows.consensus=='low').sum()}")
    print(f"S1 COND OUTPUT file={OUTPUT}")
    print("S1 COND COMPLETE")

if __name__ == "__main__": main()

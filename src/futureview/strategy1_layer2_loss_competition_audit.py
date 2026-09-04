from __future__ import annotations

import os
import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_entry_exit_cq_compare import build_cq
from .strategy1_exit_window_cq_audit import classify_causal
from .strategy1_layer2_price_distribution import (
    EPOCHS, HORIZON, LR, MODEL_HISTORY, SEED, W,
    PriceDistributionData, PriceDistributionNet, pinball_loss,
)
from .strategy1_layer2_probability_calibration_audit import build_samples

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
MIN_TRAIN = int(os.environ.get("FUTUREVIEW_MIN_TRAIN", "100"))
MIN_VALID = int(os.environ.get("FUTUREVIEW_MIN_VALID", "20"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer2-loss-competition-audit.csv")

CONFIGS = (("joint_bce_0p5", 0.5, True), ("joint_bce_1p0", 1.0, True), ("bce_only", 1.0, False))


def train(train_x: torch.Tensor, train_y: torch.Tensor, bce_weight: float, use_quantile: bool) -> PriceDistributionNet:
    np.random.seed(SEED); torch.manual_seed(SEED)
    model = PriceDistributionNet()
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    bce = nn.BCEWithLogitsLoss()
    up = (train_y > 0).float()
    for _ in range(EPOCHS):
        model.train()
        q, logit = model(train_x)
        loss = bce_weight * bce(logit, up)
        if use_quantile:
            loss = loss + pinball_loss(q, train_y)
        opt.zero_grad(); loss.backward(); opt.step()
    return model


def report(config: str, frame: pd.DataFrame) -> None:
    p = frame.pred_p_up.to_numpy(float)
    y = (frame.actual_r3.to_numpy(float) > 0).astype(float)
    rank = float(pd.Series(frame.actual_r3).corr(pd.Series(frame.pred_p_up), method="spearman"))
    brier = float(np.mean((p-y)**2))
    print(f"S1 LOSS SUMMARY config={config} n={len(frame)} pred_mean={p.mean():.6f} observed_up={y.mean():.6f} bias={(p.mean()-y.mean()):.6f} brier={brier:.6f} spearman={rank:.6f}")
    lo, hi = frame.pred_p_up.quantile([0.2, 0.8])
    for name, mask in (("bottom20", frame.pred_p_up <= lo), ("top20", frame.pred_p_up >= hi)):
        g = frame.loc[mask]
        print(f"S1 LOSS BUCKET config={config} bucket={name} n={len(g)} pred_mean={g.pred_p_up.mean():.6f} observed_up={(g.actual_r3>0).mean():.6f}")


def main() -> None:
    if W != 30 or MODEL_HISTORY != 90 or HORIZON != 3:
        raise ValueError("loss competition audit locked to W30/L90/future3")
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    paths = build_deterministic_path_table(add_strategy1_events(df).reset_index(drop=True))
    entry = build_cq(df, paths, membership="entry")
    exit_ = build_cq(df, paths, membership="exit")
    ce = classify_causal(entry.rename(columns={"B":"B_periodic"}))
    cx = classify_causal(exit_.rename(columns={"B":"B_periodic"}))
    states = ce[["start_index","end_index","state"]].merge(cx[["start_index","end_index","state"]], on=["start_index","end_index"], suffixes=("_entry","_exit")).sort_values("end_index")
    data: PriceDistributionData = build_samples(df, states)
    rows = data.rows.copy().reset_index(drop=True)
    rows["year"] = pd.to_datetime(rows.cutoff_date).dt.year.astype(int)
    all_out = []
    for config, weight, use_q in CONFIGS:
        folds = []
        for year in sorted(rows.year.unique()):
            tr = rows.year < year; va = rows.year == year
            if int(tr.sum()) < MIN_TRAIN or int(va.sum()) < MIN_VALID:
                continue
            model = train(data.x[torch.from_numpy(tr.to_numpy(copy=True))], data.y[torch.from_numpy(tr.to_numpy(copy=True))], weight, use_q)
            model.eval()
            with torch.no_grad():
                _, logit = model(data.x[torch.from_numpy(va.to_numpy(copy=True))])
                p = torch.sigmoid(logit).numpy()
            f = rows.loc[va].copy().reset_index(drop=True)
            f["pred_p_up"] = p; f["config"] = config; f["train_n"] = int(tr.sum())
            folds.append(f)
        if not folds:
            continue
        out = pd.concat(folds, ignore_index=True).sort_values("cutoff_index").reset_index(drop=True)
        report(config, out); all_out.append(out)
    if not all_out:
        raise RuntimeError("no eligible folds")
    pd.concat(all_out, ignore_index=True).to_csv(OUTPUT, index=False)
    print(f"S1 LOSS START ticker={TICKER} rows={audit.rows} epochs={EPOCHS}")
    print("S1 LOSS COMPLETE")

if __name__ == "__main__":
    main()

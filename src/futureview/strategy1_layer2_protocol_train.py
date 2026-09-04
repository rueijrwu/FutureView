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
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer2-protocol-train.csv")


def main() -> None:
    if MODEL_HISTORY != 90:
        raise ValueError("protocol training requires the established 90D normalized P/V input")

    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    validate_daily_ohlcv(df, minimum_rows=1800)

    paths = build_deterministic_path_table(add_strategy1_events(df).reset_index(drop=True))
    ce = classify_causal(build_cq(df, paths, membership="entry").rename(columns={"B": "B_periodic"}))
    cx = classify_causal(build_cq(df, paths, membership="exit").rename(columns={"B": "B_periodic"}))
    states = ce[["start_index", "end_index", "state"]].merge(
        cx[["start_index", "end_index", "state"]],
        on=["start_index", "end_index"],
        suffixes=("_entry", "_exit"),
    ).sort_values("end_index")

    # Existing Layer2 model/target implementation is left unchanged here.
    # This runner changes only the protocol: dual-neutral filter, 15D retrain, 150-sample memory.
    data: PriceDistributionData = build_samples(df, states)
    rows = data.rows.copy().reset_index(drop=True)

    first_cut = int(rows.cutoff_index.min())
    last_cut = int(rows.cutoff_index.max())
    outs = []
    fold_id = 0

    for block_start in range(first_cut, last_cut + 1, ROLL_DAYS):
        block_end = min(block_start + ROLL_DAYS - 1, last_cut)
        va = (rows.cutoff_index >= block_start) & (rows.cutoff_index <= block_end)
        if not va.any():
            continue

        # Use only prior selected samples. The current model implementation determines its own target/loss;
        # no new target/loss hyperparameter is introduced by this protocol runner.
        idx = np.flatnonzero((rows.cutoff_index < block_start).to_numpy())
        if len(idx) < TRAIN_MEMORY:
            continue
        tr_idx = idx[-TRAIN_MEMORY:]
        va_idx = np.flatnonzero(va.to_numpy())

        model = train(
            data.x[torch.from_numpy(tr_idx)],
            data.y[torch.from_numpy(tr_idx)],
            0.5,
            True,
        )
        model.eval()
        with torch.no_grad():
            q, logit = model(data.x[torch.from_numpy(va_idx)])
            p = torch.sigmoid(logit).numpy()
            q = q.numpy()

        f = rows.iloc[va_idx].copy().reset_index(drop=True)
        f["pred_q10"] = q[:, 0]
        f["pred_q50"] = q[:, 1]
        f["pred_q90"] = q[:, 2]
        f["pred_p_up"] = p
        f["fold_id"] = fold_id
        f["block_start_index"] = block_start
        f["block_end_index"] = block_end
        f["train_n"] = TRAIN_MEMORY
        outs.append(f)
        fold_id += 1

    if not outs:
        raise RuntimeError("no eligible protocol training folds")

    out = pd.concat(outs, ignore_index=True).sort_values("cutoff_index").reset_index(drop=True)
    out.to_csv(OUTPUT, index=False)

    y = (out.actual_r3.to_numpy(float) > 0).astype(float)
    p = out.pred_p_up.to_numpy(float)
    lo, hi = out.pred_p_up.quantile([0.2, 0.8])
    bottom = out[out.pred_p_up <= lo]
    top = out[out.pred_p_up >= hi]
    print(f"S1 PROTOCOL TRAIN selected={len(rows)} oos={len(out)} folds={fold_id} pred_mean={p.mean():.6f} observed_up={y.mean():.6f}")
    print(f"S1 PROTOCOL BUCKET bottom_up={(bottom.actual_r3>0).mean():.6f} bottom_ret={bottom.actual_r3.mean():.6f} top_up={(top.actual_r3>0).mean():.6f} top_ret={top.actual_r3.mean():.6f}")
    print("S1 PROTOCOL COMPLETE")


if __name__ == "__main__":
    main()

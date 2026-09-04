from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_entry_exit_cq_compare import build_cq
from .strategy1_exit_window_cq_audit import classify_causal
from .strategy1_layer2_price_distribution import (
    EPOCHS,
    HORIZON,
    MODEL_HISTORY,
    SEED,
    W,
    PriceDistributionData,
)
from .strategy1_layer2_probability_calibration_audit import build_samples
from .strategy1_layer2_loss_competition_audit import train

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
ROLL_DAYS = int(os.environ.get("FUTUREVIEW_ROLL_DAYS", "15"))
TRAIN_MEMORY = int(os.environ.get("FUTUREVIEW_TRAIN_MEMORY", "150"))
PURGE_DAYS = int(os.environ.get("FUTUREVIEW_PURGE_DAYS", "3"))
OUTPUT = Path(os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer2-15d150-full-oos.csv"))
MODEL_OUT = Path(os.environ.get("FUTUREVIEW_MODEL_OUT", "strategy1-layer2-15d150-final.pt"))
META_OUT = Path(os.environ.get("FUTUREVIEW_META_OUT", "strategy1-layer2-15d150-final.json"))


def build_data(df: pd.DataFrame) -> PriceDistributionData:
    paths = build_deterministic_path_table(add_strategy1_events(df).reset_index(drop=True))
    ce = classify_causal(build_cq(df, paths, membership="entry").rename(columns={"B": "B_periodic"}))
    cx = classify_causal(build_cq(df, paths, membership="exit").rename(columns={"B": "B_periodic"}))
    states = ce[["start_index", "end_index", "state"]].merge(
        cx[["start_index", "end_index", "state"]],
        on=["start_index", "end_index"],
        suffixes=("_entry", "_exit"),
    ).sort_values("end_index")
    return build_samples(df, states)


def score_model(model, x: torch.Tensor) -> tuple[np.ndarray, np.ndarray]:
    model.eval()
    with torch.no_grad():
        q, logit = model(x)
        p = torch.sigmoid(logit)
    return q.numpy(), p.numpy()


def main() -> None:
    if W != 30 or MODEL_HISTORY != 90 or HORIZON != 3:
        raise ValueError("full train locked to W30/L90/future3")
    if ROLL_DAYS != 15 or TRAIN_MEMORY != 150 or PURGE_DAYS != 3:
        raise ValueError("full train locked to 15D roll / 150 memory / 3D purge")

    torch.set_num_threads(2)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    data = build_data(df)
    rows = data.rows.copy().reset_index(drop=True)
    rows["cutoff_date"] = pd.to_datetime(rows.cutoff_date)

    first_cut = int(rows.cutoff_index.min())
    last_cut = int(rows.cutoff_index.max())
    boundaries = list(range(first_cut, last_cut + 1, ROLL_DAYS))

    oos_parts = []
    fold_id = 0
    for start in boundaries:
        end = min(start + ROLL_DAYS - 1, last_cut)
        va = (rows.cutoff_index >= start) & (rows.cutoff_index <= end)
        if not va.any():
            continue
        eligible = rows.cutoff_index <= (start - PURGE_DAYS - 1)
        tr_candidates = np.flatnonzero(eligible.to_numpy())
        if len(tr_candidates) < TRAIN_MEMORY:
            continue
        tr_idx = tr_candidates[-TRAIN_MEMORY:]
        va_idx = np.flatnonzero(va.to_numpy())
        model = train(
            data.x[torch.from_numpy(tr_idx)],
            data.y[torch.from_numpy(tr_idx)],
            0.5,
            True,
        )
        q, p = score_model(model, data.x[torch.from_numpy(va_idx)])
        f = rows.iloc[va_idx].copy().reset_index(drop=True)
        f["pred_q10"] = q[:, 0]
        f["pred_q50"] = q[:, 1]
        f["pred_q90"] = q[:, 2]
        f["pred_p_up"] = p
        f["fold_id"] = fold_id
        f["block_start_index"] = start
        f["block_end_index"] = end
        f["train_first_cutoff"] = int(rows.iloc[tr_idx[0]].cutoff_index)
        f["train_last_cutoff"] = int(rows.iloc[tr_idx[-1]].cutoff_index)
        f["train_n"] = TRAIN_MEMORY
        oos_parts.append(f)
        fold_id += 1

    if not oos_parts:
        raise RuntimeError("no eligible 15D/150 walk-forward folds")

    oos = pd.concat(oos_parts, ignore_index=True).sort_values("cutoff_index").reset_index(drop=True)
    oos.to_csv(OUTPUT, index=False)

    y = oos.actual_r3.to_numpy(float)
    p = oos.pred_p_up.to_numpy(float)
    obs = (y > 0).astype(float)
    brier = float(np.mean((p - obs) ** 2))
    bias = float(p.mean() - obs.mean())
    spearman = float(pd.Series(y).corr(pd.Series(p), method="spearman"))
    lo, hi = oos.pred_p_up.quantile([0.2, 0.8])
    bottom = oos[oos.pred_p_up <= lo]
    top = oos[oos.pred_p_up >= hi]

    # Final fit for the next deployment interval. Only labels fully realized by the latest data point are allowed.
    final_cut = int(df.index.max())
    eligible_final = rows.cutoff_index <= (final_cut - PURGE_DAYS)
    final_candidates = np.flatnonzero(eligible_final.to_numpy())
    if len(final_candidates) < TRAIN_MEMORY:
        raise RuntimeError("insufficient final eligible training samples")
    final_idx = final_candidates[-TRAIN_MEMORY:]
    final_model = train(
        data.x[torch.from_numpy(final_idx)],
        data.y[torch.from_numpy(final_idx)],
        0.5,
        True,
    )
    torch.save(
        {
            "state_dict": final_model.state_dict(),
            "ticker": TICKER,
            "w": W,
            "model_history": MODEL_HISTORY,
            "horizon": HORIZON,
            "roll_days": ROLL_DAYS,
            "train_memory": TRAIN_MEMORY,
            "purge_days": PURGE_DAYS,
            "epochs": EPOCHS,
            "seed": SEED,
            "train_cutoff_indices": rows.iloc[final_idx].cutoff_index.astype(int).tolist(),
            "train_cutoff_dates": rows.iloc[final_idx].cutoff_date.dt.date.astype(str).tolist(),
        },
        MODEL_OUT,
    )

    meta = {
        "ticker": TICKER,
        "rows": int(audit.rows),
        "selected_samples": int(len(rows)),
        "oos_samples": int(len(oos)),
        "folds": int(fold_id),
        "roll_days": ROLL_DAYS,
        "train_memory": TRAIN_MEMORY,
        "purge_days": PURGE_DAYS,
        "input_history_days": MODEL_HISTORY,
        "target_horizon_days": HORIZON,
        "epochs": EPOCHS,
        "oos_pred_mean": float(p.mean()),
        "oos_observed_up": float(obs.mean()),
        "oos_bias": bias,
        "oos_brier": brier,
        "oos_spearman": spearman,
        "bottom20_up": float((bottom.actual_r3 > 0).mean()),
        "bottom20_mean_return": float(bottom.actual_r3.mean()),
        "top20_up": float((top.actual_r3 > 0).mean()),
        "top20_mean_return": float(top.actual_r3.mean()),
        "final_train_n": TRAIN_MEMORY,
        "final_train_first_date": str(rows.iloc[final_idx[0]].cutoff_date.date()),
        "final_train_last_date": str(rows.iloc[final_idx[-1]].cutoff_date.date()),
        "final_data_date": str(pd.Timestamp(df.iloc[-1]["date"]).date()),
    }
    META_OUT.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(
        f"S1 FULL SUMMARY ticker={TICKER} selected={len(rows)} oos={len(oos)} folds={fold_id} "
        f"pred_mean={p.mean():.6f} observed_up={obs.mean():.6f} bias={bias:.6f} "
        f"brier={brier:.6f} spearman={spearman:.6f}"
    )
    print(
        f"S1 FULL BUCKET bottom_up={(bottom.actual_r3>0).mean():.6f} bottom_ret={bottom.actual_r3.mean():.6f} "
        f"top_up={(top.actual_r3>0).mean():.6f} top_ret={top.actual_r3.mean():.6f}"
    )
    print(
        f"S1 FULL FINAL train_n={TRAIN_MEMORY} first_date={meta['final_train_first_date']} "
        f"last_date={meta['final_train_last_date']} data_date={meta['final_data_date']}"
    )
    print(f"S1 FULL OUTPUT oos={OUTPUT} model={MODEL_OUT} meta={META_OUT}")
    print("S1 FULL COMPLETE")


if __name__ == "__main__":
    main()

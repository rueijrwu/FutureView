from __future__ import annotations

import os

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths_asof import build_deterministic_path_table_asof
from .strategy1_layer1_forward_w_audit import _classify
from .strategy1_layer2_forward_dataset import build_forward_dataset
from .strategy1_layer2_forward_smoke import (
    ForwardCQStateNet,
    build_training_data,
    nonnegative_q,
    weighted_mean,
)
from .strategy1_layer2_rolling_8y import _build_wq_from_paths

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
MODEL_HISTORY = int(os.environ.get("FUTUREVIEW_MODEL_HISTORY", "90"))
TRAIN_YEARS = int(os.environ.get("FUTUREVIEW_TRAIN_YEARS", "5"))
VALID_YEARS = int(os.environ.get("FUTUREVIEW_VALID_YEARS", "1"))
N_DATES = int(os.environ.get("FUTUREVIEW_CONVERGENCE_DATES", "5"))
MAX_EPOCHS = int(os.environ.get("FUTUREVIEW_MAX_EPOCHS", "300"))
LR = float(os.environ.get("FUTUREVIEW_LR", "0.003"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
OUTPUT = os.environ.get("FUTUREVIEW_CONVERGENCE_OUTPUT", "strategy1-layer2-epoch-convergence.csv")


def _train_curve(df: pd.DataFrame, train_rows: pd.DataFrame, *, seed: int) -> pd.DataFrame:
    np.random.seed(seed)
    torch.manual_seed(seed)
    train = build_training_data(df, train_rows)

    c_mu = train.y_cq[:, 0:1].mean(dim=0, keepdim=True)
    c_sd = train.y_cq[:, 0:1].std(dim=0, keepdim=True, unbiased=False)
    c_sd = torch.where(c_sd < 1e-6, torch.ones_like(c_sd), c_sd)
    q_scale = train.y_cq[:, 1:2].std(dim=0, keepdim=True, unbiased=False)
    q_scale = torch.where(q_scale < 1e-6, torch.ones_like(q_scale), q_scale)
    target_c_z = (train.y_cq[:, 0:1] - c_mu) / c_sd
    target_q_scaled = train.y_cq[:, 1:2] / q_scale

    model = ForwardCQStateNet()
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    reg_fn = nn.SmoothL1Loss(reduction="none")
    cls_fn = nn.CrossEntropyLoss(reduction="none")

    rows: list[dict[str, float | int]] = []
    for epoch in range(1, MAX_EPOCHS + 1):
        model.train()
        raw, logits = model(train.x)
        reg_c = reg_fn(raw[:, 0:1], target_c_z).squeeze(1)
        reg_q = reg_fn(nonnegative_q(raw[:, 1:2]), target_q_scaled).squeeze(1)
        cls = cls_fn(logits, train.y_state)

        loss_c = weighted_mean(0.5 * reg_c, train.weight)
        loss_q = weighted_mean(0.5 * reg_q, train.weight)
        loss_cls = weighted_mean(cls, train.weight)
        loss = loss_c + loss_q + loss_cls

        opt.zero_grad()
        loss.backward()
        opt.step()

        rows.append(
            {
                "epoch": epoch,
                "loss_total": float(loss.detach()),
                "loss_C": float(loss_c.detach()),
                "loss_Q": float(loss_q.detach()),
                "loss_HNL": float(loss_cls.detach()),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    if W != 30 or MODEL_HISTORY != 90 or TRAIN_YEARS != 5 or VALID_YEARS != 1:
        raise ValueError("diagnostic locked to W30/L90, five-year training history, final-one-year date sampling")
    if N_DATES != 5 or MAX_EPOCHS != 300:
        raise ValueError("diagnostic locked to five dates and 300 maximum epochs")

    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    dates = pd.to_datetime(df["date"]).reset_index(drop=True)
    events = add_strategy1_events(df).reset_index(drop=True)

    final_date = pd.Timestamp(dates.iloc[-1]).normalize()
    valid_cut = final_date - pd.DateOffset(years=VALID_YEARS)
    candidates = [
        i
        for i in range(MODEL_HISTORY, len(df) - W + 1)
        if pd.Timestamp(dates.iloc[i]) >= valid_cut
    ]
    if len(candidates) < N_DATES:
        raise RuntimeError("not enough dates for convergence diagnostic")

    positions = np.linspace(0, len(candidates) - 1, N_DATES).round().astype(int)
    sample_dates = [candidates[int(p)] for p in positions]

    print(
        f"S1 L2CONV START ticker={TICKER} rows={audit.rows} train_years={TRAIN_YEARS} "
        f"sample_dates={N_DATES} max_epochs={MAX_EPOCHS} W={W} history={MODEL_HISTORY}"
    )

    all_curves: list[pd.DataFrame] = []
    for sample_no, target_start in enumerate(sample_dates, start=1):
        cutoff = target_start - 1
        cutoff_date = pd.Timestamp(dates.iloc[cutoff])
        floor_date = cutoff_date - pd.DateOffset(years=TRAIN_YEARS)

        # The only rolling-specific path rule is the as-of exit cutoff:
        # completed paths are reused; paths whose exit exceeds cutoff are force-closed at cutoff close.
        paths_asof = build_deterministic_path_table_asof(events, asof_index=cutoff)
        wq = _build_wq_from_paths(df, paths_asof, cutoff)
        classified = _classify(wq).sort_values("start_index").reset_index(drop=True)
        forward = build_forward_dataset(classified, cutoff + 1, MODEL_HISTORY)

        # Five years defines the model training-history window; it does not redefine path/C/Q construction.
        target_dates = pd.to_datetime(df.iloc[forward["target_start"].astype(int)]["date"].to_numpy())
        train_rows = forward.loc[target_dates >= floor_date].reset_index(drop=True)
        if len(train_rows) < 100:
            raise RuntimeError(f"too few training samples at cutoff {cutoff_date.date()}: {len(train_rows)}")

        forced_entries = int((paths_asof["exit_mode"] == "forced_asof").sum())
        curve = _train_curve(df, train_rows, seed=SEED + target_start)
        curve.insert(0, "sample_no", sample_no)
        curve.insert(1, "cutoff_index", cutoff)
        curve.insert(2, "cutoff_date", cutoff_date.date().isoformat())
        curve.insert(3, "train_floor_date", floor_date.date().isoformat())
        curve.insert(4, "train_samples", len(train_rows))
        curve.insert(5, "forced_entries", forced_entries)
        all_curves.append(curve)

        for epoch in (1, 5, 10, 20, 30, 50, 75, 100, 150, 200, 250, 300):
            r = curve.loc[curve["epoch"] == epoch].iloc[0]
            print(
                f"S1 L2CONV LOSS sample={sample_no} cutoff={cutoff_date.date()} samples={len(train_rows)} "
                f"forced={forced_entries} epoch={epoch} total={r.loss_total:.8f} C={r.loss_C:.8f} "
                f"Q={r.loss_Q:.8f} HNL={r.loss_HNL:.8f}"
            )

    out = pd.concat(all_curves, ignore_index=True)
    out.to_csv(OUTPUT, index=False)

    for sample_no, g in out.groupby("sample_no", sort=True):
        start = float(g.iloc[0].loss_total)
        last = float(g.iloc[-1].loss_total)
        l50 = float(g.loc[g.epoch == 50, "loss_total"].iloc[0])
        l100 = float(g.loc[g.epoch == 100, "loss_total"].iloc[0])
        l200 = float(g.loc[g.epoch == 200, "loss_total"].iloc[0])
        print(
            f"S1 L2CONV SUMMARY sample={sample_no} cutoff={g.iloc[0].cutoff_date} "
            f"loss1={start:.8f} loss50={l50:.8f} loss100={l100:.8f} loss200={l200:.8f} "
            f"loss300={last:.8f} improve_50_300={l50-last:.8f} improve_100_300={l100-last:.8f}"
        )

    print(f"S1 L2CONV OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 L2CONV COMPLETE")


if __name__ == "__main__":
    main()

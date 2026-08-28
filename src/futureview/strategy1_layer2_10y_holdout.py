from __future__ import annotations

import os

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table
from .strategy1_cq_90d_rank_audit import build_window_q
from .strategy1_layer1_forward_w_audit import _classify
from .strategy1_layer2_forward_dataset import build_forward_dataset
from .strategy1_layer2_forward_smoke import (
    ForwardCQStateNet,
    STATE_TO_ID,
    build_training_data,
    decode_cq,
    nonnegative_q,
    weighted_mean,
)

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "10y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
MODEL_HISTORY = int(os.environ.get("FUTUREVIEW_MODEL_HISTORY", "90"))
NEUTRAL_ALPHA = float(os.environ.get("FUTUREVIEW_NEUTRAL_ALPHA", "0.2"))
EPOCHS = int(os.environ.get("FUTUREVIEW_EPOCHS", "500"))
LR = float(os.environ.get("FUTUREVIEW_LR", "0.003"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260828"))
OUTPUT = os.environ.get("FUTUREVIEW_HOLDOUT_OUTPUT", "strategy1-layer2-10y-holdout.csv")


def _stats(prefix: str, actual: np.ndarray, pred: np.ndarray) -> None:
    diff = pred - actual
    abs_err = np.abs(diff)
    if len(actual) >= 2 and np.std(actual) > 0 and np.std(pred) > 0:
        pearson = float(np.corrcoef(actual, pred)[0, 1])
        spearman = float(pd.Series(actual).corr(pd.Series(pred), method="spearman"))
    else:
        pearson = float("nan")
        spearman = float("nan")
    print(
        f"{prefix} n={len(actual)} actual_mean={actual.mean():.6f} pred_mean={pred.mean():.6f} "
        f"bias={diff.mean():.6f} mae={abs_err.mean():.6f} medae={np.median(abs_err):.6f} "
        f"p75ae={np.quantile(abs_err, 0.75):.6f} p90ae={np.quantile(abs_err, 0.90):.6f} "
        f"pearson={pearson:.6f} spearman={spearman:.6f}"
    )


def main() -> None:
    if DATA_PERIOD != "10y" or W != 30 or MODEL_HISTORY != 90:
        raise ValueError("holdout audit locked to 10y data, W=30, model_history=90")
    if abs(NEUTRAL_ALPHA - 0.2) > 1e-12:
        raise ValueError("holdout audit locked to neutral alpha=0.2")

    np.random.seed(SEED)
    torch.manual_seed(SEED)

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=2000)
    df = df.reset_index(drop=True)
    dates = pd.to_datetime(df["date"])
    final_date = pd.Timestamp(dates.iloc[-1]).normalize()
    cutoff = final_date - pd.DateOffset(years=1)

    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(df, paths, window=W, stride=1, random_samples=20, random_seed=SEED)
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)
    classified = _classify(wq).sort_values("start_index").reset_index(drop=True)
    forward = build_forward_dataset(classified, len(df), MODEL_HISTORY)

    target_start_dates = pd.to_datetime(df.iloc[forward.target_start.astype(int)]["date"].to_numpy())
    target_end_dates = pd.to_datetime(df.iloc[forward.target_end.astype(int)]["date"].to_numpy())
    train_mask = target_end_dates < cutoff
    test_mask = target_start_dates >= cutoff
    boundary_mask = ~(train_mask | test_mask)

    train_forward = forward.loc[train_mask].reset_index(drop=True)
    test_forward = forward.loc[test_mask].reset_index(drop=True)
    if train_forward.empty or test_forward.empty:
        raise RuntimeError("empty train or test split")

    train = build_training_data(df, train_forward)
    test = build_training_data(df, test_forward)

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

    for _ in range(EPOCHS):
        model.train()
        raw, logits = model(train.x)
        pred_c_z = raw[:, 0:1]
        pred_q_scaled = nonnegative_q(raw[:, 1:2])
        reg_c = reg_fn(pred_c_z, target_c_z).squeeze(1)
        reg_q = reg_fn(pred_q_scaled, target_q_scaled).squeeze(1)
        cls_each = cls_fn(logits, train.y_state)
        loss = weighted_mean(0.5 * (reg_c + reg_q) + cls_each, train.weight)
        opt.zero_grad()
        loss.backward()
        opt.step()

    model.eval()
    with torch.no_grad():
        raw, logits = model(test.x)
        pred_cq = decode_cq(raw, c_mu, c_sd, q_scale)
        probs = torch.softmax(logits, dim=1)

    actual = test.y_cq.numpy()
    pred = pred_cq.numpy()
    probs_np = probs.numpy()

    train_start = pd.Timestamp(df.iloc[int(train.rows.target_start.min())]["date"]).date().isoformat()
    train_end = pd.Timestamp(df.iloc[int(train.rows.target_end.max())]["date"]).date().isoformat()
    test_start = pd.Timestamp(df.iloc[int(test.rows.target_start.min())]["date"]).date().isoformat()
    test_end = pd.Timestamp(df.iloc[int(test.rows.target_end.max())]["date"]).date().isoformat()

    print(
        f"S1 L2HOLD START ticker={TICKER} rows={audit.rows} W={W} history={MODEL_HISTORY} "
        f"classified={len(classified)} forward={len(forward)} train={len(train.rows)} test={len(test.rows)} "
        f"boundary_dropped={int(boundary_mask.sum())} alpha={NEUTRAL_ALPHA:.3f} epochs={EPOCHS}"
    )
    print(
        f"S1 L2HOLD SPLIT final_date={final_date.date().isoformat()} cutoff={cutoff.date().isoformat()} "
        f"train_target={train_start}..{train_end} test_target={test_start}..{test_end}"
    )
    print(
        f"S1 L2HOLD QSANITY pred_negative={int((pred[:,1] < 0).sum())} "
        f"actual_zero={int(np.isclose(actual[:,1],0.0,atol=1e-8).sum())} "
        f"pred_zero={int(np.isclose(pred[:,1],0.0,atol=1e-8).sum())} pred_min={pred[:,1].min():.8f}"
    )

    _stats("S1 L2HOLD OVERALL metric=C", actual[:, 0], pred[:, 0])
    _stats("S1 L2HOLD OVERALL metric=Q", actual[:, 1], pred[:, 1])

    rows_out: list[dict[str, object]] = []
    states = test.rows.state.to_numpy()
    for state in ("high", "neutral", "low"):
        mask = states == state
        print(f"S1 L2HOLD STATECOUNT state={state} n={int(mask.sum())}")
        if mask.sum() == 0:
            continue
        _stats(f"S1 L2HOLD STATE state={state} metric=C", actual[mask, 0], pred[mask, 0])
        _stats(f"S1 L2HOLD STATE state={state} metric=Q", actual[mask, 1], pred[mask, 1])

    for i, r in test.rows.iterrows():
        start_idx = int(r.target_start)
        end_idx = int(r.target_end)
        p = probs_np[i]
        rows_out.append({
            "target_start_date": pd.Timestamp(df.iloc[start_idx]["date"]).date().isoformat(),
            "target_end_date": pd.Timestamp(df.iloc[end_idx]["date"]).date().isoformat(),
            "actual_state": str(r.state),
            "sample_weight": 1.0 if str(r.state) in ("high", "low") else NEUTRAL_ALPHA,
            "actual_C": float(actual[i, 0]),
            "pred_C": float(pred[i, 0]),
            "diff_C": float(pred[i, 0] - actual[i, 0]),
            "abs_error_C": float(abs(pred[i, 0] - actual[i, 0])),
            "actual_Q": float(actual[i, 1]),
            "pred_Q": float(pred[i, 1]),
            "diff_Q": float(pred[i, 1] - actual[i, 1]),
            "abs_error_Q": float(abs(pred[i, 1] - actual[i, 1])),
            "P_H": float(p[STATE_TO_ID["high"]]),
            "P_N": float(p[STATE_TO_ID["neutral"]]),
            "P_L": float(p[STATE_TO_ID["low"]]),
        })

    out = pd.DataFrame(rows_out)
    out.to_csv(OUTPUT, index=False)
    print(f"S1 L2HOLD OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 L2HOLD COMPLETE")


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
from dataclasses import dataclass

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

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
MODEL_HISTORY = int(os.environ.get("FUTUREVIEW_MODEL_HISTORY", "90"))
NEUTRAL_ALPHA = float(os.environ.get("FUTUREVIEW_NEUTRAL_ALPHA", "0.2"))
EPOCHS = int(os.environ.get("FUTUREVIEW_EPOCHS", "300"))
LR = float(os.environ.get("FUTUREVIEW_LR", "0.003"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))

STATE_TO_ID = {"high": 0, "neutral": 1, "low": 2}
ID_TO_STATE = {v: k for k, v in STATE_TO_ID.items()}


def state_weight(state: str) -> float:
    if state in ("high", "low"):
        return 1.0
    if state == "neutral":
        return NEUTRAL_ALPHA
    raise ValueError(f"invalid state {state!r}")


def make_input_features(df: pd.DataFrame, start: int, end: int) -> np.ndarray:
    close = df.iloc[start : end + 1]["close"].to_numpy(dtype=np.float64)
    volume = df.iloc[start : end + 1]["volume"].to_numpy(dtype=np.float64)
    if len(close) != MODEL_HISTORY:
        raise ValueError("input window length mismatch")
    if np.any(close <= 0) or np.any(volume <= 0):
        raise ValueError("price/volume must be positive")

    lp = np.log(close)
    lv = np.log(volume)
    price = lp - lp[-1]
    v_sd = float(lv.std())
    volume_z = (lv - lv.mean()) / (v_sd if v_sd > 1e-8 else 1.0)
    x = np.stack([price, volume_z]).astype(np.float32)
    if not np.isfinite(x).all():
        raise ValueError("non-finite model input")
    return x


class ForwardCQStateNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Conv1d(2, 16, 7, padding="same"),
            nn.GELU(),
            nn.Conv1d(16, 24, 5, padding="same"),
            nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.shared = nn.Sequential(nn.Linear(24, 24), nn.GELU())
        self.cq_head = nn.Linear(24, 2)
        self.state_head = nn.Linear(24, 3)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        z = self.encoder(x).squeeze(-1)
        z = self.shared(z)
        return self.cq_head(z), self.state_head(z)


@dataclass
class TrainingData:
    x: torch.Tensor
    y_cq: torch.Tensor
    y_state: torch.Tensor
    weight: torch.Tensor
    rows: pd.DataFrame


def build_training_data(df: pd.DataFrame, forward: pd.DataFrame) -> TrainingData:
    xs: list[np.ndarray] = []
    ys: list[list[float]] = []
    states: list[int] = []
    weights: list[float] = []
    kept: list[int] = []
    for i, r in forward.iterrows():
        x = make_input_features(df, int(r.input_start), int(r.input_end))
        xs.append(x)
        ys.append([float(r.C), float(r.Q)])
        states.append(STATE_TO_ID[str(r.state)])
        weights.append(state_weight(str(r.state)))
        kept.append(i)
    return TrainingData(
        x=torch.from_numpy(np.stack(xs)),
        y_cq=torch.tensor(ys, dtype=torch.float32),
        y_state=torch.tensor(states, dtype=torch.long),
        weight=torch.tensor(weights, dtype=torch.float32),
        rows=forward.loc[kept].reset_index(drop=True),
    )


def weighted_mean(loss: torch.Tensor, weight: torch.Tensor) -> torch.Tensor:
    return (loss * weight).sum() / weight.sum()


def main() -> None:
    if W != 30 or MODEL_HISTORY != 90:
        raise ValueError("prediction smoke model locked to W=30 and model_history=90")
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(df, paths, window=W, stride=1, random_samples=20, random_seed=SEED)
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)
    classified = _classify(wq).sort_values("start_index").reset_index(drop=True)
    forward = build_forward_dataset(classified, len(df), MODEL_HISTORY)
    data = build_training_data(df, forward)

    y_mu = data.y_cq.mean(dim=0, keepdim=True)
    y_sd = data.y_cq.std(dim=0, keepdim=True, unbiased=False)
    y_sd = torch.where(y_sd < 1e-6, torch.ones_like(y_sd), y_sd)
    target_z = (data.y_cq - y_mu) / y_sd

    model = ForwardCQStateNet()
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    reg_fn = nn.SmoothL1Loss(reduction="none")
    cls_fn = nn.CrossEntropyLoss(reduction="none")

    for _ in range(EPOCHS):
        model.train()
        pred_z, logits = model(data.x)
        reg_each = reg_fn(pred_z, target_z).mean(dim=1)
        cls_each = cls_fn(logits, data.y_state)
        loss = weighted_mean(reg_each + cls_each, data.weight)
        opt.zero_grad()
        loss.backward()
        opt.step()

    model.eval()
    with torch.no_grad():
        pred_z, logits = model(data.x)
        pred_cq = pred_z * y_sd + y_mu
        prob = torch.softmax(logits, dim=1)

    pred_np = pred_cq.numpy()
    prob_np = prob.numpy()
    prob_sum_error = float(np.max(np.abs(prob_np.sum(axis=1) - 1.0)))
    q_negative = int((pred_np[:, 1] < 0).sum())

    print(
        f"S1 L2SMOKE START ticker={TICKER} rows={audit.rows} W={W} model_history={MODEL_HISTORY} "
        f"samples={len(data.rows)} alpha={NEUTRAL_ALPHA:.3f} epochs={EPOCHS}"
    )
    print(
        f"S1 L2SMOKE SANITY prob_sum_max_error={prob_sum_error:.8f} "
        f"pred_C_min={pred_np[:,0].min():.6f} pred_C_max={pred_np[:,0].max():.6f} "
        f"pred_Q_min={pred_np[:,1].min():.6f} pred_Q_max={pred_np[:,1].max():.6f} pred_Q_negative={q_negative}"
    )

    for j in range(max(0, len(data.rows) - 8), len(data.rows)):
        r = data.rows.iloc[j]
        p = prob_np[j]
        print(
            f"S1 L2SMOKE HIST target_start={int(r.target_start)} state={r.state} "
            f"actual_C={float(r.C):.6f} pred_C={pred_np[j,0]:.6f} "
            f"actual_Q={float(r.Q):.6f} pred_Q={pred_np[j,1]:.6f} "
            f"P_H={p[0]:.6f} P_N={p[1]:.6f} P_L={p[2]:.6f} pred_state={ID_TO_STATE[int(np.argmax(p))]}"
        )

    live_end = len(df) - 1
    live_start = live_end - MODEL_HISTORY + 1
    live_x = torch.from_numpy(make_input_features(df, live_start, live_end)[None, ...])
    with torch.no_grad():
        live_z, live_logits = model(live_x)
        live_cq = (live_z * y_sd + y_mu).numpy()[0]
        live_p = torch.softmax(live_logits, dim=1).numpy()[0]

    input_start_date = pd.Timestamp(df.iloc[live_start]["date"]).date()
    input_end_date = pd.Timestamp(df.iloc[live_end]["date"]).date()
    print(
        f"S1 L2SMOKE LIVE input_start={input_start_date} input_end={input_end_date} "
        f"pred_C={live_cq[0]:.6f} pred_Q={live_cq[1]:.6f} "
        f"P_H={live_p[0]:.6f} P_N={live_p[1]:.6f} P_L={live_p[2]:.6f} "
        f"pred_state={ID_TO_STATE[int(np.argmax(live_p))]}"
    )
    print("S1 L2SMOKE COMPLETE")


if __name__ == "__main__":
    main()

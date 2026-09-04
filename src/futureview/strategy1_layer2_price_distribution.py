from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch
from torch import nn
import torch.nn.functional as F

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table
from .strategy1_cq_90d_rank_audit import build_window_q
from .strategy1_layer1_forward_w_audit import _classify
from .strategy1_layer2_forward_smoke import make_input_features

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
MODEL_HISTORY = int(os.environ.get("FUTUREVIEW_MODEL_HISTORY", "90"))
HORIZON = int(os.environ.get("FUTUREVIEW_PRICE_HORIZON", "3"))
VALID_YEARS = int(os.environ.get("FUTUREVIEW_VALID_YEARS", "1"))
EPOCHS = int(os.environ.get("FUTUREVIEW_EPOCHS", "300"))
LR = float(os.environ.get("FUTUREVIEW_LR", "0.003"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260904"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer2-price-distribution.csv")

QUANTILES = (0.10, 0.50, 0.90)


@dataclass
class PriceDistributionData:
    x: torch.Tensor
    y: torch.Tensor
    rows: pd.DataFrame


class PriceDistributionNet(nn.Module):
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
        self.q_center = nn.Linear(24, 1)
        self.q_lower_gap = nn.Linear(24, 1)
        self.q_upper_gap = nn.Linear(24, 1)
        self.up_head = nn.Linear(24, 1)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        z = self.shared(self.encoder(x).squeeze(-1))
        q50 = self.q_center(z)
        q10 = q50 - F.softplus(self.q_lower_gap(z))
        q90 = q50 + F.softplus(self.q_upper_gap(z))
        quantiles = torch.cat([q10, q50, q90], dim=1)
        up_logit = self.up_head(z).squeeze(1)
        return quantiles, up_logit


def pinball_loss(pred: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    qs = torch.tensor(QUANTILES, dtype=pred.dtype, device=pred.device).view(1, -1)
    err = target.view(-1, 1) - pred
    return torch.maximum(qs * err, (qs - 1.0) * err).mean()


def build_selected_samples(df: pd.DataFrame, classified: pd.DataFrame) -> PriceDistributionData:
    close = df["close"].to_numpy(dtype=np.float64)
    xs: list[np.ndarray] = []
    ys: list[float] = []
    rows: list[dict[str, object]] = []

    for r in classified.itertuples(index=False):
        if str(r.state) == "neutral":
            continue
        cutoff = int(r.end_index)
        future = cutoff + HORIZON
        input_start = cutoff - MODEL_HISTORY + 1
        if input_start < 0 or future >= len(df):
            continue
        x = make_input_features(df, input_start, cutoff)
        y = float(np.log(close[future] / close[cutoff]))
        xs.append(x)
        ys.append(y)
        rows.append({
            "state": str(r.state),
            "cutoff_index": cutoff,
            "future_index": future,
            "cutoff_date": pd.Timestamp(df.at[cutoff, "date"]).date().isoformat(),
            "future_date": pd.Timestamp(df.at[future, "date"]).date().isoformat(),
            "actual_r3": y,
        })

    if not xs:
        raise RuntimeError("no Layer1-selected samples available")
    return PriceDistributionData(
        x=torch.from_numpy(np.stack(xs)),
        y=torch.tensor(ys, dtype=torch.float32),
        rows=pd.DataFrame(rows),
    )


def _train(train_x: torch.Tensor, train_y: torch.Tensor) -> PriceDistributionNet:
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    model = PriceDistributionNet()
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    bce = nn.BCEWithLogitsLoss()
    up = (train_y > 0).float()
    for _ in range(EPOCHS):
        model.train()
        q, logit = model(train_x)
        loss = pinball_loss(q, train_y) + 0.5 * bce(logit, up)
        opt.zero_grad()
        loss.backward()
        opt.step()
    return model


def _describe(prefix: str, actual: np.ndarray) -> None:
    print(
        f"{prefix} n={len(actual)} mean={actual.mean():.6f} median={np.median(actual):.6f} "
        f"p10={np.quantile(actual,0.10):.6f} p90={np.quantile(actual,0.90):.6f} "
        f"p_up={(actual>0).mean():.6f}"
    )


def _bucket_report(out: pd.DataFrame, score_col: str) -> None:
    lo = float(out[score_col].quantile(0.20))
    hi = float(out[score_col].quantile(0.80))
    bucket = np.where(out[score_col] >= hi, "top20", np.where(out[score_col] <= lo, "bottom20", "middle60"))
    out[f"bucket_{score_col}"] = bucket
    for name in ("bottom20", "middle60", "top20"):
        g = out.loc[out[f"bucket_{score_col}"] == name]
        if len(g):
            _describe(f"S1 L2PD BUCKET score={score_col} bucket={name}", g.actual_r3.to_numpy(dtype=float))


def main() -> None:
    if W != 30 or MODEL_HISTORY != 90 or HORIZON != 3 or VALID_YEARS != 1:
        raise ValueError("Layer2 price distribution v1 is locked to W30/L90/future3/final1Y")

    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(df, paths, window=W, stride=1, random_samples=20, random_seed=SEED)
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)
    classified = _classify(wq).sort_values("end_index").reset_index(drop=True)
    data = build_selected_samples(df, classified)

    dates = pd.to_datetime(data.rows["cutoff_date"])
    final_date = pd.Timestamp(df.iloc[-1]["date"]).normalize()
    valid_cut = final_date - pd.DateOffset(years=VALID_YEARS)
    train_mask = dates < valid_cut
    valid_mask = dates >= valid_cut
    if int(train_mask.sum()) < 100 or int(valid_mask.sum()) < 20:
        raise RuntimeError("insufficient chronological train/validation selected samples")

    train_x = data.x[torch.from_numpy(train_mask.to_numpy())]
    train_y = data.y[torch.from_numpy(train_mask.to_numpy())]
    valid_x = data.x[torch.from_numpy(valid_mask.to_numpy())]
    valid_y = data.y[torch.from_numpy(valid_mask.to_numpy())]
    model = _train(train_x, train_y)

    model.eval()
    with torch.no_grad():
        q, logit = model(valid_x)
        p_up = torch.sigmoid(logit)
    qn = q.numpy()
    pn = p_up.numpy()
    yn = valid_y.numpy()

    out = data.rows.loc[valid_mask].copy().reset_index(drop=True)
    out["pred_q10"] = qn[:, 0]
    out["pred_q50"] = qn[:, 1]
    out["pred_q90"] = qn[:, 2]
    out["pred_p_up"] = pn
    out.to_csv(OUTPUT, index=False)

    coverage80 = float(((yn >= qn[:, 0]) & (yn <= qn[:, 2])).mean())
    direction_acc = float(((pn >= 0.5) == (yn > 0)).mean())
    brier = float(np.mean((pn - (yn > 0).astype(float)) ** 2))
    q50_spearman = float(pd.Series(yn).corr(pd.Series(qn[:, 1]), method="spearman"))
    p_spearman = float(pd.Series(yn).corr(pd.Series(pn), method="spearman"))

    print(
        f"S1 L2PD START ticker={TICKER} rows={audit.rows} selected={len(data.rows)} "
        f"train={int(train_mask.sum())} valid={int(valid_mask.sum())} W={W} history={MODEL_HISTORY} horizon={HORIZON} epochs={EPOCHS}"
    )
    _describe("S1 L2PD BASELINE selected_validation", yn)
    print(
        f"S1 L2PD METRIC coverage_q10_q90={coverage80:.6f} direction_acc={direction_acc:.6f} "
        f"brier={brier:.6f} q50_spearman={q50_spearman:.6f} p_up_spearman={p_spearman:.6f}"
    )
    _bucket_report(out, "pred_p_up")
    _bucket_report(out, "pred_q50")
    print(f"S1 L2PD OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 L2PD COMPLETE")


if __name__ == "__main__":
    main()

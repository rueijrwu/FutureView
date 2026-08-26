from __future__ import annotations

import math

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_ticker_daily, validate_daily_ohlcv
from .models import MultiScaleBlock
from .strategy1_success_training import DATA_PERIOD, HORIZON, make_success_dataset
from .strategy1_smh_ridge_lmu import _make_folds, _spearman, _bucket_metrics

TICKER = "SMH"
TOP_FRACTION = 0.20
SEEDS = (20260823, 20260824, 20260825)
EPOCHS = 80
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4


class ScalarTargetCNN(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.multi = MultiScaleBlock(5, branch_channels=8)
        self.fusion = nn.Sequential(
            nn.Conv1d(self.multi.out_channels, 16, kernel_size=3, padding="same"),
            nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(16, 8),
            nn.GELU(),
            nn.Linear(8, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.fusion(self.multi(x))).squeeze(1)


def _fit_cnn(x_train: torch.Tensor, y_train: np.ndarray, x_test: torch.Tensor, seed: int) -> np.ndarray:
    torch.manual_seed(seed)
    np.random.seed(seed)

    y_train = np.asarray(y_train, dtype=float)
    y_mean = float(np.mean(y_train))
    y_std = float(np.std(y_train))
    if y_std < 1e-8:
        y_std = 1.0

    target = torch.from_numpy(((y_train - y_mean) / y_std).astype(np.float32))
    model = ScalarTargetCNN().cpu()
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    loss_fn = nn.HuberLoss(delta=1.0)

    model.train()
    for _ in range(EPOCHS):
        optimizer.zero_grad(set_to_none=True)
        pred = model(x_train)
        loss = loss_fn(pred, target)
        loss.backward()
        optimizer.step()

    model.eval()
    with torch.no_grad():
        z = model(x_test).cpu().numpy().astype(float)
    return y_mean + y_std * z


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


def main() -> None:
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    ds = make_success_dataset(df)

    raw_dates = pd.to_datetime(df["date"]).reset_index(drop=True)
    live_end = raw_dates.iloc[-1]
    live_start = live_end - pd.DateOffset(months=3)
    holdout_positions = np.flatnonzero(raw_dates.to_numpy() >= np.datetime64(live_start))
    holdout_start = int(holdout_positions[0]) if len(holdout_positions) else len(raw_dates)
    target_end = np.asarray(ds.raw_indices, dtype=int) + HORIZON - 1
    history_idx = np.flatnonzero(target_end < holdout_start)

    x = ds.x.cpu()[history_idx]
    raw_indices = np.asarray(ds.raw_indices, dtype=int)[history_idx]
    dates = pd.to_datetime(np.asarray(ds.dates)[history_idx])
    targets = {
        "L": np.asarray(ds.entry_lower, dtype=float)[history_idx],
        "mu": np.asarray(ds.net_expected_return, dtype=float)[history_idx],
        "U": np.asarray(ds.entry_upper, dtype=float)[history_idx],
    }
    folds = _make_folds(raw_indices)

    print(
        "S1 SMH_CNN DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"history_entries={len(history_idx)} folds={len(folds)} lookback=50 horizon={HORIZON} "
        f"live_holdout_start={pd.Timestamp(live_start).date()} live_holdout_end={pd.Timestamp(live_end).date()} "
        "history_rule=target_end_strictly_before_live_start"
    )
    print(
        "S1 SMH_CNN MODEL name=SCALAR_TARGET_CNN targets=L,mu,U independent_models=true "
        f"epochs={EPOCHS} lr={LEARNING_RATE} weight_decay={WEIGHT_DECAY} seeds={','.join(map(str, SEEDS))} "
        "target_standardization=train_only no_Q=true no_composite_score=true"
    )
    print(
        "S1 SMH_CNN EVAL chronological=true purge_raw_sessions=60 top_fraction=0.20 "
        "metrics=spearman,realized_target_top20,bottom20,top_minus_bottom"
    )

    aggregate: dict[str, list[tuple[float, float, float, float]]] = {k: [] for k in targets}

    for fold_id, (train, test) in enumerate(folds, start=1):
        gap = int(raw_indices[test[0]] - raw_indices[train[-1]] - 1)
        print(
            f"S1 SMH_CNN FOLD id={fold_id} n_train={len(train)} n_test={len(test)} "
            f"train_first={pd.Timestamp(dates[train[0]]).date()} train_last={pd.Timestamp(dates[train[-1]]).date()} "
            f"test_first={pd.Timestamp(dates[test[0]]).date()} test_last={pd.Timestamp(dates[test[-1]]).date()} raw_session_gap={gap}"
        )
        for name, y in targets.items():
            seed_rows = []
            for seed in SEEDS:
                pred = _fit_cnn(x[train], y[train], x[test], seed)
                rho = _spearman(y[test], pred)
                top, bottom, spread = _bucket_metrics(y[test], pred)
                seed_rows.append((rho, top, bottom, spread))
                print(
                    f"S1 SMH_CNN FOLD_TARGET id={fold_id} target={name} seed={seed} "
                    f"spearman={_fmt(rho)} realized_top20_mean={top:.6f} "
                    f"realized_bottom20_mean={bottom:.6f} top_minus_bottom={spread:.6f}"
                )
            seed_arr = np.asarray(seed_rows, dtype=float)
            aggregate[name].append(tuple(np.nanmean(seed_arr, axis=0)))

    for name, rows in aggregate.items():
        arr = np.asarray(rows, dtype=float)
        print(
            f"S1 SMH_CNN SUMMARY target={name} folds={len(rows)} "
            f"spearman_mean={_fmt(float(np.nanmean(arr[:,0])))} "
            f"spearman_positive_folds={int(np.sum(arr[:,0] > 0.0))}/{len(rows)} "
            f"realized_top20_mean={np.mean(arr[:,1]):.6f} realized_bottom20_mean={np.mean(arr[:,2]):.6f} "
            f"top_minus_bottom_mean={np.mean(arr[:,3]):.6f} "
            f"positive_separation_folds={int(np.sum(arr[:,3] > 0.0))}/{len(rows)}"
        )

    print("S1 SMH_CNN COMPLETE")


if __name__ == "__main__":
    main()

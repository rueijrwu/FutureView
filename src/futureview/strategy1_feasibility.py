from __future__ import annotations

import math

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_spy_daily
from .datasets import build_windows
from .features import make_causal_features
from .models import TrendCNNDual, TrendCNNJoint
from .strategy1_targets import STRATEGY1_TARGET_COLUMNS, make_strategy1_targets
from .walkforward import purged_expanding_walk_forward

HORIZONS = (15, 30, 45, 60)
SEED = 20260825
EPOCHS = 20
LEARNING_RATE = 3e-3
HUBER_DELTA = 0.01
RIDGE_ALPHA = 1e-2
TOP_FRACTION = 0.20


def _rankdata(values: np.ndarray) -> np.ndarray:
    return pd.Series(values).rank(method="average").to_numpy(dtype=float)


def _spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) < 2:
        return float("nan")
    r_true = _rankdata(y_true)
    r_pred = _rankdata(y_pred)
    if np.std(r_true) == 0.0 or np.std(r_pred) == 0.0:
        return float("nan")
    return float(np.corrcoef(r_true, r_pred)[0, 1])


def _metric_row(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    mae = float(np.mean(np.abs(y_true - y_pred)))
    spearman = _spearman(y_true, y_pred)
    n_top = max(1, int(math.ceil(len(y_pred) * TOP_FRACTION)))
    top_idx = np.argsort(y_pred, kind="stable")[-n_top:]
    bottom_idx = np.argsort(y_pred, kind="stable")[:n_top]
    overall = float(np.mean(y_true))
    top = float(np.mean(y_true[top_idx]))
    bottom = float(np.mean(y_true[bottom_idx]))
    return {
        "mae": mae,
        "spearman": spearman,
        "overall": overall,
        "top20": top,
        "bottom20": bottom,
        "top_minus_all": top - overall,
        "top_minus_bottom": top - bottom,
    }


def _fit_ridge(x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray) -> np.ndarray:
    mean = x_train.mean(axis=0, keepdims=True)
    std = x_train.std(axis=0, keepdims=True)
    std[std < 1e-8] = 1.0
    xtr = (x_train - mean) / std
    xte = (x_test - mean) / std
    xtr = np.concatenate([np.ones((len(xtr), 1)), xtr], axis=1)
    xte = np.concatenate([np.ones((len(xte), 1)), xte], axis=1)
    reg = np.eye(xtr.shape[1], dtype=float) * RIDGE_ALPHA
    reg[0, 0] = 0.0
    coef = np.linalg.solve(xtr.T @ xtr + reg, xtr.T @ y_train)
    return xte @ coef


def _fit_cnn(model_cls, x_train: torch.Tensor, y_train: torch.Tensor, x_test: torch.Tensor) -> np.ndarray:
    torch.manual_seed(SEED)
    model = model_cls().cpu()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    loss_fn = nn.HuberLoss(delta=HUBER_DELTA)
    model.train()
    for _ in range(EPOCHS):
        optimizer.zero_grad(set_to_none=True)
        prediction = model(x_train)
        loss = loss_fn(prediction, y_train)
        loss.backward()
        optimizer.step()
    model.eval()
    with torch.no_grad():
        return model(x_test).cpu().numpy().astype(float)


def _print_metrics(name: str, y_true: np.ndarray, y_pred: np.ndarray) -> None:
    for j, h in enumerate(HORIZONS):
        m = _metric_row(y_true[:, j], y_pred[:, j])
        print(
            f"S1 FEASIBILITY {name} {h}D n={len(y_true)} "
            f"spearman={m['spearman']:.3f} mae={m['mae']:.6f} "
            f"realized_all={m['overall']:.6f} top20={m['top20']:.6f} "
            f"bottom20={m['bottom20']:.6f} top_minus_all={m['top_minus_all']:.6f} "
            f"top_minus_bottom={m['top_minus_bottom']:.6f}"
        )


def main() -> None:
    torch.set_num_threads(2)
    df = download_spy_daily(period="3y")
    features = make_causal_features(df)
    targets = make_strategy1_targets(df)
    windows = build_windows(features, targets, lookback=50, target_columns=STRATEGY1_TARGET_COLUMNS)
    folds = purged_expanding_walk_forward(
        len(windows.y), min_train=260, test_size=60, purge=60, step=60
    )

    x_np = windows.x.numpy().astype(float)
    y_np = windows.y.numpy().astype(float)
    dates = pd.to_datetime(windows.dates)

    print(
        f"S1 FEASIBILITY DATA windows={len(y_np)} folds={len(folds)} "
        f"first={dates[0].date()} last={dates[-1].date()} "
        f"epochs={EPOCHS} huber_delta={HUBER_DELTA} ridge_alpha={RIDGE_ALPHA} seed={SEED}"
    )

    all_true: list[np.ndarray] = []
    predictions: dict[str, list[np.ndarray]] = {
        "CONSTANT": [],
        "LINEAR": [],
        "CNN_A": [],
        "CNN_B": [],
    }

    for fold_id, fold in enumerate(folds, start=1):
        train_idx = fold.train
        test_idx = fold.test
        x_train = windows.x[train_idx].cpu()
        y_train = windows.y[train_idx].cpu()
        x_test = windows.x[test_idx].cpu()
        y_test = y_np[test_idx]

        constant = np.broadcast_to(y_np[train_idx].mean(axis=0), y_test.shape).copy()
        linear = _fit_ridge(
            x_np[train_idx].reshape(len(train_idx), -1),
            y_np[train_idx],
            x_np[test_idx].reshape(len(test_idx), -1),
        )
        cnn_a = _fit_cnn(TrendCNNJoint, x_train, y_train, x_test)
        cnn_b = _fit_cnn(TrendCNNDual, x_train, y_train, x_test)

        all_true.append(y_test)
        predictions["CONSTANT"].append(constant)
        predictions["LINEAR"].append(linear)
        predictions["CNN_A"].append(cnn_a)
        predictions["CNN_B"].append(cnn_b)

        print(
            f"S1 FEASIBILITY FOLD id={fold_id} train={len(train_idx)} test={len(test_idx)} "
            f"train_last={dates[train_idx[-1]].date()} test_first={dates[test_idx[0]].date()} "
            f"test_last={dates[test_idx[-1]].date()} purge={test_idx[0] - train_idx[-1] - 1}"
        )

    y_true = np.concatenate(all_true, axis=0)
    print(f"S1 FEASIBILITY OOS n={len(y_true)}")
    for name, chunks in predictions.items():
        _print_metrics(name, y_true, np.concatenate(chunks, axis=0))

    print("S1 FEASIBILITY PASS")


if __name__ == "__main__":
    main()

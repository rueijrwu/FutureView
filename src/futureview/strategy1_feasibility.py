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
    if len(y_true) < 2 or np.std(y_pred) == 0.0:
        return float("nan")
    r_true = _rankdata(y_true)
    r_pred = _rankdata(y_pred)
    if np.std(r_true) == 0.0 or np.std(r_pred) == 0.0:
        return float("nan")
    return float(np.corrcoef(r_true, r_pred)[0, 1])


def _metric_row(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    mae = float(np.mean(np.abs(y_true - y_pred)))
    overall = float(np.mean(y_true))
    spearman = _spearman(y_true, y_pred)
    if np.std(y_pred) == 0.0:
        return {
            "mae": mae,
            "spearman": float("nan"),
            "overall": overall,
            "top20": float("nan"),
            "bottom20": float("nan"),
            "top_minus_all": float("nan"),
            "top_minus_bottom": float("nan"),
        }
    n_top = max(1, int(math.ceil(len(y_pred) * TOP_FRACTION)))
    order = np.argsort(y_pred, kind="stable")
    top_idx = order[-n_top:]
    bottom_idx = order[:n_top]
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


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


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
    names = ("CONSTANT", "LINEAR", "CNN_A", "CNN_B")
    fold_metrics: dict[str, dict[int, list[dict[str, float]]]] = {
        name: {h: [] for h in HORIZONS} for name in names
    }

    print(
        f"S1 FEASIBILITY DATA windows={len(y_np)} folds={len(folds)} "
        f"first={dates[0].date()} last={dates[-1].date()} "
        f"epochs={EPOCHS} huber_delta={HUBER_DELTA} ridge_alpha={RIDGE_ALPHA} seed={SEED}"
    )

    for fold_id, fold in enumerate(folds, start=1):
        train_idx = fold.train
        test_idx = fold.test
        x_train = windows.x[train_idx].cpu()
        y_train = windows.y[train_idx].cpu()
        x_test = windows.x[test_idx].cpu()
        y_test = y_np[test_idx]

        predictions = {
            "CONSTANT": np.broadcast_to(y_np[train_idx].mean(axis=0), y_test.shape).copy(),
            "LINEAR": _fit_ridge(
                x_np[train_idx].reshape(len(train_idx), -1),
                y_np[train_idx],
                x_np[test_idx].reshape(len(test_idx), -1),
            ),
            "CNN_A": _fit_cnn(TrendCNNJoint, x_train, y_train, x_test),
            "CNN_B": _fit_cnn(TrendCNNDual, x_train, y_train, x_test),
        }

        print(
            f"S1 FEASIBILITY FOLD id={fold_id} train={len(train_idx)} test={len(test_idx)} "
            f"train_last={dates[train_idx[-1]].date()} test_first={dates[test_idx[0]].date()} "
            f"test_last={dates[test_idx[-1]].date()} purge={test_idx[0] - train_idx[-1] - 1}"
        )

        for name, pred in predictions.items():
            for j, h in enumerate(HORIZONS):
                m = _metric_row(y_test[:, j], pred[:, j])
                fold_metrics[name][h].append(m)
                print(
                    f"S1 FEASIBILITY FOLD_METRIC id={fold_id} model={name} horizon={h} "
                    f"spearman={_fmt(m['spearman'])} mae={m['mae']:.6f} "
                    f"realized_all={m['overall']:.6f} top20={_fmt(m['top20'])} "
                    f"top_minus_all={_fmt(m['top_minus_all'])} "
                    f"top_minus_bottom={_fmt(m['top_minus_bottom'])}"
                )

    print(f"S1 FEASIBILITY OOS complete_folds={len(folds)} n={sum(len(f.test) for f in folds)}")
    for name in names:
        for h in HORIZONS:
            rows = fold_metrics[name][h]
            mae = np.asarray([r["mae"] for r in rows], dtype=float)
            spearman = np.asarray([r["spearman"] for r in rows], dtype=float)
            lift = np.asarray([r["top_minus_all"] for r in rows], dtype=float)
            spread = np.asarray([r["top_minus_bottom"] for r in rows], dtype=float)
            valid_rank = np.isfinite(spearman)
            valid_lift = np.isfinite(lift)
            print(
                f"S1 FEASIBILITY SUMMARY model={name} horizon={h} folds={len(rows)} "
                f"mae_mean={mae.mean():.6f} mae_std={mae.std(ddof=0):.6f} "
                f"spearman_mean={_fmt(np.nanmean(spearman) if valid_rank.any() else float('nan'))} "
                f"spearman_positive={int(np.sum(spearman[valid_rank] > 0))}/{int(valid_rank.sum())} "
                f"top20_lift_mean={_fmt(np.nanmean(lift) if valid_lift.any() else float('nan'))} "
                f"top20_lift_positive={int(np.sum(lift[valid_lift] > 0))}/{int(valid_lift.sum())} "
                f"top_bottom_mean={_fmt(np.nanmean(spread) if np.isfinite(spread).any() else float('nan'))}"
            )

    print("S1 FEASIBILITY PASS")


if __name__ == "__main__":
    main()

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_spy_daily
from .datasets import build_windows
from .features import make_causal_features
from .models import TrendCNNJoint
from .strategy1_targets import STRATEGY1_TARGET_COLUMNS, make_strategy1_targets
from .walkforward import purged_expanding_walk_forward

HORIZONS = (15, 30, 45, 60)
TARGET_HORIZON = 30
TARGET_INDEX = HORIZONS.index(TARGET_HORIZON)
SEEDS = (20260821, 20260822, 20260823, 20260824, 20260825)
LOOKBACKS = (5, 10, 20, 50)
EPOCHS = 20
LEARNING_RATE = 3e-3
HUBER_DELTA = 0.01
TOP_FRACTION = 0.20
PURGE = 60
TEST_SIZE = 60
MIN_EXPANDING_TRAIN = 320
SLIDING_TRAIN = 260
RIDGE_ALPHA = 0.01


def _rankdata(values: np.ndarray) -> np.ndarray:
    return pd.Series(values).rank(method="average").to_numpy(dtype=float)


def _spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) < 2 or np.std(y_pred) < 1e-12:
        return float("nan")
    r_true = _rankdata(y_true)
    r_pred = _rankdata(y_pred)
    if np.std(r_true) < 1e-12 or np.std(r_pred) < 1e-12:
        return float("nan")
    return float(np.corrcoef(r_true, r_pred)[0, 1])


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    overall = float(np.mean(y_true))
    mae = float(np.mean(np.abs(y_true - y_pred)))
    spearman = _spearman(y_true, y_pred)
    if np.std(y_pred) < 1e-12:
        return {
            "mae": mae,
            "spearman": float("nan"),
            "overall": overall,
            "top20": float("nan"),
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
        "top_minus_all": top - overall,
        "top_minus_bottom": top - bottom,
    }


def _summary_features(x: torch.Tensor) -> np.ndarray:
    """Return 20 fixed causal summary features from [batch, 5, 50] OHLCV windows."""
    arr = x.detach().cpu().numpy().astype(float)
    if arr.ndim != 3 or arr.shape[1] != 5 or arr.shape[2] < max(LOOKBACKS):
        raise ValueError(f"expected [batch, 5, >=50], got {arr.shape}")
    rows: list[np.ndarray] = []
    for lb in LOOKBACKS:
        w = arr[:, :, -lb:]
        close = w[:, 3, :]
        high = w[:, 1, :]
        low = w[:, 2, :]
        volume = w[:, 4, :]
        rows.extend(
            [
                close.sum(axis=1),
                close.std(axis=1, ddof=0),
                (high - low).mean(axis=1),
                np.abs(close).mean(axis=1),
                volume.mean(axis=1),
            ]
        )
    out = np.column_stack(rows)
    if out.shape[1] != 20 or not np.isfinite(out).all():
        raise RuntimeError("invalid causal summary feature matrix")
    return out


def _fit_ridge(x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray) -> np.ndarray:
    mean = x_train.mean(axis=0)
    std = x_train.std(axis=0, ddof=0)
    std = np.where(std < 1e-12, 1.0, std)
    z_train = (x_train - mean) / std
    z_test = (x_test - mean) / std
    design = np.column_stack([np.ones(len(z_train)), z_train])
    test_design = np.column_stack([np.ones(len(z_test)), z_test])
    penalty = np.eye(design.shape[1], dtype=float) * RIDGE_ALPHA
    penalty[0, 0] = 0.0
    beta = np.linalg.solve(design.T @ design + penalty, design.T @ y_train)
    return test_design @ beta


def _fit_cnn(
    x_train: torch.Tensor,
    y_train: torch.Tensor,
    x_test: torch.Tensor,
    *,
    seed: int,
) -> np.ndarray:
    torch.manual_seed(seed)
    model = TrendCNNJoint().cpu()
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
        return model(x_test).cpu().numpy().astype(float)[:, TARGET_INDEX]


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


def _mean_std(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if not len(arr):
        return float("nan"), float("nan")
    return float(arr.mean()), float(arr.std(ddof=0))


def main() -> None:
    torch.set_num_threads(2)
    df = download_spy_daily(period="3y")
    features = make_causal_features(df)
    targets = make_strategy1_targets(df)
    windows = build_windows(
        features,
        targets,
        lookback=50,
        target_columns=STRATEGY1_TARGET_COLUMNS,
    )
    dates = pd.to_datetime(windows.dates)
    y = windows.y.numpy().astype(float)[:, TARGET_INDEX]
    summary_x = _summary_features(windows.x)

    all_folds = purged_expanding_walk_forward(
        len(y),
        min_train=MIN_EXPANDING_TRAIN,
        test_size=TEST_SIZE,
        purge=PURGE,
        step=TEST_SIZE,
    )
    folds = tuple(f for f in all_folds if len(f.test) == TEST_SIZE)
    if not folds:
        raise RuntimeError("no complete common OOS folds")

    cnn_results: dict[int, list[dict[str, float]]] = {seed: [] for seed in SEEDS}
    ridge_results: list[dict[str, float]] = []
    constant_results: list[dict[str, float]] = []

    print(
        f"S1 SUMMARY_BASELINE DATA windows={len(y)} folds={len(folds)} "
        f"first={dates[0].date()} last={dates[-1].date()} horizon={TARGET_HORIZON} "
        f"train=SLIDING_{SLIDING_TRAIN} summary_dim={summary_x.shape[1]} "
        f"ridge_alpha={RIDGE_ALPHA} epochs={EPOCHS} purge={PURGE} test_size={TEST_SIZE} "
        f"seeds={','.join(map(str, SEEDS))}"
    )
    print(
        "S1 SUMMARY_BASELINE FEATURES "
        "lookbacks=5,10,20,50 per_lookback=close_sum,close_std,range_mean,abs_close_mean,volume_z_mean"
    )

    for fold_id, fold in enumerate(folds, start=1):
        expanding_idx = fold.train
        test_idx = fold.test
        train_end = int(expanding_idx[-1]) + 1
        train_idx = np.arange(train_end - SLIDING_TRAIN, train_end, dtype=int)
        if train_idx[0] < 0:
            raise RuntimeError("sliding train window begins before dataset")

        y_train = y[train_idx]
        y_test = y[test_idx]
        print(
            f"S1 SUMMARY_BASELINE FOLD id={fold_id} n_train={len(train_idx)} "
            f"train_first={dates[train_idx[0]].date()} train_last={dates[train_idx[-1]].date()} "
            f"test_first={dates[test_idx[0]].date()} test_last={dates[test_idx[-1]].date()} "
            f"purge={test_idx[0] - expanding_idx[-1] - 1}"
        )

        ridge_pred = _fit_ridge(summary_x[train_idx], y_train, summary_x[test_idx])
        ridge_m = _metrics(y_test, ridge_pred)
        ridge_results.append(ridge_m)
        print(
            f"S1 SUMMARY_BASELINE FOLD_METRIC id={fold_id} model=SUMMARY_RIDGE "
            f"spearman={_fmt(ridge_m['spearman'])} mae={ridge_m['mae']:.6f} "
            f"top20_lift={_fmt(ridge_m['top_minus_all'])} "
            f"top_bottom={_fmt(ridge_m['top_minus_bottom'])}"
        )

        constant_pred = np.full(len(test_idx), float(y_train.mean()), dtype=float)
        constant_m = _metrics(y_test, constant_pred)
        constant_results.append(constant_m)
        print(
            f"S1 SUMMARY_BASELINE FOLD_METRIC id={fold_id} model=CONSTANT "
            f"spearman={_fmt(constant_m['spearman'])} mae={constant_m['mae']:.6f} "
            f"top20_lift={_fmt(constant_m['top_minus_all'])}"
        )

        x_train = windows.x[train_idx].cpu()
        y_train_all = windows.y[train_idx].cpu()
        x_test = windows.x[test_idx].cpu()
        for seed in SEEDS:
            cnn_pred = _fit_cnn(x_train, y_train_all, x_test, seed=seed)
            cnn_m = _metrics(y_test, cnn_pred)
            cnn_results[seed].append(cnn_m)
            print(
                f"S1 SUMMARY_BASELINE FOLD_METRIC id={fold_id} model=CNN_A seed={seed} "
                f"spearman={_fmt(cnn_m['spearman'])} mae={cnn_m['mae']:.6f} "
                f"top20_lift={_fmt(cnn_m['top_minus_all'])} "
                f"top_bottom={_fmt(cnn_m['top_minus_bottom'])}"
            )

    def summarize_rows(rows: list[dict[str, float]]) -> dict[str, float]:
        spearman = np.asarray([r["spearman"] for r in rows], dtype=float)
        lift = np.asarray([r["top_minus_all"] for r in rows], dtype=float)
        mae = np.asarray([r["mae"] for r in rows], dtype=float)
        return {
            "spearman_mean": float(np.nanmean(spearman)) if np.isfinite(spearman).any() else float("nan"),
            "spearman_positive": float(np.sum(spearman[np.isfinite(spearman)] > 0)),
            "spearman_valid": float(np.isfinite(spearman).sum()),
            "lift_mean": float(np.nanmean(lift)) if np.isfinite(lift).any() else float("nan"),
            "lift_positive": float(np.sum(lift[np.isfinite(lift)] > 0)),
            "lift_valid": float(np.isfinite(lift).sum()),
            "mae_mean": float(mae.mean()),
        }

    ridge_summary = summarize_rows(ridge_results)
    constant_summary = summarize_rows(constant_results)
    print(
        f"S1 SUMMARY_BASELINE SUMMARY model=SUMMARY_RIDGE folds={len(folds)} "
        f"spearman_mean={_fmt(ridge_summary['spearman_mean'])} "
        f"spearman_positive={int(ridge_summary['spearman_positive'])}/{int(ridge_summary['spearman_valid'])} "
        f"top20_lift_mean={_fmt(ridge_summary['lift_mean'])} "
        f"top20_lift_positive={int(ridge_summary['lift_positive'])}/{int(ridge_summary['lift_valid'])} "
        f"mae_mean={ridge_summary['mae_mean']:.6f}"
    )
    print(
        f"S1 SUMMARY_BASELINE SUMMARY model=CONSTANT folds={len(folds)} "
        f"spearman_mean={_fmt(constant_summary['spearman_mean'])} "
        f"top20_lift_mean={_fmt(constant_summary['lift_mean'])} "
        f"mae_mean={constant_summary['mae_mean']:.6f}"
    )

    seed_summaries: dict[int, dict[str, float]] = {}
    for seed in SEEDS:
        summary = summarize_rows(cnn_results[seed])
        seed_summaries[seed] = summary
        print(
            f"S1 SUMMARY_BASELINE SEED_SUMMARY model=CNN_A seed={seed} folds={len(folds)} "
            f"spearman_mean={_fmt(summary['spearman_mean'])} "
            f"spearman_positive={int(summary['spearman_positive'])}/{int(summary['spearman_valid'])} "
            f"top20_lift_mean={_fmt(summary['lift_mean'])} "
            f"top20_lift_positive={int(summary['lift_positive'])}/{int(summary['lift_valid'])} "
            f"mae_mean={summary['mae_mean']:.6f}"
        )

    for key, label in (("spearman_mean", "spearman"), ("lift_mean", "top20_lift"), ("mae_mean", "mae")):
        values = [seed_summaries[seed][key] for seed in SEEDS]
        mean, std = _mean_std(values)
        positive = sum(v > 0 for v in values if np.isfinite(v))
        print(
            f"S1 SUMMARY_BASELINE CROSS_SEED model=CNN_A metric={label} "
            f"mean={_fmt(mean)} std={_fmt(std)} positive={positive}/{len(SEEDS)}"
        )

    for fold_id in range(1, len(folds) + 1):
        for key, label in (("spearman", "spearman"), ("top_minus_all", "top20_lift")):
            values = [cnn_results[seed][fold_id - 1][key] for seed in SEEDS]
            mean, std = _mean_std(values)
            positive = sum(v > 0 for v in values if np.isfinite(v))
            ridge_value = ridge_results[fold_id - 1][key]
            print(
                f"S1 SUMMARY_BASELINE FOLD_COMPARE fold={fold_id} metric={label} "
                f"cnn_mean={_fmt(mean)} cnn_std={_fmt(std)} cnn_positive={positive}/{len(SEEDS)} "
                f"ridge={_fmt(ridge_value)}"
            )

    print("S1 SUMMARY_BASELINE PASS")


if __name__ == "__main__":
    main()

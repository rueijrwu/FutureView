from __future__ import annotations

import math

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_spy_daily
from .datasets import build_windows
from .features import make_causal_features
from .models import TrendCNNJoint, TrendCNNDual
from .strategy1_targets import STRATEGY1_TARGET_COLUMNS, make_strategy1_targets
from .walkforward import purged_expanding_walk_forward

HORIZONS = (15, 30, 45, 60)
TARGET_HORIZON = 30
TARGET_INDEX = HORIZONS.index(TARGET_HORIZON)
SEEDS = (20260821, 20260822, 20260823, 20260824, 20260825)
MODELS = ("CNN_A", "CNN_B")
EPOCHS = 20
LEARNING_RATE = 3e-3
HUBER_DELTA = 0.01
TOP_FRACTION = 0.20
PURGE = 60
TEST_SIZE = 60
MIN_EXPANDING_TRAIN = 320
SLIDING_TRAIN = 260


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
        "top_minus_all": top - overall,
        "top_minus_bottom": top - bottom,
    }


def _fit_model(
    model_name: str,
    x_train: torch.Tensor,
    y_train: torch.Tensor,
    x_test: torch.Tensor,
    *,
    seed: int,
) -> np.ndarray:
    torch.manual_seed(seed)
    if model_name == "CNN_A":
        model = TrendCNNJoint().cpu()
    elif model_name == "CNN_B":
        model = TrendCNNDual().cpu()
    else:
        raise ValueError(model_name)
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

    results: dict[str, dict[int, list[dict[str, float]]]] = {
        model: {seed: [] for seed in SEEDS} for model in MODELS
    }

    print(
        f"S1 MODEL_COMPARE DATA windows={len(y)} folds={len(folds)} "
        f"first={dates[0].date()} last={dates[-1].date()} horizon={TARGET_HORIZON} "
        f"train=SLIDING_{SLIDING_TRAIN} epochs={EPOCHS} purge={PURGE} "
        f"test_size={TEST_SIZE} seeds={','.join(map(str, SEEDS))}"
    )

    for fold_id, fold in enumerate(folds, start=1):
        expanding_idx = fold.train
        test_idx = fold.test
        train_end = int(expanding_idx[-1]) + 1
        train_idx = np.arange(train_end - SLIDING_TRAIN, train_end, dtype=int)
        if train_idx[0] < 0:
            raise RuntimeError("sliding train window begins before dataset")

        print(
            f"S1 MODEL_COMPARE FOLD id={fold_id} n_train={len(train_idx)} "
            f"train_first={dates[train_idx[0]].date()} train_last={dates[train_idx[-1]].date()} "
            f"test_first={dates[test_idx[0]].date()} test_last={dates[test_idx[-1]].date()} "
            f"purge={test_idx[0] - expanding_idx[-1] - 1}"
        )

        x_train = windows.x[train_idx].cpu()
        y_train = windows.y[train_idx].cpu()
        x_test = windows.x[test_idx].cpu()
        y_test = y[test_idx]

        for model_name in MODELS:
            for seed in SEEDS:
                pred = _fit_model(model_name, x_train, y_train, x_test, seed=seed)
                m = _metrics(y_test, pred)
                results[model_name][seed].append(m)
                print(
                    f"S1 MODEL_COMPARE FOLD_METRIC id={fold_id} model={model_name} seed={seed} "
                    f"spearman={_fmt(m['spearman'])} mae={m['mae']:.6f} "
                    f"top20_lift={_fmt(m['top_minus_all'])} "
                    f"top_bottom={_fmt(m['top_minus_bottom'])}"
                )

    seed_summaries: dict[str, dict[int, dict[str, float]]] = {
        model: {} for model in MODELS
    }
    for model_name in MODELS:
        for seed in SEEDS:
            rows = results[model_name][seed]
            sp = np.asarray([r["spearman"] for r in rows], dtype=float)
            lift = np.asarray([r["top_minus_all"] for r in rows], dtype=float)
            mae = np.asarray([r["mae"] for r in rows], dtype=float)
            summary = {
                "spearman_mean": float(np.nanmean(sp)),
                "spearman_positive": float(np.sum(sp[np.isfinite(sp)] > 0)),
                "lift_mean": float(np.nanmean(lift)),
                "lift_positive": float(np.sum(lift[np.isfinite(lift)] > 0)),
                "mae_mean": float(mae.mean()),
            }
            seed_summaries[model_name][seed] = summary
            print(
                f"S1 MODEL_COMPARE SEED_SUMMARY model={model_name} seed={seed} folds={len(rows)} "
                f"spearman_mean={_fmt(summary['spearman_mean'])} "
                f"spearman_positive={int(summary['spearman_positive'])}/{len(rows)} "
                f"top20_lift_mean={_fmt(summary['lift_mean'])} "
                f"top20_lift_positive={int(summary['lift_positive'])}/{len(rows)} "
                f"mae_mean={summary['mae_mean']:.6f}"
            )

    for model_name in MODELS:
        for key, label in (("spearman_mean", "spearman"), ("lift_mean", "top20_lift"), ("mae_mean", "mae")):
            values = [seed_summaries[model_name][seed][key] for seed in SEEDS]
            mean, std = _mean_std(values)
            positive = sum(v > 0 for v in values if np.isfinite(v))
            print(
                f"S1 MODEL_COMPARE CROSS_SEED model={model_name} metric={label} "
                f"mean={_fmt(mean)} std={_fmt(std)} positive={positive}/{len(SEEDS)}"
            )

    for fold_id in range(1, len(folds) + 1):
        for model_name in MODELS:
            for key, label in (("spearman", "spearman"), ("top_minus_all", "top20_lift")):
                values = [results[model_name][seed][fold_id - 1][key] for seed in SEEDS]
                mean, std = _mean_std(values)
                positive = sum(v > 0 for v in values if np.isfinite(v))
                print(
                    f"S1 MODEL_COMPARE FOLD_SEED fold={fold_id} model={model_name} metric={label} "
                    f"mean={_fmt(mean)} std={_fmt(std)} positive={positive}/{len(SEEDS)}"
                )

    print("S1 MODEL_COMPARE PASS")


if __name__ == "__main__":
    main()

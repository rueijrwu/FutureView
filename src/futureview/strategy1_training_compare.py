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
SEED = 20260825
EPOCHS = 20
LEARNING_RATE = 3e-3
HUBER_DELTA = 0.01
TOP_FRACTION = 0.20
PURGE = 60
TEST_SIZE = 60
MIN_EXPANDING_TRAIN = 320
SLIDING_WINDOWS = (260, 320)


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


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    overall = float(np.mean(y_true))
    mae = float(np.mean(np.abs(y_true - y_pred)))
    spearman = _spearman(y_true, y_pred)
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


def _fit_cnn(x_train: torch.Tensor, y_train: torch.Tensor, x_test: torch.Tensor) -> np.ndarray:
    torch.manual_seed(SEED)
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
        return model(x_test).cpu().numpy().astype(float)


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


def main() -> None:
    torch.set_num_threads(2)
    df = download_spy_daily(period="3y")
    features = make_causal_features(df)
    targets = make_strategy1_targets(df)
    windows = build_windows(features, targets, lookback=50, target_columns=STRATEGY1_TARGET_COLUMNS)
    all_folds = purged_expanding_walk_forward(
        len(windows.y), min_train=MIN_EXPANDING_TRAIN, test_size=TEST_SIZE, purge=PURGE, step=TEST_SIZE
    )
    folds = tuple(f for f in all_folds if len(f.test) == TEST_SIZE)
    if not folds:
        raise RuntimeError("no complete common OOS folds")

    y_np = windows.y.numpy().astype(float)
    dates = pd.to_datetime(windows.dates)
    schemes = ("EXPANDING", "SLIDING_260", "SLIDING_320")
    results: dict[str, dict[int, list[dict[str, float]]]] = {
        scheme: {h: [] for h in HORIZONS} for scheme in schemes
    }

    print(
        f"S1 TRAINING_COMPARE DATA windows={len(y_np)} folds={len(folds)} "
        f"first={dates[0].date()} last={dates[-1].date()} epochs={EPOCHS} "
        f"purge={PURGE} test_size={TEST_SIZE} seed={SEED}"
    )

    for fold_id, fold in enumerate(folds, start=1):
        expanding_idx = fold.train
        test_idx = fold.test
        train_end = int(expanding_idx[-1]) + 1
        train_sets = {
            "EXPANDING": expanding_idx,
            "SLIDING_260": np.arange(train_end - 260, train_end, dtype=int),
            "SLIDING_320": np.arange(train_end - 320, train_end, dtype=int),
        }
        if train_sets["SLIDING_260"][0] < 0 or train_sets["SLIDING_320"][0] < 0:
            raise RuntimeError("sliding train window begins before dataset")

        print(
            f"S1 TRAINING_COMPARE FOLD id={fold_id} test_first={dates[test_idx[0]].date()} "
            f"test_last={dates[test_idx[-1]].date()} purge={test_idx[0] - expanding_idx[-1] - 1}"
        )

        y_test = y_np[test_idx]
        x_test = windows.x[test_idx].cpu()
        for scheme, train_idx in train_sets.items():
            pred = _fit_cnn(windows.x[train_idx].cpu(), windows.y[train_idx].cpu(), x_test)
            print(
                f"S1 TRAINING_COMPARE TRAIN id={fold_id} scheme={scheme} n={len(train_idx)} "
                f"train_first={dates[train_idx[0]].date()} train_last={dates[train_idx[-1]].date()}"
            )
            for j, h in enumerate(HORIZONS):
                m = _metrics(y_test[:, j], pred[:, j])
                results[scheme][h].append(m)
                print(
                    f"S1 TRAINING_COMPARE FOLD_METRIC id={fold_id} scheme={scheme} horizon={h} "
                    f"spearman={_fmt(m['spearman'])} mae={m['mae']:.6f} "
                    f"realized_all={m['overall']:.6f} top20={m['top20']:.6f} "
                    f"top_minus_all={m['top_minus_all']:.6f} "
                    f"top_minus_bottom={m['top_minus_bottom']:.6f}"
                )

    for scheme in schemes:
        for h in HORIZONS:
            rows = results[scheme][h]
            spearman = np.asarray([r["spearman"] for r in rows], dtype=float)
            mae = np.asarray([r["mae"] for r in rows], dtype=float)
            lift = np.asarray([r["top_minus_all"] for r in rows], dtype=float)
            spread = np.asarray([r["top_minus_bottom"] for r in rows], dtype=float)
            valid_rank = np.isfinite(spearman)
            print(
                f"S1 TRAINING_COMPARE SUMMARY scheme={scheme} horizon={h} folds={len(rows)} "
                f"spearman_mean={_fmt(np.nanmean(spearman) if valid_rank.any() else float('nan'))} "
                f"spearman_positive={int(np.sum(spearman[valid_rank] > 0))}/{int(valid_rank.sum())} "
                f"mae_mean={mae.mean():.6f} "
                f"top20_lift_mean={lift.mean():.6f} "
                f"top20_lift_positive={int(np.sum(lift > 0))}/{len(lift)} "
                f"top_bottom_mean={spread.mean():.6f}"
            )

    print("S1 TRAINING_COMPARE PASS")


if __name__ == "__main__":
    main()

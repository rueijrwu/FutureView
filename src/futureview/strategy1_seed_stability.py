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
SEEDS = (20260821, 20260822, 20260823, 20260824, 20260825)
SCHEMES = ("EXPANDING", "SLIDING_260", "SLIDING_320")
EPOCHS = 20
LEARNING_RATE = 3e-3
HUBER_DELTA = 0.01
TOP_FRACTION = 0.20
PURGE = 60
TEST_SIZE = 60
MIN_EXPANDING_TRAIN = 320


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
        return model(x_test).cpu().numpy().astype(float)


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


def _mean_std(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    valid = arr[np.isfinite(arr)]
    if not len(valid):
        return float("nan"), float("nan")
    return float(valid.mean()), float(valid.std(ddof=0))


def main() -> None:
    torch.set_num_threads(2)
    df = download_spy_daily(period="3y")
    features = make_causal_features(df)
    targets = make_strategy1_targets(df)
    windows = build_windows(features, targets, lookback=50, target_columns=STRATEGY1_TARGET_COLUMNS)
    all_folds = purged_expanding_walk_forward(
        len(windows.y),
        min_train=MIN_EXPANDING_TRAIN,
        test_size=TEST_SIZE,
        purge=PURGE,
        step=TEST_SIZE,
    )
    folds = tuple(f for f in all_folds if len(f.test) == TEST_SIZE)
    if not folds:
        raise RuntimeError("no complete common OOS folds")

    y_np = windows.y.numpy().astype(float)
    dates = pd.to_datetime(windows.dates)
    results: dict[str, dict[int, dict[int, list[dict[str, float]]]]] = {
        scheme: {
            seed: {h: [] for h in HORIZONS}
            for seed in SEEDS
        }
        for scheme in SCHEMES
    }

    print(
        f"S1 SEED_STABILITY DATA windows={len(y_np)} folds={len(folds)} "
        f"first={dates[0].date()} last={dates[-1].date()} epochs={EPOCHS} "
        f"purge={PURGE} test_size={TEST_SIZE} seeds={','.join(map(str, SEEDS))}"
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
            f"S1 SEED_STABILITY FOLD id={fold_id} "
            f"test_first={dates[test_idx[0]].date()} test_last={dates[test_idx[-1]].date()} "
            f"purge={test_idx[0] - expanding_idx[-1] - 1}"
        )

        y_test = y_np[test_idx]
        x_test = windows.x[test_idx].cpu()
        for scheme, train_idx in train_sets.items():
            print(
                f"S1 SEED_STABILITY TRAIN id={fold_id} scheme={scheme} n={len(train_idx)} "
                f"train_first={dates[train_idx[0]].date()} train_last={dates[train_idx[-1]].date()}"
            )
            x_train = windows.x[train_idx].cpu()
            y_train = windows.y[train_idx].cpu()
            for seed in SEEDS:
                pred = _fit_cnn(x_train, y_train, x_test, seed=seed)
                for j, h in enumerate(HORIZONS):
                    m = _metrics(y_test[:, j], pred[:, j])
                    results[scheme][seed][h].append(m)
                    print(
                        f"S1 SEED_STABILITY FOLD_METRIC id={fold_id} scheme={scheme} "
                        f"seed={seed} horizon={h} spearman={_fmt(m['spearman'])} "
                        f"mae={m['mae']:.6f} top_minus_all={_fmt(m['top_minus_all'])} "
                        f"top_minus_bottom={_fmt(m['top_minus_bottom'])}"
                    )

    seed_summary: dict[str, dict[int, dict[int, dict[str, float]]]] = {
        scheme: {seed: {} for seed in SEEDS} for scheme in SCHEMES
    }
    for scheme in SCHEMES:
        for seed in SEEDS:
            for h in HORIZONS:
                rows = results[scheme][seed][h]
                spearman = np.asarray([r["spearman"] for r in rows], dtype=float)
                lift = np.asarray([r["top_minus_all"] for r in rows], dtype=float)
                mae = np.asarray([r["mae"] for r in rows], dtype=float)
                valid_rank = np.isfinite(spearman)
                valid_lift = np.isfinite(lift)
                summary = {
                    "spearman_mean": float(np.nanmean(spearman)) if valid_rank.any() else float("nan"),
                    "spearman_positive_folds": float(np.sum(spearman[valid_rank] > 0)),
                    "spearman_valid_folds": float(valid_rank.sum()),
                    "lift_mean": float(np.nanmean(lift)) if valid_lift.any() else float("nan"),
                    "lift_positive_folds": float(np.sum(lift[valid_lift] > 0)),
                    "lift_valid_folds": float(valid_lift.sum()),
                    "mae_mean": float(mae.mean()),
                }
                seed_summary[scheme][seed][h] = summary
                print(
                    f"S1 SEED_STABILITY SEED_SUMMARY scheme={scheme} seed={seed} horizon={h} "
                    f"spearman_mean={_fmt(summary['spearman_mean'])} "
                    f"spearman_positive={int(summary['spearman_positive_folds'])}/{int(summary['spearman_valid_folds'])} "
                    f"top20_lift_mean={_fmt(summary['lift_mean'])} "
                    f"top20_lift_positive={int(summary['lift_positive_folds'])}/{int(summary['lift_valid_folds'])} "
                    f"mae_mean={summary['mae_mean']:.6f}"
                )

    for scheme in SCHEMES:
        for h in HORIZONS:
            seed_spearman = [seed_summary[scheme][seed][h]["spearman_mean"] for seed in SEEDS]
            seed_lift = [seed_summary[scheme][seed][h]["lift_mean"] for seed in SEEDS]
            seed_mae = [seed_summary[scheme][seed][h]["mae_mean"] for seed in SEEDS]
            sp_mean, sp_std = _mean_std(seed_spearman)
            lift_mean, lift_std = _mean_std(seed_lift)
            mae_mean, mae_std = _mean_std(seed_mae)
            print(
                f"S1 SEED_STABILITY CROSS_SEED scheme={scheme} horizon={h} seeds={len(SEEDS)} "
                f"spearman_mean={_fmt(sp_mean)} spearman_std={_fmt(sp_std)} "
                f"spearman_positive_seeds={sum(v > 0 for v in seed_spearman if np.isfinite(v))}/{sum(np.isfinite(v) for v in seed_spearman)} "
                f"top20_lift_mean={_fmt(lift_mean)} top20_lift_std={_fmt(lift_std)} "
                f"top20_lift_positive_seeds={sum(v > 0 for v in seed_lift if np.isfinite(v))}/{sum(np.isfinite(v) for v in seed_lift)} "
                f"mae_mean={_fmt(mae_mean)} mae_std={_fmt(mae_std)}"
            )

    for scheme in SCHEMES:
        for fold_id in range(1, len(folds) + 1):
            for h in HORIZONS:
                fold_spearman = [
                    results[scheme][seed][h][fold_id - 1]["spearman"] for seed in SEEDS
                ]
                fold_lift = [
                    results[scheme][seed][h][fold_id - 1]["top_minus_all"] for seed in SEEDS
                ]
                sp_mean, sp_std = _mean_std(fold_spearman)
                lift_mean, lift_std = _mean_std(fold_lift)
                print(
                    f"S1 SEED_STABILITY FOLD_SEED scheme={scheme} fold={fold_id} horizon={h} "
                    f"spearman_mean={_fmt(sp_mean)} spearman_std={_fmt(sp_std)} "
                    f"spearman_positive_seeds={sum(v > 0 for v in fold_spearman if np.isfinite(v))}/{sum(np.isfinite(v) for v in fold_spearman)} "
                    f"top20_lift_mean={_fmt(lift_mean)} top20_lift_std={_fmt(lift_std)} "
                    f"top20_lift_positive_seeds={sum(v > 0 for v in fold_lift if np.isfinite(v))}/{sum(np.isfinite(v) for v in fold_lift)}"
                )

    print("S1 SEED_STABILITY PASS")


if __name__ == "__main__":
    main()

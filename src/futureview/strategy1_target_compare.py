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
from .strategy1 import STRATEGY1_HORIZONS, make_strategy1_oracle_labels
from .strategy1_targets import STRATEGY1_TARGET_COLUMNS, make_strategy1_targets
from .walkforward import purged_expanding_walk_forward

HORIZONS = STRATEGY1_HORIZONS
TARGET_HORIZON = 30
TARGET_INDEX = HORIZONS.index(TARGET_HORIZON)
SEEDS = (20260821, 20260822, 20260823, 20260824, 20260825)
TARGETS = ("RAW_ORACLE", "EXPOSURE_EFFICIENCY")
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


def _top_indices(y_pred: np.ndarray) -> np.ndarray:
    if np.std(y_pred) < 1e-12:
        return np.asarray([], dtype=int)
    n_top = max(1, int(math.ceil(len(y_pred) * TOP_FRACTION)))
    return np.argsort(y_pred, kind="stable")[-n_top:]


def _lift(values: np.ndarray, selected: np.ndarray) -> tuple[float, float, float]:
    overall = float(np.mean(values))
    if not len(selected):
        return overall, float("nan"), float("nan")
    top = float(np.mean(values[selected]))
    return overall, top, top - overall


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
    arr = arr[np.isfinite(arr)]
    if not len(arr):
        return float("nan"), float("nan")
    return float(arr.mean()), float(arr.std(ddof=0))


def _make_efficiency_targets(df: pd.DataFrame) -> tuple[pd.DataFrame, tuple[str, ...]]:
    labels = make_strategy1_oracle_labels(df, horizons=HORIZONS)
    columns = tuple(f"oracle_s1_eff_{h}" for h in HORIZONS)
    rename = {
        f"oracle_return_per_exposure_day_{h}": f"oracle_s1_eff_{h}"
        for h in HORIZONS
    }
    out = labels.loc[:, ["date", *rename.keys()]].rename(columns=rename)
    values = out.loc[:, list(columns)].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("non-finite Strategy 1 exposure-efficiency target")
    if (values < -1e-12).any():
        raise ValueError("Strategy 1 exposure-efficiency targets must be non-negative")
    return out.reset_index(drop=True), columns


def main() -> None:
    torch.set_num_threads(2)
    df = download_spy_daily(period="3y")
    features = make_causal_features(df)

    raw_targets = make_strategy1_targets(df, horizons=HORIZONS)
    eff_targets, eff_columns = _make_efficiency_targets(df)
    raw_windows = build_windows(
        features,
        raw_targets,
        lookback=50,
        target_columns=STRATEGY1_TARGET_COLUMNS,
    )
    eff_windows = build_windows(
        features,
        eff_targets,
        lookback=50,
        target_columns=eff_columns,
    )

    raw_dates = pd.to_datetime(raw_windows.dates)
    eff_dates = pd.to_datetime(eff_windows.dates)
    if len(raw_dates) != len(eff_dates) or not np.array_equal(raw_dates.to_numpy(), eff_dates.to_numpy()):
        raise RuntimeError("raw and efficiency target windows are not date-aligned")
    if raw_windows.x.shape != eff_windows.x.shape or not torch.equal(raw_windows.x, eff_windows.x):
        raise RuntimeError("raw and efficiency target experiments do not share identical inputs")

    all_folds = purged_expanding_walk_forward(
        len(raw_windows.y),
        min_train=MIN_EXPANDING_TRAIN,
        test_size=TEST_SIZE,
        purge=PURGE,
        step=TEST_SIZE,
    )
    folds = tuple(f for f in all_folds if len(f.test) == TEST_SIZE)
    if not folds:
        raise RuntimeError("no complete common OOS folds")

    raw_y = raw_windows.y.numpy().astype(float)
    eff_y = eff_windows.y.numpy().astype(float)
    target_windows = {
        "RAW_ORACLE": raw_windows,
        "EXPOSURE_EFFICIENCY": eff_windows,
    }
    results: dict[str, dict[int, list[dict[str, float]]]] = {
        target: {seed: [] for seed in SEEDS} for target in TARGETS
    }

    print(
        f"S1 TARGET_COMPARE DATA windows={len(raw_y)} folds={len(folds)} "
        f"first={raw_dates[0].date()} last={raw_dates[-1].date()} horizon={TARGET_HORIZON} "
        f"train=SLIDING_{SLIDING_TRAIN} epochs={EPOCHS} purge={PURGE} test_size={TEST_SIZE} "
        f"seeds={','.join(map(str, SEEDS))}"
    )

    for fold_id, fold in enumerate(folds, start=1):
        expanding_idx = fold.train
        test_idx = fold.test
        train_end = int(expanding_idx[-1]) + 1
        train_idx = np.arange(train_end - SLIDING_TRAIN, train_end, dtype=int)
        if train_idx[0] < 0:
            raise RuntimeError("sliding train window begins before dataset")

        print(
            f"S1 TARGET_COMPARE FOLD id={fold_id} n_train={len(train_idx)} "
            f"train_first={raw_dates[train_idx[0]].date()} train_last={raw_dates[train_idx[-1]].date()} "
            f"test_first={raw_dates[test_idx[0]].date()} test_last={raw_dates[test_idx[-1]].date()} "
            f"purge={test_idx[0] - expanding_idx[-1] - 1}"
        )

        raw_test = raw_y[test_idx, TARGET_INDEX]
        eff_test = eff_y[test_idx, TARGET_INDEX]
        x_test = raw_windows.x[test_idx].cpu()

        for target_name in TARGETS:
            windows = target_windows[target_name]
            y_test_self = windows.y[test_idx, TARGET_INDEX].numpy().astype(float)
            x_train = windows.x[train_idx].cpu()
            y_train = windows.y[train_idx].cpu()

            for seed in SEEDS:
                pred = _fit_cnn(x_train, y_train, x_test, seed=seed)[:, TARGET_INDEX]
                selected = _top_indices(pred)
                self_spearman = _spearman(y_test_self, pred)
                _, _, self_lift = _lift(y_test_self, selected)
                raw_all, raw_top, raw_lift = _lift(raw_test, selected)
                eff_all, eff_top, eff_lift = _lift(eff_test, selected)
                mae = float(np.mean(np.abs(y_test_self - pred)))
                row = {
                    "self_spearman": self_spearman,
                    "self_lift": self_lift,
                    "raw_top": raw_top,
                    "raw_lift": raw_lift,
                    "eff_top": eff_top,
                    "eff_lift": eff_lift,
                    "mae": mae,
                }
                results[target_name][seed].append(row)
                print(
                    f"S1 TARGET_COMPARE FOLD_METRIC id={fold_id} target={target_name} seed={seed} "
                    f"self_spearman={_fmt(self_spearman)} self_top20_lift={_fmt(self_lift)} "
                    f"raw_all={raw_all:.6f} raw_top20={_fmt(raw_top)} raw_lift={_fmt(raw_lift)} "
                    f"eff_all={eff_all:.6f} eff_top20={_fmt(eff_top)} eff_lift={_fmt(eff_lift)} "
                    f"mae={mae:.6f}"
                )

    seed_summary: dict[str, dict[int, dict[str, float]]] = {
        target: {} for target in TARGETS
    }
    for target_name in TARGETS:
        for seed in SEEDS:
            rows = results[target_name][seed]
            summary = {
                key: float(np.nanmean([r[key] for r in rows]))
                for key in ("self_spearman", "self_lift", "raw_lift", "eff_lift", "mae")
            }
            seed_summary[target_name][seed] = summary
            print(
                f"S1 TARGET_COMPARE SEED_SUMMARY target={target_name} seed={seed} folds={len(rows)} "
                f"self_spearman_mean={_fmt(summary['self_spearman'])} "
                f"self_top20_lift_mean={_fmt(summary['self_lift'])} "
                f"raw_lift_mean={_fmt(summary['raw_lift'])} "
                f"eff_lift_mean={_fmt(summary['eff_lift'])} mae_mean={summary['mae']:.6f}"
            )

    for target_name in TARGETS:
        summaries = seed_summary[target_name]
        metrics = {}
        for key in ("self_spearman", "self_lift", "raw_lift", "eff_lift", "mae"):
            values = [summaries[seed][key] for seed in SEEDS]
            metrics[key] = (*_mean_std(values), sum(v > 0 for v in values if np.isfinite(v)))
        print(
            f"S1 TARGET_COMPARE CROSS_SEED target={target_name} seeds={len(SEEDS)} "
            f"self_spearman_mean={_fmt(metrics['self_spearman'][0])} self_spearman_std={_fmt(metrics['self_spearman'][1])} "
            f"self_spearman_positive={metrics['self_spearman'][2]}/{len(SEEDS)} "
            f"self_top20_lift_mean={_fmt(metrics['self_lift'][0])} self_top20_lift_std={_fmt(metrics['self_lift'][1])} "
            f"raw_lift_mean={_fmt(metrics['raw_lift'][0])} raw_lift_std={_fmt(metrics['raw_lift'][1])} "
            f"raw_lift_positive={metrics['raw_lift'][2]}/{len(SEEDS)} "
            f"eff_lift_mean={_fmt(metrics['eff_lift'][0])} eff_lift_std={_fmt(metrics['eff_lift'][1])} "
            f"eff_lift_positive={metrics['eff_lift'][2]}/{len(SEEDS)} "
            f"mae_mean={_fmt(metrics['mae'][0])} mae_std={_fmt(metrics['mae'][1])}"
        )

    for target_name in TARGETS:
        for fold_id in range(1, len(folds) + 1):
            for key in ("self_spearman", "raw_lift", "eff_lift"):
                values = [results[target_name][seed][fold_id - 1][key] for seed in SEEDS]
                mean, std = _mean_std(values)
                positive = sum(v > 0 for v in values if np.isfinite(v))
                print(
                    f"S1 TARGET_COMPARE FOLD_SEED target={target_name} fold={fold_id} metric={key} "
                    f"mean={_fmt(mean)} std={_fmt(std)} positive={positive}/{len(SEEDS)}"
                )

    print("S1 TARGET_COMPARE PASS")


if __name__ == "__main__":
    main()

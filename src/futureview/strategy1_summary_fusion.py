from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_spy_daily
from .datasets import build_windows
from .features import make_causal_features
from .models import MultiScaleBlock, TrendCNNJoint, count_parameters
from .strategy1_summary_baseline import (
    EPOCHS,
    HUBER_DELTA,
    LEARNING_RATE,
    MIN_EXPANDING_TRAIN,
    PURGE,
    SEEDS,
    SLIDING_TRAIN,
    TARGET_HORIZON,
    TARGET_INDEX,
    TEST_SIZE,
    _mean_std,
    _metrics,
    _summary_features,
)
from .strategy1_targets import STRATEGY1_TARGET_COLUMNS, make_strategy1_targets
from .walkforward import purged_expanding_walk_forward

SUMMARY_DIM = 20


class TrendCNNJointSummary20(nn.Module):
    """Model A encoder plus 20 standardized causal summary features.

    The CNN encoder is identical to TrendCNNJoint through global pooling. The
    pooled 16-dimensional CNN representation is concatenated with 20 summary
    features, then passed through the same 8-unit output-head width used by
    Model A.
    """

    def __init__(self) -> None:
        super().__init__()
        self.multi = MultiScaleBlock(5, branch_channels=8)
        self.fusion = nn.Sequential(
            nn.Conv1d(self.multi.out_channels, 16, kernel_size=3, padding="same"),
            nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Sequential(
            nn.Linear(16 + SUMMARY_DIM, 8),
            nn.GELU(),
            nn.Linear(8, len(STRATEGY1_TARGET_COLUMNS)),
            nn.Tanh(),
        )

    def forward(self, x: torch.Tensor, summary: torch.Tensor) -> torch.Tensor:
        if x.ndim != 3 or x.shape[1] != 5:
            raise ValueError(f"expected x [batch, 5, time], got {tuple(x.shape)}")
        if summary.ndim != 2 or summary.shape[1] != SUMMARY_DIM:
            raise ValueError(f"expected summary [batch, {SUMMARY_DIM}], got {tuple(summary.shape)}")
        if x.shape[0] != summary.shape[0]:
            raise ValueError("x and summary batch sizes differ")
        cnn = self.fusion(self.multi(x)).flatten(1)
        return self.head(torch.cat([cnn, summary], dim=1))


def _standardize_summary(
    summary_train: np.ndarray,
    summary_eval: np.ndarray,
) -> tuple[torch.Tensor, torch.Tensor]:
    mean = summary_train.mean(axis=0)
    std = summary_train.std(axis=0, ddof=0)
    std = np.where(std < 1e-12, 1.0, std)
    z_train = (summary_train - mean) / std
    z_eval = (summary_eval - mean) / std
    if not np.isfinite(z_train).all() or not np.isfinite(z_eval).all():
        raise RuntimeError("non-finite standardized summary features")
    return (
        torch.from_numpy(z_train.astype(np.float32)),
        torch.from_numpy(z_eval.astype(np.float32)),
    )


def _fit_baseline(
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
        pred = model(x_train)
        loss = loss_fn(pred, y_train)
        loss.backward()
        optimizer.step()
    model.eval()
    with torch.no_grad():
        return model(x_test).cpu().numpy().astype(float)[:, TARGET_INDEX]


def _fit_fusion(
    x_train: torch.Tensor,
    y_train: torch.Tensor,
    summary_train: torch.Tensor,
    x_test: torch.Tensor,
    summary_test: torch.Tensor,
    *,
    seed: int,
) -> np.ndarray:
    torch.manual_seed(seed)
    model = TrendCNNJointSummary20().cpu()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    loss_fn = nn.HuberLoss(delta=HUBER_DELTA)
    model.train()
    for _ in range(EPOCHS):
        optimizer.zero_grad(set_to_none=True)
        pred = model(x_train, summary_train)
        loss = loss_fn(pred, y_train)
        loss.backward()
        optimizer.step()
    model.eval()
    with torch.no_grad():
        return model(x_test, summary_test).cpu().numpy().astype(float)[:, TARGET_INDEX]


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


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
    dates = pd.DatetimeIndex(pd.to_datetime(windows.dates))
    y = windows.y.numpy().astype(float)[:, TARGET_INDEX]
    summary_x = _summary_features(windows.x)
    if summary_x.shape != (len(windows.x), SUMMARY_DIM):
        raise RuntimeError(f"unexpected summary matrix shape: {summary_x.shape}")

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

    model_params = {
        "CNN_A": count_parameters(TrendCNNJoint()),
        "CNN_A_PLUS_SUMMARY20": count_parameters(TrendCNNJointSummary20()),
    }
    results: dict[str, dict[int, list[dict[str, float]]]] = {
        name: {seed: [] for seed in SEEDS} for name in model_params
    }

    print(
        f"S1 SUMMARY_FUSION DATA windows={len(y)} folds={len(folds)} horizon={TARGET_HORIZON} "
        f"train=SLIDING_{SLIDING_TRAIN} epochs={EPOCHS} purge={PURGE} test_size={TEST_SIZE} "
        f"summary_dim={SUMMARY_DIM} first={dates[0].date()} last={dates[-1].date()} "
        f"seeds={','.join(map(str, SEEDS))}"
    )
    print(
        "S1 SUMMARY_FUSION RULE cnn_encoder_unchanged=true summary_features=20 "
        "summary_standardization=training_only concat=cnn16_plus_summary20 head_hidden=8 "
        "target=30D_RAW_ORACLE no_random_split=true"
    )
    for name, params in model_params.items():
        print(f"S1 SUMMARY_FUSION MODEL name={name} params={params}")

    for fold_id, fold in enumerate(folds, start=1):
        train_end = int(fold.train[-1]) + 1
        train_idx = np.arange(train_end - SLIDING_TRAIN, train_end, dtype=int)
        test_idx = fold.test
        if train_idx[0] < 0:
            raise RuntimeError("sliding train window begins before dataset")

        x_train = windows.x[train_idx].cpu()
        y_train = windows.y[train_idx].cpu()
        x_test = windows.x[test_idx].cpu()
        y_test = y[test_idx]
        summary_train, summary_test = _standardize_summary(
            summary_x[train_idx], summary_x[test_idx]
        )

        print(
            f"S1 SUMMARY_FUSION FOLD id={fold_id} n_train={len(train_idx)} "
            f"train_first={dates[train_idx[0]].date()} train_last={dates[train_idx[-1]].date()} "
            f"test_first={dates[test_idx[0]].date()} test_last={dates[test_idx[-1]].date()} "
            f"purge={test_idx[0] - fold.train[-1] - 1}"
        )

        for seed in SEEDS:
            baseline_pred = _fit_baseline(x_train, y_train, x_test, seed=seed)
            baseline_m = _metrics(y_test, baseline_pred)
            results["CNN_A"][seed].append(baseline_m)
            print(
                f"S1 SUMMARY_FUSION FOLD_METRIC id={fold_id} model=CNN_A seed={seed} "
                f"spearman={_fmt(baseline_m['spearman'])} mae={baseline_m['mae']:.6f} "
                f"top20_lift={_fmt(baseline_m['top_minus_all'])} "
                f"top_bottom={_fmt(baseline_m['top_minus_bottom'])}"
            )

            fusion_pred = _fit_fusion(
                x_train,
                y_train,
                summary_train,
                x_test,
                summary_test,
                seed=seed,
            )
            fusion_m = _metrics(y_test, fusion_pred)
            results["CNN_A_PLUS_SUMMARY20"][seed].append(fusion_m)
            print(
                f"S1 SUMMARY_FUSION FOLD_METRIC id={fold_id} model=CNN_A_PLUS_SUMMARY20 seed={seed} "
                f"spearman={_fmt(fusion_m['spearman'])} mae={fusion_m['mae']:.6f} "
                f"top20_lift={_fmt(fusion_m['top_minus_all'])} "
                f"top_bottom={_fmt(fusion_m['top_minus_bottom'])}"
            )

    seed_summary: dict[str, dict[int, dict[str, float]]] = {name: {} for name in results}
    for model_name in results:
        for seed in SEEDS:
            rows = results[model_name][seed]
            summary = {
                "spearman": float(np.nanmean([r["spearman"] for r in rows])),
                "lift": float(np.nanmean([r["top_minus_all"] for r in rows])),
                "mae": float(np.mean([r["mae"] for r in rows])),
            }
            seed_summary[model_name][seed] = summary
            print(
                f"S1 SUMMARY_FUSION SEED_SUMMARY model={model_name} seed={seed} folds={len(rows)} "
                f"spearman_mean={_fmt(summary['spearman'])} "
                f"top20_lift_mean={_fmt(summary['lift'])} mae_mean={summary['mae']:.6f}"
            )

    for model_name in results:
        for key, label in (("spearman", "spearman"), ("lift", "top20_lift"), ("mae", "mae")):
            values = [seed_summary[model_name][seed][key] for seed in SEEDS]
            mean, std = _mean_std(values)
            positive = sum(v > 0 for v in values if np.isfinite(v))
            print(
                f"S1 SUMMARY_FUSION CROSS_SEED model={model_name} metric={label} "
                f"mean={_fmt(mean)} std={_fmt(std)} positive={positive}/{len(SEEDS)}"
            )

    for fold_id in range(1, len(folds) + 1):
        for model_name in results:
            for key, label in (("spearman", "spearman"), ("top_minus_all", "top20_lift")):
                values = [results[model_name][seed][fold_id - 1][key] for seed in SEEDS]
                mean, std = _mean_std(values)
                positive = sum(v > 0 for v in values if np.isfinite(v))
                print(
                    f"S1 SUMMARY_FUSION FOLD_SEED fold={fold_id} model={model_name} "
                    f"metric={label} mean={_fmt(mean)} std={_fmt(std)} "
                    f"positive={positive}/{len(SEEDS)}"
                )

    print("S1 SUMMARY_FUSION PASS")


if __name__ == "__main__":
    main()

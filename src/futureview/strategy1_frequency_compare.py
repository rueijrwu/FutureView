from __future__ import annotations

import math

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_spy_daily
from .datasets import build_windows
from .features import FEATURE_COLUMNS, make_causal_features
from .massive_data import aggregate_rth_two_bars, download_spy_intraday_massive
from .models import TrendCNNJoint, count_parameters
from .strategy1_targets import STRATEGY1_TARGET_COLUMNS, make_strategy1_targets
from .walkforward import purged_expanding_walk_forward

HORIZONS = (15, 30, 45, 60)
TARGET_HORIZON = 30
TARGET_INDEX = HORIZONS.index(TARGET_HORIZON)
SEEDS = (20260821, 20260822, 20260823, 20260824, 20260825)
EPOCHS = 20
LEARNING_RATE = 3e-3
HUBER_DELTA = 0.01
TOP_FRACTION = 0.20
PURGE = 60
TEST_SIZE = 60
MIN_EXPANDING_TRAIN = 320
SLIDING_TRAIN = 260
DAILY_LOOKBACK = 50
INTRADAY_BARS_PER_SESSION = 2
INTRADAY_LOOKBACK = DAILY_LOOKBACK * INTRADAY_BARS_PER_SESSION
INTRADAY_VOLUME_WINDOW = 20 * INTRADAY_BARS_PER_SESSION


class MultiScaleBlockVariable(nn.Module):
    def __init__(self, in_channels: int, kernels: tuple[int, int, int], branch_channels: int = 8) -> None:
        super().__init__()
        self.branches = nn.ModuleList(
            [
                nn.Sequential(
                    nn.Conv1d(in_channels, branch_channels, kernel_size=k, padding="same"),
                    nn.GELU(),
                )
                for k in kernels
            ]
        )

    @property
    def out_channels(self) -> int:
        return len(self.branches) * self.branches[0][0].out_channels

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.cat([branch(x) for branch in self.branches], dim=1)


class TrendCNNJointVariable(nn.Module):
    """Model-A topology with configurable temporal kernels."""

    def __init__(self, kernels: tuple[int, int, int]) -> None:
        super().__init__()
        self.multi = MultiScaleBlockVariable(5, kernels=kernels, branch_channels=8)
        self.fusion = nn.Sequential(
            nn.Conv1d(self.multi.out_channels, 16, kernel_size=3, padding="same"),
            nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(16, 8),
            nn.GELU(),
            nn.Linear(8, len(HORIZONS)),
            nn.Tanh(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 3 or x.shape[1] != 5:
            raise ValueError(f"expected [batch, 5, time], got {tuple(x.shape)}")
        return self.head(self.fusion(self.multi(x)))


def _intraday_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy().sort_values("timestamp").reset_index(drop=True)
    prev_close = out["close"].shift(1)
    out["open_rel"] = out["open"] / prev_close - 1.0
    out["high_rel"] = out["high"] / prev_close - 1.0
    out["low_rel"] = out["low"] / prev_close - 1.0
    out["close_rel"] = out["close"] / prev_close - 1.0
    log_volume = np.log(out["volume"].clip(lower=1).astype(float))
    mean = log_volume.rolling(INTRADAY_VOLUME_WINDOW, min_periods=INTRADAY_VOLUME_WINDOW).mean()
    std = log_volume.rolling(INTRADAY_VOLUME_WINDOW, min_periods=INTRADAY_VOLUME_WINDOW).std(ddof=0)
    out["volume_z"] = (log_volume - mean) / std.replace(0.0, np.nan)
    return (
        out.loc[:, ["timestamp", "date", "session_bar", *FEATURE_COLUMNS]]
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .reset_index(drop=True)
    )


def _build_intraday_windows(
    features: pd.DataFrame,
    targets: pd.DataFrame,
) -> tuple[torch.Tensor, torch.Tensor, np.ndarray]:
    target_by_date = targets.copy()
    target_by_date["date"] = pd.to_datetime(target_by_date["date"]).dt.normalize()
    target_by_date = target_by_date.set_index("date").sort_index()
    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    dates: list[pd.Timestamp] = []
    values = features.loc[:, FEATURE_COLUMNS].to_numpy(dtype=np.float32)

    for end in range(INTRADAY_LOOKBACK - 1, len(features)):
        if int(features.at[end, "session_bar"]) != 1:
            continue
        date = pd.Timestamp(features.at[end, "date"]).normalize()
        start = end - INTRADAY_LOOKBACK + 1
        window = features.iloc[start : end + 1]
        counts = window.groupby("date")["session_bar"].nunique()
        if len(counts) != DAILY_LOOKBACK or not (counts == 2).all():
            continue
        if date not in target_by_date.index:
            continue
        x = values[start : end + 1].T
        y = target_by_date.loc[date, list(STRATEGY1_TARGET_COLUMNS)].to_numpy(dtype=np.float32)
        if np.isfinite(x).all() and np.isfinite(y).all():
            xs.append(x)
            ys.append(y)
            dates.append(date)

    if not xs:
        raise RuntimeError("no aligned 50-session intraday windows")
    return torch.from_numpy(np.stack(xs)), torch.from_numpy(np.stack(ys)), np.asarray(dates)


def _rankdata(values: np.ndarray) -> np.ndarray:
    return pd.Series(values).rank(method="average").to_numpy(dtype=float)


def _spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) < 2 or np.std(y_pred) < 1e-12:
        return float("nan")
    a = _rankdata(y_true)
    b = _rankdata(y_pred)
    if np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    mae = float(np.mean(np.abs(y_true - y_pred)))
    spearman = _spearman(y_true, y_pred)
    if np.std(y_pred) < 1e-12:
        return {"mae": mae, "spearman": float("nan"), "lift": float("nan"), "top_bottom": float("nan")}
    n_top = max(1, int(math.ceil(len(y_pred) * TOP_FRACTION)))
    order = np.argsort(y_pred, kind="stable")
    top = float(np.mean(y_true[order[-n_top:]]))
    bottom = float(np.mean(y_true[order[:n_top]]))
    return {
        "mae": mae,
        "spearman": spearman,
        "lift": top - float(np.mean(y_true)),
        "top_bottom": top - bottom,
    }


def _fit_model(
    model: nn.Module,
    x_train: torch.Tensor,
    y_train: torch.Tensor,
    x_test: torch.Tensor,
    seed: int,
) -> np.ndarray:
    torch.manual_seed(seed)
    for module in model.modules():
        if hasattr(module, "reset_parameters"):
            module.reset_parameters()
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
    daily = download_spy_daily(period="3y")
    targets = make_strategy1_targets(daily)
    daily_features = make_causal_features(daily)
    daily_windows = build_windows(
        daily_features,
        targets,
        lookback=DAILY_LOOKBACK,
        target_columns=STRATEGY1_TARGET_COLUMNS,
    )

    start = pd.Timestamp(daily["date"].min()).date().isoformat()
    end = pd.Timestamp(daily["date"].max()).date().isoformat()
    intraday_raw = download_spy_intraday_massive(start, end)
    intraday_two = aggregate_rth_two_bars(intraday_raw)
    intraday_features = _intraday_features(intraday_two)
    intraday_x, intraday_y, intraday_dates = _build_intraday_windows(intraday_features, targets)

    daily_date_map = {pd.Timestamp(d).normalize(): i for i, d in enumerate(pd.to_datetime(daily_windows.dates))}
    intra_date_map = {pd.Timestamp(d).normalize(): i for i, d in enumerate(pd.to_datetime(intraday_dates))}
    common_dates = np.asarray(sorted(set(daily_date_map).intersection(intra_date_map)), dtype="datetime64[ns]")
    if len(common_dates) < MIN_EXPANDING_TRAIN + PURGE + TEST_SIZE:
        raise RuntimeError(f"insufficient common Daily/Intraday dates: {len(common_dates)}")

    daily_idx = np.asarray([daily_date_map[pd.Timestamp(d).normalize()] for d in common_dates], dtype=int)
    intra_idx = np.asarray([intra_date_map[pd.Timestamp(d).normalize()] for d in common_dates], dtype=int)
    daily_x = daily_windows.x[daily_idx].cpu()
    daily_y = daily_windows.y[daily_idx].cpu()
    intra_x = intraday_x[intra_idx].cpu()
    intra_y = intraday_y[intra_idx].cpu()
    if not torch.equal(daily_y, intra_y):
        raise RuntimeError("Daily and intraday experiments are not target-aligned")

    all_folds = purged_expanding_walk_forward(
        len(common_dates),
        min_train=MIN_EXPANDING_TRAIN,
        test_size=TEST_SIZE,
        purge=PURGE,
        step=TEST_SIZE,
    )
    folds = tuple(f for f in all_folds if len(f.test) == TEST_SIZE)
    if not folds:
        raise RuntimeError("no complete common OOS folds")

    model_factories = {
        "DAILY_50_K5_10_20": lambda: TrendCNNJoint().cpu(),
        "RTH2_100_K5_10_20": lambda: TrendCNNJointVariable((5, 10, 20)).cpu(),
        "RTH2_100_K10_20_40": lambda: TrendCNNJointVariable((10, 20, 40)).cpu(),
    }
    x_by_model = {
        "DAILY_50_K5_10_20": daily_x,
        "RTH2_100_K5_10_20": intra_x,
        "RTH2_100_K10_20_40": intra_x,
    }
    results: dict[str, dict[int, list[dict[str, float]]]] = {
        name: {seed: [] for seed in SEEDS} for name in model_factories
    }

    print(
        f"S1 FREQUENCY_COMPARE DATA common_windows={len(common_dates)} folds={len(folds)} "
        f"first={pd.Timestamp(common_dates[0]).date()} last={pd.Timestamp(common_dates[-1]).date()} "
        f"horizon={TARGET_HORIZON} train=SLIDING_{SLIDING_TRAIN} epochs={EPOCHS} "
        f"purge={PURGE} test_size={TEST_SIZE}"
    )
    print(
        f"S1 FREQUENCY_COMPARE INPUT daily_bars={DAILY_LOOKBACK} intraday_bars={INTRADAY_LOOKBACK} "
        f"sessions={DAILY_LOOKBACK} intraday_per_session=2 rth_bar1=09:30-13:30 "
        f"rth_bar2=13:30-16:00 intraday_volume_window={INTRADAY_VOLUME_WINDOW}"
    )
    for name, factory in model_factories.items():
        print(f"S1 FREQUENCY_COMPARE MODEL name={name} params={count_parameters(factory())}")

    for fold_id, fold in enumerate(folds, start=1):
        train_end = int(fold.train[-1]) + 1
        train_idx = np.arange(train_end - SLIDING_TRAIN, train_end, dtype=int)
        test_idx = fold.test
        if train_idx[0] < 0:
            raise RuntimeError("sliding train window begins before common dataset")
        print(
            f"S1 FREQUENCY_COMPARE FOLD id={fold_id} "
            f"train_first={pd.Timestamp(common_dates[train_idx[0]]).date()} "
            f"train_last={pd.Timestamp(common_dates[train_idx[-1]]).date()} "
            f"test_first={pd.Timestamp(common_dates[test_idx[0]]).date()} "
            f"test_last={pd.Timestamp(common_dates[test_idx[-1]]).date()} "
            f"purge={test_idx[0] - fold.train[-1] - 1}"
        )
        y_test = daily_y[test_idx, TARGET_INDEX].numpy().astype(float)
        for model_name, factory in model_factories.items():
            x_all = x_by_model[model_name]
            for seed in SEEDS:
                pred = _fit_model(factory(), x_all[train_idx], daily_y[train_idx], x_all[test_idx], seed)
                m = _metrics(y_test, pred)
                results[model_name][seed].append(m)
                print(
                    f"S1 FREQUENCY_COMPARE FOLD_METRIC id={fold_id} model={model_name} seed={seed} "
                    f"spearman={_fmt(m['spearman'])} mae={m['mae']:.6f} "
                    f"top20_lift={_fmt(m['lift'])} top_bottom={_fmt(m['top_bottom'])}"
                )

    seed_summary: dict[str, dict[int, dict[str, float]]] = {name: {} for name in model_factories}
    for model_name in model_factories:
        for seed in SEEDS:
            rows = results[model_name][seed]
            summary = {
                "spearman": float(np.nanmean([r["spearman"] for r in rows])),
                "lift": float(np.nanmean([r["lift"] for r in rows])),
                "mae": float(np.mean([r["mae"] for r in rows])),
            }
            seed_summary[model_name][seed] = summary
            print(
                f"S1 FREQUENCY_COMPARE SEED_SUMMARY model={model_name} seed={seed} folds={len(rows)} "
                f"spearman_mean={_fmt(summary['spearman'])} "
                f"top20_lift_mean={_fmt(summary['lift'])} mae_mean={summary['mae']:.6f}"
            )

    for model_name in model_factories:
        for key in ("spearman", "lift", "mae"):
            values = [seed_summary[model_name][seed][key] for seed in SEEDS]
            mean, std = _mean_std(values)
            positive = sum(v > 0 for v in values if np.isfinite(v))
            label = "top20_lift" if key == "lift" else key
            print(
                f"S1 FREQUENCY_COMPARE CROSS_SEED model={model_name} metric={label} "
                f"mean={_fmt(mean)} std={_fmt(std)} positive={positive}/{len(SEEDS)}"
            )

    for fold_id in range(1, len(folds) + 1):
        for model_name in model_factories:
            for key in ("spearman", "lift"):
                values = [results[model_name][seed][fold_id - 1][key] for seed in SEEDS]
                mean, std = _mean_std(values)
                positive = sum(v > 0 for v in values if np.isfinite(v))
                label = "top20_lift" if key == "lift" else key
                print(
                    f"S1 FREQUENCY_COMPARE FOLD_SEED fold={fold_id} model={model_name} metric={label} "
                    f"mean={_fmt(mean)} std={_fmt(std)} positive={positive}/{len(SEEDS)}"
                )

    print("S1 FREQUENCY_COMPARE PASS")


if __name__ == "__main__":
    main()

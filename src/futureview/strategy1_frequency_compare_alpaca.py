from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from .alpaca_data import aggregate_rth_two_bars, download_spy_intraday_alpaca
from .data import download_spy_daily
from .datasets import build_windows
from .features import make_causal_features
from .models import TrendCNNJoint, count_parameters
from .strategy1_frequency_compare import (
    DAILY_LOOKBACK,
    EPOCHS,
    INTRADAY_LOOKBACK,
    INTRADAY_VOLUME_WINDOW,
    MIN_EXPANDING_TRAIN,
    PURGE,
    SEEDS,
    SLIDING_TRAIN,
    TARGET_HORIZON,
    TARGET_INDEX,
    TEST_SIZE,
    TrendCNNJointVariable,
    _build_intraday_windows,
    _fit_model,
    _fmt,
    _intraday_features,
    _mean_std,
    _metrics,
)
from .strategy1_targets import STRATEGY1_TARGET_COLUMNS, make_strategy1_targets
from .walkforward import purged_expanding_walk_forward


def main() -> None:
    """Canonical Daily-vs-intraday frequency comparison using Alpaca IEX data."""
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
    intraday_raw = download_spy_intraday_alpaca(start, end, timeframe="30Min", feed="iex")
    intraday_two = aggregate_rth_two_bars(intraday_raw)
    intraday_features = _intraday_features(intraday_two)
    intraday_x, intraday_y, intraday_dates = _build_intraday_windows(intraday_features, targets)

    daily_date_map = {pd.Timestamp(d).normalize(): i for i, d in enumerate(pd.to_datetime(daily_windows.dates))}
    intra_date_map = {pd.Timestamp(d).normalize(): i for i, d in enumerate(pd.to_datetime(intraday_dates))}
    common_dates = np.asarray(sorted(set(daily_date_map).intersection(intra_date_map)), dtype="datetime64[ns]")
    if len(common_dates) < MIN_EXPANDING_TRAIN + PURGE + TEST_SIZE:
        raise RuntimeError(
            f"insufficient common Daily/Alpaca-IEX dates: {len(common_dates)}; "
            f"need at least {MIN_EXPANDING_TRAIN + PURGE + TEST_SIZE}"
        )

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
        f"S1 FREQUENCY_COMPARE_ALPACA DATA common_windows={len(common_dates)} folds={len(folds)} "
        f"first={pd.Timestamp(common_dates[0]).date()} last={pd.Timestamp(common_dates[-1]).date()} "
        f"horizon={TARGET_HORIZON} train=SLIDING_{SLIDING_TRAIN} epochs={EPOCHS} "
        f"purge={PURGE} test_size={TEST_SIZE} provider=alpaca feed=iex timeframe=30Min"
    )
    print(
        f"S1 FREQUENCY_COMPARE_ALPACA INPUT daily_bars={DAILY_LOOKBACK} intraday_bars={INTRADAY_LOOKBACK} "
        f"sessions={DAILY_LOOKBACK} intraday_per_session=2 rth_bar1=09:30-13:30 "
        f"rth_bar2=13:30-16:00 intraday_volume_window={INTRADAY_VOLUME_WINDOW}"
    )
    for name, factory in model_factories.items():
        print(f"S1 FREQUENCY_COMPARE_ALPACA MODEL name={name} params={count_parameters(factory())}")

    for fold_id, fold in enumerate(folds, start=1):
        train_end = int(fold.train[-1]) + 1
        train_idx = np.arange(train_end - SLIDING_TRAIN, train_end, dtype=int)
        test_idx = fold.test
        if train_idx[0] < 0:
            raise RuntimeError("sliding train window begins before common dataset")
        print(
            f"S1 FREQUENCY_COMPARE_ALPACA FOLD id={fold_id} "
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
                    f"S1 FREQUENCY_COMPARE_ALPACA FOLD_METRIC id={fold_id} model={model_name} seed={seed} "
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
                f"S1 FREQUENCY_COMPARE_ALPACA SEED_SUMMARY model={model_name} seed={seed} folds={len(rows)} "
                f"spearman_mean={_fmt(summary['spearman'])} top20_lift_mean={_fmt(summary['lift'])} "
                f"mae_mean={summary['mae']:.6f}"
            )

    for model_name in model_factories:
        for key in ("spearman", "lift", "mae"):
            values = [seed_summary[model_name][seed][key] for seed in SEEDS]
            mean, std = _mean_std(values)
            positive = sum(v > 0 for v in values if np.isfinite(v))
            label = "top20_lift" if key == "lift" else key
            print(
                f"S1 FREQUENCY_COMPARE_ALPACA CROSS_SEED model={model_name} metric={label} "
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
                    f"S1 FREQUENCY_COMPARE_ALPACA FOLD_SEED fold={fold_id} model={model_name} "
                    f"metric={label} mean={_fmt(mean)} std={_fmt(std)} positive={positive}/{len(SEEDS)}"
                )

    print("S1 FREQUENCY_COMPARE_ALPACA PASS")


if __name__ == "__main__":
    main()

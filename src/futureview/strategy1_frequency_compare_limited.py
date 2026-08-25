from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from .data import download_spy_daily
from .datasets import build_windows
from .features import make_causal_features
from .massive_data import aggregate_rth_two_bars, download_spy_intraday_massive
from .models import TrendCNNJoint, count_parameters
from .strategy1_frequency_compare import (
    DAILY_LOOKBACK,
    EPOCHS,
    INTRADAY_LOOKBACK,
    INTRADAY_VOLUME_WINDOW,
    PURGE,
    SEEDS,
    SLIDING_TRAIN,
    TARGET_HORIZON,
    TARGET_INDEX,
    TrendCNNJointVariable,
    _build_intraday_windows,
    _fit_model,
    _fmt,
    _intraday_features,
    _mean_std,
    _metrics,
)
from .strategy1_targets import STRATEGY1_TARGET_COLUMNS, make_strategy1_targets


def main() -> None:
    """Run the matched-horizon frequency test when Massive history is limited.

    This runner preserves Sliding-260 training and the 60-session purge. It uses all
    remaining common dates after those fixed requirements as one OOS block rather than
    silently reducing the purge or training history. The resulting OOS block may be
    shorter than the canonical 60 sessions and is reported explicitly.
    """
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

    daily_date_map = {
        pd.Timestamp(d).normalize(): i for i, d in enumerate(pd.to_datetime(daily_windows.dates))
    }
    intra_date_map = {
        pd.Timestamp(d).normalize(): i for i, d in enumerate(pd.to_datetime(intraday_dates))
    }
    common_dates = np.asarray(
        sorted(set(daily_date_map).intersection(intra_date_map)), dtype="datetime64[ns]"
    )

    required_before_test = SLIDING_TRAIN + PURGE
    oos_size = len(common_dates) - required_before_test
    if oos_size < 20:
        raise RuntimeError(
            f"insufficient common Daily/Intraday dates for a useful limited-history OOS block: "
            f"common={len(common_dates)} train={SLIDING_TRAIN} purge={PURGE} oos={oos_size}"
        )

    daily_idx = np.asarray(
        [daily_date_map[pd.Timestamp(d).normalize()] for d in common_dates], dtype=int
    )
    intra_idx = np.asarray(
        [intra_date_map[pd.Timestamp(d).normalize()] for d in common_dates], dtype=int
    )
    daily_x = daily_windows.x[daily_idx].cpu()
    daily_y = daily_windows.y[daily_idx].cpu()
    intra_x = intraday_x[intra_idx].cpu()
    intra_y = intraday_y[intra_idx].cpu()
    if not torch.equal(daily_y, intra_y):
        raise RuntimeError("Daily and intraday experiments are not target-aligned")

    train_idx = np.arange(0, SLIDING_TRAIN, dtype=int)
    test_start = SLIDING_TRAIN + PURGE
    test_idx = np.arange(test_start, len(common_dates), dtype=int)

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

    print(
        f"S1 FREQUENCY_COMPARE_LIMITED DATA common_windows={len(common_dates)} folds=1 "
        f"first={pd.Timestamp(common_dates[0]).date()} last={pd.Timestamp(common_dates[-1]).date()} "
        f"horizon={TARGET_HORIZON} train=SLIDING_{SLIDING_TRAIN} epochs={EPOCHS} "
        f"purge={PURGE} test_size={len(test_idx)} canonical_test_size=60 limited_history=true"
    )
    print(
        f"S1 FREQUENCY_COMPARE_LIMITED FOLD id=1 "
        f"train_first={pd.Timestamp(common_dates[train_idx[0]]).date()} "
        f"train_last={pd.Timestamp(common_dates[train_idx[-1]]).date()} "
        f"test_first={pd.Timestamp(common_dates[test_idx[0]]).date()} "
        f"test_last={pd.Timestamp(common_dates[test_idx[-1]]).date()} "
        f"purge={test_idx[0] - train_idx[-1] - 1}"
    )
    print(
        f"S1 FREQUENCY_COMPARE_LIMITED INPUT daily_bars={DAILY_LOOKBACK} "
        f"intraday_bars={INTRADAY_LOOKBACK} sessions={DAILY_LOOKBACK} "
        f"intraday_per_session=2 intraday_volume_window={INTRADAY_VOLUME_WINDOW}"
    )

    y_test = daily_y[test_idx, TARGET_INDEX].numpy().astype(float)
    results: dict[str, list[dict[str, float]]] = {name: [] for name in model_factories}

    for model_name, factory in model_factories.items():
        print(
            f"S1 FREQUENCY_COMPARE_LIMITED MODEL name={model_name} "
            f"params={count_parameters(factory())}"
        )
        x_all = x_by_model[model_name]
        for seed in SEEDS:
            pred = _fit_model(
                factory(), x_all[train_idx], daily_y[train_idx], x_all[test_idx], seed
            )
            m = _metrics(y_test, pred)
            results[model_name].append(m)
            print(
                f"S1 FREQUENCY_COMPARE_LIMITED FOLD_METRIC id=1 model={model_name} seed={seed} "
                f"spearman={_fmt(m['spearman'])} mae={m['mae']:.6f} "
                f"top20_lift={_fmt(m['lift'])} top_bottom={_fmt(m['top_bottom'])}"
            )

    for model_name in model_factories:
        for key in ("spearman", "lift", "mae"):
            values = [row[key] for row in results[model_name]]
            mean, std = _mean_std(values)
            positive = sum(v > 0 for v in values if np.isfinite(v))
            label = "top20_lift" if key == "lift" else key
            print(
                f"S1 FREQUENCY_COMPARE_LIMITED CROSS_SEED model={model_name} metric={label} "
                f"mean={_fmt(mean)} std={_fmt(std)} positive={positive}/{len(SEEDS)}"
            )

    print("S1 FREQUENCY_COMPARE_LIMITED PASS")


if __name__ == "__main__":
    main()

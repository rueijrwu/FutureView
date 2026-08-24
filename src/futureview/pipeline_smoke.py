from __future__ import annotations

import torch

from .data import download_spy_daily, validate_daily_ohlcv
from .datasets import build_windows
from .features import make_causal_features
from .labels import HORIZONS, make_forward_labels
from .walkforward import purged_three_way_split


def main() -> None:
    df = download_spy_daily(period="3y")
    validate_daily_ohlcv(df)

    features = make_causal_features(df)
    labels = make_forward_labels(df)
    windowed = build_windows(features, labels, lookback=50, horizons=HORIZONS)

    expected_channels = 5
    expected_lookback = 50
    expected_targets = len(HORIZONS)
    if tuple(windowed.x.shape[1:]) != (expected_channels, expected_lookback):
        raise AssertionError(f"unexpected x shape: {tuple(windowed.x.shape)}")
    if windowed.y.shape[1] != expected_targets:
        raise AssertionError(f"unexpected y shape: {tuple(windowed.y.shape)}")
    if not torch.isfinite(windowed.x).all():
        raise AssertionError("non-finite values in x")
    if not torch.isfinite(windowed.y).all():
        raise AssertionError("non-finite values in y")

    split = purged_three_way_split(len(windowed.dates), purge=max(HORIZONS))
    train_last = windowed.dates[split.train[-1]]
    val_first = windowed.dates[split.validation[0]]
    val_last = windowed.dates[split.validation[-1]]
    test_first = windowed.dates[split.test[0]]

    if not (train_last < val_first < val_last < test_first):
        raise AssertionError("chronological split ordering failed")

    print(
        "PIPELINE SMOKE PASS "
        f"rows={len(df)} features={len(features)} windows={len(windowed.dates)} "
        f"x={tuple(windowed.x.shape)} y={tuple(windowed.y.shape)} "
        f"train={len(split.train)} val={len(split.validation)} test={len(split.test)} "
        f"purge={max(HORIZONS)}"
    )


if __name__ == "__main__":
    main()

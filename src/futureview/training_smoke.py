from __future__ import annotations

import numpy as np
import torch
from torch import nn

from .data import download_spy_daily, validate_daily_ohlcv
from .datasets import build_windows
from .features import make_causal_features
from .labels import HORIZONS, add_success_labels, make_forward_labels
from .models import TrendCNNDual, TrendCNNJoint
from .walkforward import purged_three_way_split


def _train_one(model: nn.Module, x: torch.Tensor, y: torch.Tensor, epochs: int = 3) -> float:
    model.train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    loss_fn = nn.SmoothL1Loss()
    loss_value = float("nan")
    for _ in range(epochs):
        optimizer.zero_grad(set_to_none=True)
        pred = model(x)
        loss = loss_fn(pred, y)
        if not torch.isfinite(loss):
            raise AssertionError("non-finite training loss")
        loss.backward()
        optimizer.step()
        loss_value = float(loss.detach())
    return loss_value


def _eval_loss(model: nn.Module, x: torch.Tensor, y: torch.Tensor) -> float:
    model.eval()
    with torch.no_grad():
        pred = model(x)
        if not torch.isfinite(pred).all():
            raise AssertionError("non-finite model predictions")
        return float(nn.functional.smooth_l1_loss(pred, y))


def main() -> None:
    torch.manual_seed(7)
    torch.set_num_threads(2)

    df = download_spy_daily(period="3y")
    validate_daily_ohlcv(df)
    features = make_causal_features(df)
    labels = make_forward_labels(df)
    loose = add_success_labels(labels, "loose")
    strict = add_success_labels(labels, "strict")
    windowed = build_windows(features, labels, lookback=50, horizons=HORIZONS)
    split = purged_three_way_split(len(windowed.dates), purge=max(HORIZONS))

    # Baseline success rate is measured on the same eligible dates used by windows.
    date_index_loose = loose.set_index("date")
    date_index_strict = strict.set_index("date")
    print("BASELINE SUCCESS RATES")
    for h in HORIZONS:
        loose_rates = date_index_loose.loc[windowed.dates, f"success_loose_{h}"].to_numpy(dtype=float)
        strict_rates = date_index_strict.loc[windowed.dates, f"success_strict_{h}"].to_numpy(dtype=float)
        print(
            f"{h:>2}D loose={loose_rates.mean():.3f} strict={strict_rates.mean():.3f} "
            f"n={len(loose_rates)}"
        )

    x_train, y_train = windowed.x[split.train], windowed.y[split.train]
    x_val, y_val = windowed.x[split.validation], windowed.y[split.validation]
    x_test, y_test = windowed.x[split.test], windowed.y[split.test]

    if min(len(x_train), len(x_val), len(x_test)) == 0:
        raise AssertionError("empty train/validation/test split")

    for name, model in (
        ("A", TrendCNNJoint()),
        ("B", TrendCNNDual()),
    ):
        train_loss = _train_one(model, x_train, y_train, epochs=3)
        val_loss = _eval_loss(model, x_val, y_val)
        test_loss = _eval_loss(model, x_test, y_test)
        print(
            f"MODEL {name} train_loss={train_loss:.6f} "
            f"val_loss={val_loss:.6f} test_loss={test_loss:.6f}"
        )

    print(
        "TRAINING SMOKE PASS "
        f"train={len(x_train)} val={len(x_val)} test={len(x_test)} purge={max(HORIZONS)}"
    )


if __name__ == "__main__":
    main()

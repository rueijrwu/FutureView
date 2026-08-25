from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SplitIndices:
    train: np.ndarray
    validation: np.ndarray
    test: np.ndarray


@dataclass(frozen=True)
class WalkForwardFold:
    train: np.ndarray
    test: np.ndarray


def purged_three_way_split(
    n_samples: int,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    purge: int = 60,
) -> SplitIndices:
    """Simple chronological split with purge gaps for smoke validation."""
    if n_samples <= 0:
        raise ValueError("n_samples must be positive")
    if not (0.0 < train_fraction < 1.0 and 0.0 < validation_fraction < 1.0):
        raise ValueError("fractions must be between 0 and 1")
    if train_fraction + validation_fraction >= 1.0:
        raise ValueError("train + validation fractions must leave room for test")

    train_end = int(n_samples * train_fraction)
    validation_start = train_end + purge
    validation_end = int(n_samples * (train_fraction + validation_fraction))
    test_start = validation_end + purge

    train = np.arange(0, train_end, dtype=int)
    validation = np.arange(validation_start, validation_end, dtype=int)
    test = np.arange(test_start, n_samples, dtype=int)

    if min(len(train), len(validation), len(test)) == 0:
        raise ValueError(
            f"split too small after purge: train={len(train)} validation={len(validation)} test={len(test)}"
        )
    return SplitIndices(train=train, validation=validation, test=test)


def purged_expanding_walk_forward(
    n_samples: int,
    min_train: int = 260,
    test_size: int = 60,
    purge: int = 60,
    step: int = 60,
) -> tuple[WalkForwardFold, ...]:
    """Create expanding chronological OOS folds separated by a purge gap.

    For each fold, training uses indices [0, train_end), then `purge` samples are
    excluded before the test block. Later folds expand the training history.
    Test blocks never precede their training data and use no future observations.
    """
    if n_samples <= 0:
        raise ValueError("n_samples must be positive")
    if min_train <= 0 or test_size <= 0 or step <= 0 or purge < 0:
        raise ValueError("invalid walk-forward sizes")

    folds: list[WalkForwardFold] = []
    test_start = min_train + purge
    while test_start < n_samples:
        test_end = min(test_start + test_size, n_samples)
        train_end = test_start - purge
        if train_end < min_train:
            raise RuntimeError("walk-forward train set shorter than min_train")
        train = np.arange(0, train_end, dtype=int)
        test = np.arange(test_start, test_end, dtype=int)
        if len(test) == 0:
            break
        folds.append(WalkForwardFold(train=train, test=test))
        test_start += step

    if not folds:
        raise ValueError(
            f"no walk-forward folds: n={n_samples} min_train={min_train} purge={purge} test={test_size}"
        )

    return tuple(folds)

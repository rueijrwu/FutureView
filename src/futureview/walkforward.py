from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SplitIndices:
    train: np.ndarray
    validation: np.ndarray
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

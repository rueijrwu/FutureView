from __future__ import annotations

import numpy as np
import pandas as pd

from futureview.strategy1_layer2_8y_rolling5y_validation import rolling_train_mask


def test_rolling_mask_respects_five_year_window_and_label_availability() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime([
        "2019-01-02",
        "2020-01-02",
        "2021-01-04",
        "2022-01-03",
        "2023-01-03",
        "2024-01-03",
        "2025-01-03",
    ]))
    available = np.array([100, 200, 300, 400, 500, 600, 700])
    mask = rolling_train_mask(
        dates,
        available,
        current_target_index=650,
        current_date=pd.Timestamp("2025-01-03"),
        train_years=5,
    )
    # 2020-01-03 is the lower bound, so 2020-01-02 is too old.
    # 2024-01-03 is eligible and available before current target.
    assert mask.tolist() == [False, False, True, True, True, True, False]


def test_rolling_mask_rejects_label_not_yet_available() -> None:
    dates = pd.DatetimeIndex(pd.to_datetime(["2023-01-03", "2024-01-03"]))
    available = np.array([650, 590])
    mask = rolling_train_mask(
        dates,
        available,
        current_target_index=600,
        current_date=pd.Timestamp("2025-01-03"),
        train_years=5,
    )
    assert mask.tolist() == [False, True]

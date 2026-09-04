from __future__ import annotations

import pandas as pd

from futureview.strategy1_layer2_price_distribution_chrono import assign_fold_buckets


def test_assign_fold_buckets_orders_extremes() -> None:
    frame = pd.DataFrame({"score": list(range(10))})
    bucket = assign_fold_buckets(frame, "score")
    assert bucket.iloc[0] == "bottom20"
    assert bucket.iloc[-1] == "top20"
    assert set(bucket.unique()) == {"bottom20", "middle60", "top20"}


def test_assign_fold_buckets_preserves_index() -> None:
    frame = pd.DataFrame({"score": [0.1, 0.2, 0.3, 0.4, 0.5]}, index=[10, 20, 30, 40, 50])
    bucket = assign_fold_buckets(frame, "score")
    assert bucket.index.tolist() == frame.index.tolist()

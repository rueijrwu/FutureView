from __future__ import annotations

import numpy as np
import pandas as pd

from futureview.strategy1_layer2_10y_holdout import _stats


def test_holdout_date_rule_has_gap_for_boundary_windows() -> None:
    cutoff = pd.Timestamp("2025-08-28")
    starts = pd.to_datetime(["2025-07-01", "2025-08-10", "2025-08-28", "2025-09-01"])
    ends = pd.to_datetime(["2025-08-01", "2025-09-20", "2025-10-10", "2025-10-15"])
    train = ends < cutoff
    test = starts >= cutoff
    boundary = ~(train | test)
    assert train.tolist() == [True, False, False, False]
    assert test.tolist() == [False, False, True, True]
    assert boundary.tolist() == [False, True, False, False]


def test_stats_accepts_small_nonconstant_arrays(capsys) -> None:
    actual = np.array([0.0, 1.0, 2.0])
    pred = np.array([0.1, 0.9, 2.2])
    _stats("TEST metric=C", actual, pred)
    out = capsys.readouterr().out
    assert "mae=" in out
    assert "pearson=" in out
    assert "spearman=" in out

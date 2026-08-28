import numpy as np
import pandas as pd
import pytest

from futureview.strategy1_layer2_weight_handoff import (
    build_handoff_table,
    state_weight,
    weighted_mean_loss,
)


def test_state_weight_mapping():
    assert state_weight("high", 0.2) == 1.0
    assert state_weight("neutral", 0.2) == 0.2
    assert state_weight("low", 0.2) == 1.0


def test_handoff_uses_strictly_prior_90_sessions():
    classified = pd.DataFrame(
        [
            {"start_index": 100, "end_index": 129, "state": "high", "past_C": 0.1, "past_Q": 0.0},
            {"start_index": 150, "end_index": 179, "state": "neutral", "past_C": 0.0, "past_Q": 0.1},
        ]
    )
    out = build_handoff_table(classified, n_market_rows=300, model_history=90, neutral_alpha=0.2)
    assert list(out.input_start) == [10, 60]
    assert list(out.input_end) == [99, 149]
    assert (out.input_end == out.layer1_start - 1).all()
    assert (out.input_length == 90).all()
    assert list(out.sample_weight) == [1.0, 0.2]


def test_handoff_drops_rows_without_full_prior_history():
    classified = pd.DataFrame(
        [
            {"start_index": 50, "end_index": 79, "state": "low", "past_C": -0.1, "past_Q": 0.2},
            {"start_index": 90, "end_index": 119, "state": "low", "past_C": -0.2, "past_Q": 0.3},
        ]
    )
    out = build_handoff_table(classified, n_market_rows=200, model_history=90, neutral_alpha=0.2)
    assert len(out) == 1
    assert int(out.iloc[0].input_start) == 0
    assert int(out.iloc[0].input_end) == 89


def test_weighted_mean_loss_matches_manual_reduction():
    losses = np.array([2.0, 10.0, 4.0])
    weights = np.array([1.0, 0.2, 1.0])
    expected = (2.0 * 1.0 + 10.0 * 0.2 + 4.0 * 1.0) / 2.2
    assert weighted_mean_loss(losses, weights) == pytest.approx(expected)


def test_weighted_mean_loss_preserves_constant_loss_scale():
    losses = np.array([3.5, 3.5, 3.5])
    weights = np.array([1.0, 0.2, 1.0])
    assert weighted_mean_loss(losses, weights) == pytest.approx(3.5)

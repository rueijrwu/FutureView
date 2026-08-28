from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from futureview.strategy1_layer2_forward_smoke import (
    MODEL_HISTORY,
    ForwardCQStateNet,
    make_input_features,
    nonnegative_q,
    state_weight,
    weighted_mean,
)


def _df(n: int = 120) -> pd.DataFrame:
    return pd.DataFrame({
        "close": np.linspace(100.0, 130.0, n),
        "volume": np.linspace(1_000_000.0, 1_500_000.0, n),
    })


def test_state_weights() -> None:
    assert state_weight("high") == 1.0
    assert state_weight("neutral") == 0.2
    assert state_weight("low") == 1.0


def test_input_features_shape_and_finite() -> None:
    x = make_input_features(_df(), 10, 10 + MODEL_HISTORY - 1)
    assert x.shape == (2, MODEL_HISTORY)
    assert np.isfinite(x).all()
    assert abs(float(x[0, -1])) < 1e-7


def test_network_output_shapes_and_probability_sum() -> None:
    torch.manual_seed(1)
    model = ForwardCQStateNet()
    x = torch.zeros(4, 2, MODEL_HISTORY)
    cq, logits = model(x)
    p = torch.softmax(logits, dim=1)
    assert cq.shape == (4, 2)
    assert logits.shape == (4, 3)
    assert torch.allclose(p.sum(dim=1), torch.ones(4), atol=1e-6)


def test_q_transform_is_nonnegative_and_allows_exact_zero() -> None:
    raw = torch.tensor([[-2.0], [0.0], [3.0]])
    q = nonnegative_q(raw)
    assert torch.all(q >= 0)
    assert float(q[1, 0]) == 0.0


def test_weighted_mean_matches_manual() -> None:
    loss = torch.tensor([1.0, 2.0, 4.0])
    weight = torch.tensor([1.0, 0.2, 1.0])
    got = weighted_mean(loss, weight)
    expected = (1.0 + 0.4 + 4.0) / 2.2
    assert abs(float(got) - expected) < 1e-6

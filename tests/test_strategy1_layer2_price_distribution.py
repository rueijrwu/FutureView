import numpy as np
import pandas as pd
import torch

from futureview.strategy1_layer2_price_distribution import (
    MODEL_HISTORY,
    PriceDistributionNet,
    build_selected_samples,
    pinball_loss,
)


def _df(n: int = 140) -> pd.DataFrame:
    close = 100.0 * np.exp(np.arange(n, dtype=float) * 0.001)
    volume = 1_000_000.0 + np.arange(n, dtype=float) * 1000.0
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n, freq="B"),
        "close": close,
        "volume": volume,
    })


def test_selected_samples_exclude_neutral_and_use_future_three_close() -> None:
    df = _df()
    classified = pd.DataFrame([
        {"start_index": 61, "end_index": 90, "state": "high", "past_C": 0.1, "past_Q": 0.01, "past_entries": 2},
        {"start_index": 62, "end_index": 91, "state": "neutral", "past_C": 0.0, "past_Q": 0.02, "past_entries": 2},
        {"start_index": 63, "end_index": 92, "state": "low", "past_C": -0.1, "past_Q": 0.03, "past_entries": 2},
    ])
    data = build_selected_samples(df, classified)
    assert data.x.shape == (2, 2, MODEL_HISTORY)
    assert data.rows.state.tolist() == ["high", "low"]
    expected0 = np.log(df.at[93, "close"] / df.at[90, "close"])
    expected1 = np.log(df.at[95, "close"] / df.at[92, "close"])
    np.testing.assert_allclose(data.y.numpy(), [expected0, expected1], rtol=0, atol=1e-7)


def test_network_quantiles_are_ordered() -> None:
    torch.manual_seed(1)
    model = PriceDistributionNet()
    x = torch.randn(8, 2, MODEL_HISTORY)
    q, logit = model(x)
    assert q.shape == (8, 3)
    assert logit.shape == (8,)
    assert torch.all(q[:, 0] <= q[:, 1])
    assert torch.all(q[:, 1] <= q[:, 2])


def test_pinball_loss_is_finite_and_nonnegative() -> None:
    pred = torch.tensor([[-0.1, 0.0, 0.1], [-0.2, 0.1, 0.3]], dtype=torch.float32)
    target = torch.tensor([0.02, -0.03], dtype=torch.float32)
    loss = pinball_loss(pred, target)
    assert torch.isfinite(loss)
    assert float(loss) >= 0.0

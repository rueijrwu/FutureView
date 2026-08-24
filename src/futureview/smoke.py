from __future__ import annotations

import torch
from torch import nn

from futureview.models import HORIZONS, TrendCNNDual, TrendCNNJoint, count_parameters


def run_model(name: str, model: nn.Module, x: torch.Tensor, y: torch.Tensor) -> None:
    model.train()
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    loss_fn = nn.HuberLoss()

    optimizer.zero_grad(set_to_none=True)
    pred = model(x)
    assert pred.shape == y.shape, (pred.shape, y.shape)
    assert torch.isfinite(pred).all(), f"{name}: non-finite prediction"

    loss = loss_fn(pred, y)
    assert torch.isfinite(loss), f"{name}: non-finite loss"
    loss.backward()

    grad_ok = any(
        p.grad is not None and torch.isfinite(p.grad).all()
        for p in model.parameters()
        if p.requires_grad
    )
    assert grad_ok, f"{name}: no finite gradients"
    optimizer.step()

    print(
        f"{name}: params={count_parameters(model):,} "
        f"input={tuple(x.shape)} output={tuple(pred.shape)} loss={loss.item():.6f}"
    )


def main() -> None:
    torch.manual_seed(7)
    torch.set_num_threads(1)
    device = torch.device("cpu")

    batch_size = 16
    lookback = 50
    x = torch.randn(batch_size, 5, lookback, device=device)
    y = torch.empty(batch_size, len(HORIZONS), device=device).uniform_(-1.0, 1.0)

    print(f"torch={torch.__version__}")
    print(f"device={device}")
    print(f"horizons={HORIZONS}")

    run_model("Model A / joint OHLCV", TrendCNNJoint().to(device), x, y)
    run_model("Model B / price-volume dual", TrendCNNDual().to(device), x, y)
    print("SMOKE PASS")


if __name__ == "__main__":
    main()

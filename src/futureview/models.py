from __future__ import annotations

import torch
from torch import nn

HORIZONS = (15, 30, 45, 60)


class MultiScaleBlock(nn.Module):
    def __init__(self, in_channels: int, branch_channels: int = 8) -> None:
        super().__init__()
        self.branches = nn.ModuleList(
            [
                nn.Sequential(
                    nn.Conv1d(in_channels, branch_channels, kernel_size=k, padding="same"),
                    nn.GELU(),
                )
                for k in (5, 10, 20)
            ]
        )

    @property
    def out_channels(self) -> int:
        return len(self.branches) * self.branches[0][0].out_channels

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.cat([branch(x) for branch in self.branches], dim=1)


class TrendCNNJoint(nn.Module):
    """Model A: joint OHLCV multi-scale CNN.

    Input shape: [batch, 5, 50]
    Output shape: [batch, 4] for horizons 15/30/45/60.
    """

    def __init__(self) -> None:
        super().__init__()
        self.multi = MultiScaleBlock(5, branch_channels=8)
        self.fusion = nn.Sequential(
            nn.Conv1d(self.multi.out_channels, 16, kernel_size=3, padding="same"),
            nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(16, 8),
            nn.GELU(),
            nn.Linear(8, len(HORIZONS)),
            nn.Tanh(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 3 or x.shape[1] != 5:
            raise ValueError(f"expected [batch, 5, time], got {tuple(x.shape)}")
        return self.head(self.fusion(self.multi(x)))


class TrendCNNDual(nn.Module):
    """Model B: separate price and volume branches, then fusion.

    Input shape: [batch, 5, 50], channels ordered O/H/L/C/V.
    Output shape: [batch, 4] for horizons 15/30/45/60.
    """

    def __init__(self) -> None:
        super().__init__()
        self.price_multi = MultiScaleBlock(4, branch_channels=8)
        self.volume_multi = MultiScaleBlock(1, branch_channels=4)
        fusion_channels = self.price_multi.out_channels + self.volume_multi.out_channels
        self.fusion = nn.Sequential(
            nn.Conv1d(fusion_channels, 20, kernel_size=3, padding="same"),
            nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(20, 10),
            nn.GELU(),
            nn.Linear(10, len(HORIZONS)),
            nn.Tanh(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 3 or x.shape[1] != 5:
            raise ValueError(f"expected [batch, 5, time], got {tuple(x.shape)}")
        price = x[:, :4, :]
        volume = x[:, 4:5, :]
        features = torch.cat(
            [self.price_multi(price), self.volume_multi(volume)], dim=1
        )
        return self.head(self.fusion(features))


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)

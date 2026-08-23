from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class ScreenerConfig(BaseModel):
    top_n: int = Field(default=50, ge=1)
    min_price: float = Field(default=10.0, gt=0)
    min_avg_dollar_volume_20d: float = Field(default=50_000_000, ge=0)
    max_extension_atr: float = Field(default=3.0, gt=0)
    require_close_above_sma50: bool = True
    require_sma50_above_sma200: bool = True
    require_positive_sma50_slope: bool = True
    require_positive_rs20: bool = True
    require_positive_rs60: bool = True


class RankingConfig(BaseModel):
    rs20_weight: float = 0.30
    rs60_weight: float = 0.25
    trend_weight: float = 0.20
    breakout_weight: float = 0.15
    volume_weight: float = 0.10

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "RankingConfig":
        total = (
            self.rs20_weight
            + self.rs60_weight
            + self.trend_weight
            + self.breakout_weight
            + self.volume_weight
        )
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"ranking weights must sum to 1.0, got {total:.6f}")
        return self


class PortfolioConfig(BaseModel):
    tactical_max_fraction: float = Field(default=2 / 3, gt=0, le=1)
    emergency_reserve_min_fraction: float = Field(default=0.10, ge=0, le=1)
    emergency_reserve_max_fraction: float = Field(default=0.30, ge=0, le=1)
    top_leader_option_count: int = Field(default=3, ge=0)

    @model_validator(mode="after")
    def reserve_bounds_are_valid(self) -> "PortfolioConfig":
        if self.emergency_reserve_min_fraction > self.emergency_reserve_max_fraction:
            raise ValueError("emergency reserve minimum cannot exceed maximum")
        return self


class ExitConfig(BaseModel):
    moving_average_levels: list[int] = Field(default_factory=lambda: [5, 10])
    new_high_partial_profit: bool = True


class StrategyConfig(BaseModel):
    benchmark: str = "SPY"
    screener: ScreenerConfig = Field(default_factory=ScreenerConfig)
    ranking: RankingConfig = Field(default_factory=RankingConfig)
    portfolio: PortfolioConfig = Field(default_factory=PortfolioConfig)
    exits: ExitConfig = Field(default_factory=ExitConfig)


def load_strategy_config(path: str | Path) -> StrategyConfig:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return StrategyConfig.model_validate(raw)

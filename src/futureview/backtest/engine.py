from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


class Strategy(Protocol):
    def on_day(self, trading_date: date, state: PortfolioState) -> None: ...


@dataclass
class PortfolioState:
    cash: float
    core_reserve: float
    tactical_capital: float
    emergency_reserve: float

    @property
    def equity(self) -> float:
        return self.cash + self.core_reserve + self.tactical_capital + self.emergency_reserve


class BacktestEngine:
    """Daily event loop; execution and pricing models will plug into this layer."""

    def __init__(self, strategy: Strategy, state: PortfolioState) -> None:
        self.strategy = strategy
        self.state = state

    def run(self, trading_dates: list[date]) -> PortfolioState:
        for trading_date in trading_dates:
            self.strategy.on_day(trading_date, self.state)
        return self.state

from __future__ import annotations

from datetime import date

import polars as pl

from futureview.config import RankingConfig, ScreenerConfig, StrategyConfig
from futureview.screener.pipeline import build_ranking_history


def test_eligible_symbols_are_applied_before_ranking() -> None:
    dates = pl.date_range(date(2025, 1, 1), date(2025, 8, 31), interval="1d", eager=True)
    prices = pl.concat(
        [
            pl.DataFrame(
                {
                    "symbol": [symbol] * len(dates),
                    "date": dates,
                    "open": [price] * len(dates),
                    "high": [price * 1.01] * len(dates),
                    "low": [price * 0.99] * len(dates),
                    "close": [price] * len(dates),
                    "volume": [10_000_000.0] * len(dates),
                }
            )
            for symbol, price in (("SPY", 500.0), ("AAA", 100.0), ("ETF1", 100.0))
        ],
        how="vertical",
    )
    config = StrategyConfig(
        benchmark="SPY",
        screener=ScreenerConfig(
            top_n=50,
            min_price=10.0,
            min_avg_dollar_volume_20d=1.0,
            max_extension_atr=100.0,
            require_close_above_sma50=False,
            require_sma50_above_sma200=False,
            require_positive_sma50_slope=False,
            require_positive_rs20=False,
            require_positive_rs60=False,
        ),
        ranking=RankingConfig(),
    )

    ranking = build_ranking_history(prices, config, eligible_symbols={"AAA"})

    assert set(ranking.get_column("symbol").unique()) == {"AAA"}

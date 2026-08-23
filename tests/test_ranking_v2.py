from datetime import date

import polars as pl

from futureview.config import RankingConfig
from futureview.screener.ranking import rank_cross_sections


def _row(symbol: str, trading_date: date, extension_atr: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "date": trading_date,
        "close": 100.0,
        "sma20": 95.0,
        "sma50": 90.0,
        "sma200": 80.0,
        "sma50_slope10": 0.05,
        "distance_from_high20": 0.0,
        "breakout20": True,
        "rs20": 0.30,
        "rs60": 0.50,
        "volume_ratio20": 1.20,
        "extension_atr": extension_atr,
    }


def test_extension_penalty_reduces_score_for_equally_strong_stock() -> None:
    frame = pl.DataFrame(
        [
            _row("LOWEXT", date(2026, 8, 20), 1.0),
            _row("HIGHEXT", date(2026, 8, 20), 2.9),
            _row("LOWEXT", date(2026, 8, 21), 1.0),
            _row("HIGHEXT", date(2026, 8, 21), 2.9),
        ]
    )
    config = RankingConfig(persistence_lookback=2)

    ranked = rank_cross_sections(frame, config)
    latest = ranked.filter(pl.col("date") == date(2026, 8, 21))
    scores = {row["symbol"]: row for row in latest.to_dicts()}

    assert scores["LOWEXT"]["extension_penalty"] == 0.0
    assert scores["HIGHEXT"]["extension_penalty"] > 0.0
    assert scores["LOWEXT"]["stock_score"] > scores["HIGHEXT"]["stock_score"]

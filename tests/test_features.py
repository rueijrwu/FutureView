from datetime import date, timedelta

import polars as pl

from futureview.features.core import add_core_features, add_relative_strength


def _prices() -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    start = date(2025, 10, 1)
    for i in range(230):
        trading_date = start + timedelta(days=i)
        for symbol, slope in (("SPY", 0.20), ("AAA", 0.55)):
            close = 100.0 + slope * i
            rows.append(
                {
                    "symbol": symbol,
                    "date": trading_date,
                    "open": close - 0.5,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close,
                    "volume": 1_000_000,
                }
            )
    return pl.DataFrame(rows)


def test_relative_strength_uses_same_date_benchmark() -> None:
    features = add_relative_strength(add_core_features(_prices()), "SPY")
    latest = features.filter(pl.col("date") == features.get_column("date").max())
    aaa = latest.filter(pl.col("symbol") == "AAA").row(0, named=True)
    assert aaa["rs20"] > 0
    assert aaa["rs60"] > 0


def test_breakout_level_excludes_current_bar() -> None:
    prices = _prices()
    last_date = prices.get_column("date").max()
    prices = prices.with_columns(
        pl.when((pl.col("symbol") == "AAA") & (pl.col("date") == last_date))
        .then(pl.lit(500.0))
        .otherwise(pl.col("close"))
        .alias("close"),
        pl.when((pl.col("symbol") == "AAA") & (pl.col("date") == last_date))
        .then(pl.lit(501.0))
        .otherwise(pl.col("high"))
        .alias("high"),
    )
    features = add_core_features(prices)
    aaa = features.filter(
        (pl.col("symbol") == "AAA") & (pl.col("date") == last_date)
    ).row(0, named=True)
    assert aaa["breakout20"] is True
    assert aaa["high20_prior"] < aaa["close"]

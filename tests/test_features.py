from datetime import date, timedelta

import polars as pl
import pytest

from futureview.features.core import add_core_features, add_relative_strength
from futureview.features.incremental import (
    STATE_SHARDS,
    bootstrap_states,
    bootstrap_symbol_state,
    state_shard,
    update_symbol_state,
)


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
                    "volume": 1_000_000 + i * 1_000,
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


def test_incremental_core_features_match_batch_engine() -> None:
    prices = _prices().filter(pl.col("symbol") == "AAA").sort("date")
    history = prices.head(229)
    next_bar = prices.tail(1).row(0, named=True)

    state = bootstrap_symbol_state(history, "AAA")
    _, incremental = update_symbol_state(
        state,
        trading_date=next_bar["date"],
        open_=next_bar["open"],
        high=next_bar["high"],
        low=next_bar["low"],
        close=next_bar["close"],
        volume=next_bar["volume"],
    )

    batch = add_core_features(prices).tail(1).row(0, named=True)
    numeric_columns = (
        "sma5",
        "sma10",
        "sma20",
        "sma50",
        "sma200",
        "avg_volume20",
        "return20",
        "return60",
        "high20_prior",
        "high50_prior",
        "true_range",
        "atr14",
        "avg_dollar_volume20",
        "volume_ratio20",
        "sma50_slope10",
        "extension_atr",
        "distance_from_high20",
    )
    for column in numeric_columns:
        assert incremental[column] == pytest.approx(batch[column], rel=1e-12, abs=1e-12)

    assert incremental["breakout20"] is batch["breakout20"]
    assert incremental["breakout50"] is batch["breakout50"]


def test_incremental_state_round_trip() -> None:
    prices = _prices().filter(pl.col("symbol") == "AAA").sort("date")
    state = bootstrap_symbol_state(prices.head(229), "AAA")
    restored = type(state).from_dict(state.to_dict())
    assert restored == state


def test_bootstrap_states_and_shards_are_deterministic() -> None:
    states = bootstrap_states(_prices())
    assert set(states) == {"AAA", "SPY"}
    assert 0 <= state_shard("AAA") < STATE_SHARDS
    assert state_shard("AAA") == state_shard("AAA")
    assert states["AAA"].as_of == _prices().get_column("date").max()

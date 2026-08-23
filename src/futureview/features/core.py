from __future__ import annotations

import polars as pl

REQUIRED_PRICE_COLUMNS = {"symbol", "date", "open", "high", "low", "close", "volume"}


def _validate_price_frame(frame: pl.DataFrame) -> None:
    missing = REQUIRED_PRICE_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"price frame is missing required columns: {sorted(missing)}")


def add_core_features(frame: pl.DataFrame) -> pl.DataFrame:
    """Compute point-in-time daily features for every symbol.

    The input is expected to contain split-adjusted OHLCV data. Rolling features
    use only the current and prior observations. Breakout levels deliberately
    exclude the current bar so a close can be tested against information that
    was already known before that close.
    """
    _validate_price_frame(frame)

    by = "symbol"
    ordered = frame.sort(["symbol", "date"])
    close = pl.col("close")
    prev_close = close.shift(1).over(by)
    true_range = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )

    out = ordered.with_columns(
        close.rolling_mean(5).over(by).alias("sma5"),
        close.rolling_mean(10).over(by).alias("sma10"),
        close.rolling_mean(20).over(by).alias("sma20"),
        close.rolling_mean(50).over(by).alias("sma50"),
        close.rolling_mean(200).over(by).alias("sma200"),
        pl.col("volume").rolling_mean(20).over(by).alias("avg_volume20"),
        close.pct_change(20).over(by).alias("return20"),
        close.pct_change(60).over(by).alias("return60"),
        pl.col("high").rolling_max(20).shift(1).over(by).alias("high20_prior"),
        pl.col("high").rolling_max(50).shift(1).over(by).alias("high50_prior"),
        true_range.alias("true_range"),
    )

    out = out.with_columns(
        pl.col("true_range").rolling_mean(14).over(by).alias("atr14"),
        (pl.col("close") * pl.col("avg_volume20")).alias("avg_dollar_volume20"),
        (pl.col("volume") / pl.col("avg_volume20")).alias("volume_ratio20"),
        (pl.col("sma50") / pl.col("sma50").shift(10).over(by) - 1.0).alias(
            "sma50_slope10"
        ),
    )

    return out.with_columns(
        ((pl.col("close") - pl.col("sma20")) / pl.col("atr14")).alias("extension_atr"),
        (pl.col("close") >= pl.col("high20_prior")).alias("breakout20"),
        (pl.col("close") >= pl.col("high50_prior")).alias("breakout50"),
        (pl.col("close") / pl.col("high20_prior") - 1.0).alias("distance_from_high20"),
    )


def add_relative_strength(frame: pl.DataFrame, benchmark_symbol: str = "SPY") -> pl.DataFrame:
    """Add 20- and 60-session excess returns versus a benchmark.

    This must be called after :func:`add_core_features`. The benchmark row is
    joined by date, preventing any use of future benchmark observations.
    """
    required = {"symbol", "date", "return20", "return60"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"feature frame is missing required columns: {sorted(missing)}")

    benchmark = (
        frame.filter(pl.col("symbol") == benchmark_symbol)
        .select(
            "date",
            pl.col("return20").alias("benchmark_return20"),
            pl.col("return60").alias("benchmark_return60"),
        )
        .unique(subset=["date"])
    )
    if benchmark.is_empty():
        raise ValueError(f"benchmark symbol {benchmark_symbol!r} is not present")

    return frame.join(benchmark, on="date", how="left").with_columns(
        (pl.col("return20") - pl.col("benchmark_return20")).alias("rs20"),
        (pl.col("return60") - pl.col("benchmark_return60")).alias("rs60"),
    )

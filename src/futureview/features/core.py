from __future__ import annotations

import polars as pl


def add_core_features(frame: pl.DataFrame) -> pl.DataFrame:
    """Compute point-in-time daily features per symbol.

    Input must contain symbol, date, open, high, low, close, volume and be sorted
    by symbol/date. All rolling values use only current and prior observations.
    """
    by = "symbol"
    close = pl.col("close")
    prev_close = close.shift(1).over(by)
    true_range = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )

    out = frame.sort(["symbol", "date"]).with_columns(
        pl.col("close").rolling_mean(5).over(by).alias("sma5"),
        pl.col("close").rolling_mean(10).over(by).alias("sma10"),
        pl.col("close").rolling_mean(20).over(by).alias("sma20"),
        pl.col("close").rolling_mean(50).over(by).alias("sma50"),
        pl.col("close").rolling_mean(200).over(by).alias("sma200"),
        pl.col("volume").rolling_mean(20).over(by).alias("avg_volume20"),
        pl.col("close").pct_change(20).over(by).alias("return20"),
        pl.col("close").pct_change(60).over(by).alias("return60"),
        pl.col("high").rolling_max(20).over(by).alias("high20"),
        true_range.alias("true_range"),
    )
    out = out.with_columns(
        pl.col("true_range").rolling_mean(14).over(by).alias("atr14"),
        (pl.col("close") * pl.col("avg_volume20")).alias("avg_dollar_volume20"),
        (pl.col("sma50") - pl.col("sma50").shift(10).over(by)).alias("sma50_slope10"),
    )
    return out.with_columns(
        ((pl.col("close") - pl.col("sma20")) / pl.col("atr14")).alias("extension_atr"),
        (pl.col("close") >= pl.col("high20").shift(1).over(by)).alias("breakout20"),
    )

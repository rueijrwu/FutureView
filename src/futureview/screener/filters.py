from __future__ import annotations

import polars as pl

from futureview.config import ScreenerConfig

REQUIRED_FEATURE_COLUMNS = {
    "symbol",
    "date",
    "close",
    "sma50",
    "sma200",
    "sma50_slope10",
    "avg_dollar_volume20",
    "extension_atr",
    "rs20",
    "rs60",
}


def apply_hard_filters(frame: pl.DataFrame, config: ScreenerConfig) -> pl.DataFrame:
    """Reduce a feature cross-section to liquid, technically valid candidates."""
    missing = REQUIRED_FEATURE_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"feature frame is missing required columns: {sorted(missing)}")

    predicate = (
        (pl.col("close") >= config.min_price)
        & (pl.col("avg_dollar_volume20") >= config.min_avg_dollar_volume_20d)
        & (pl.col("extension_atr") <= config.max_extension_atr)
    )

    if config.require_close_above_sma50:
        predicate &= pl.col("close") > pl.col("sma50")
    if config.require_sma50_above_sma200:
        predicate &= pl.col("sma50") > pl.col("sma200")
    if config.require_positive_sma50_slope:
        predicate &= pl.col("sma50_slope10") > 0
    if config.require_positive_rs20:
        predicate &= pl.col("rs20") > 0
    if config.require_positive_rs60:
        predicate &= pl.col("rs60") > 0

    return frame.filter(predicate)

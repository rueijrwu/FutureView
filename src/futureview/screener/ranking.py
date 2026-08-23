from __future__ import annotations

import polars as pl

from futureview.config import RankingConfig


def _percentile_rank(column: str) -> pl.Expr:
    """Cross-sectional percentile where 1.0 is strongest for each date."""
    return pl.col(column).rank(method="average").over("date") / pl.len().over("date")


def _with_component_scores(frame: pl.DataFrame) -> pl.DataFrame:
    trend_score = pl.mean_horizontal(
        (pl.col("close") > pl.col("sma20")).cast(pl.Float64),
        (pl.col("sma20") > pl.col("sma50")).cast(pl.Float64),
        (pl.col("sma50") > pl.col("sma200")).cast(pl.Float64),
        (pl.col("sma50_slope10") > 0).cast(pl.Float64),
    )

    proximity_score = (1.0 + pl.col("distance_from_high20") / 0.05).clip(0.0, 1.0)
    breakout_score = (
        pl.when(pl.col("breakout20"))
        .then(pl.lit(1.0))
        .otherwise(proximity_score)
    )

    return frame.with_columns(
        trend_score.alias("trend_score"),
        breakout_score.alias("breakout_score"),
        _percentile_rank("rs20").alias("rs20_rank"),
        _percentile_rank("rs60").alias("rs60_rank"),
        _percentile_rank("volume_ratio20").alias("volume_rank"),
    )


def _add_base_rank(frame: pl.DataFrame, config: RankingConfig) -> pl.DataFrame:
    base_score = (
        config.rs20_weight * pl.col("rs20_rank")
        + config.rs60_weight * pl.col("rs60_rank")
        + config.trend_weight * pl.col("trend_score")
        + config.breakout_weight * pl.col("breakout_score")
        + config.volume_weight * pl.col("volume_rank")
    )
    return frame.with_columns(base_score.alias("base_score")).with_columns(
        pl.col("base_score")
        .rank(method="ordinal", descending=True)
        .over("date")
        .cast(pl.Int32)
        .alias("base_rank")
    )


def _add_persistence_score(frame: pl.DataFrame, config: RankingConfig) -> pl.DataFrame:
    """Measure how often a symbol stayed in the preliminary Top 50 over 20 sessions."""
    dates = frame.select("date").unique().sort("date").with_row_index("session_idx")
    symbols = frame.select("symbol").unique()
    grid = symbols.join(dates, how="cross")

    top50 = frame.select(
        "symbol",
        "date",
        (pl.col("base_rank") <= 50).cast(pl.Float64).alias("top50_flag"),
    )
    persistence = (
        grid.join(top50, on=["symbol", "date"], how="left")
        .with_columns(pl.col("top50_flag").fill_null(0.0))
        .sort(["symbol", "session_idx"])
        .with_columns(
            pl.col("top50_flag")
            .rolling_mean(window_size=config.persistence_lookback, min_samples=1)
            .over("symbol")
            .alias("persistence_score")
        )
        .select("symbol", "date", "persistence_score")
    )
    return frame.join(persistence, on=["symbol", "date"], how="left")


def _extension_penalty(config: RankingConfig) -> pl.Expr:
    start = config.extension_penalty_start_atr
    width = max(3.0 - start, 1e-9)
    scaled = ((pl.col("extension_atr") - start) / width).clip(0.0, 1.0)
    return (config.extension_penalty_max * scaled.pow(2)).alias("extension_penalty")


def rank_cross_sections(frame: pl.DataFrame, config: RankingConfig) -> pl.DataFrame:
    """Rank one or many daily cross-sections without future information."""
    if frame.is_empty():
        return frame

    ranked = _with_component_scores(frame)
    ranked = _add_base_rank(ranked, config)
    ranked = _add_persistence_score(ranked, config)
    ranked = ranked.with_columns(_extension_penalty(config)).with_columns(
        (
            pl.col("base_score")
            + config.persistence_weight * pl.col("persistence_score")
            - pl.col("extension_penalty")
        ).alias("stock_score")
    )

    return (
        ranked.with_columns(
            pl.col("stock_score")
            .rank(method="ordinal", descending=True)
            .over("date")
            .cast(pl.Int32)
            .alias("rank")
        )
        .sort(["date", "rank"])
    )

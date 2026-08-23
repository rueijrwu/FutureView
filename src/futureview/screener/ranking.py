from __future__ import annotations

import polars as pl


def percentile_rank(expr: str) -> pl.Expr:
    return pl.col(expr).rank(method="average") / pl.len()


def rank_cross_section(frame: pl.DataFrame) -> pl.DataFrame:
    """Rank a single trading-date cross section after hard filters."""
    ranked = frame.with_columns(
        percentile_rank("rs20").alias("rs20_rank"),
        percentile_rank("rs60").alias("rs60_rank"),
        percentile_rank("volume_ratio20").alias("volume_rank"),
    ).with_columns(
        (
            0.30 * pl.col("rs20_rank")
            + 0.25 * pl.col("rs60_rank")
            + 0.20 * pl.col("trend_score")
            + 0.15 * pl.col("breakout_score")
            + 0.10 * pl.col("volume_rank")
        ).alias("stock_score")
    )
    return ranked.sort("stock_score", descending=True).with_row_index("rank", offset=1)

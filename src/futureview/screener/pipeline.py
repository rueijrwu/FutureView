from __future__ import annotations

from datetime import date

import polars as pl

from futureview.config import StrategyConfig
from futureview.features.core import add_core_features, add_relative_strength
from futureview.screener.filters import apply_hard_filters
from futureview.screener.ranking import rank_cross_sections


def build_feature_history(prices: pl.DataFrame, config: StrategyConfig) -> pl.DataFrame:
    """Create the canonical point-in-time feature history used everywhere else."""
    features = add_core_features(prices)
    return add_relative_strength(features, benchmark_symbol=config.benchmark)


def build_ranking_history(prices: pl.DataFrame, config: StrategyConfig) -> pl.DataFrame:
    """Run hard filters and cross-sectional ranking for every available date."""
    features = build_feature_history(prices, config)
    candidates = apply_hard_filters(features, config.screener)
    return rank_cross_sections(candidates, config.ranking)


def top_n_for_date(
    ranking_history: pl.DataFrame,
    *,
    top_n: int = 50,
    as_of: date | None = None,
) -> pl.DataFrame:
    """Return a reproducible Top-N snapshot for a specific or latest date."""
    if ranking_history.is_empty():
        return ranking_history

    selected_date = as_of
    if selected_date is None:
        selected_date = ranking_history.select(pl.col("date").max()).item()

    return (
        ranking_history.filter(
            (pl.col("date") == selected_date) & (pl.col("rank") <= top_n)
        )
        .sort("rank")
    )

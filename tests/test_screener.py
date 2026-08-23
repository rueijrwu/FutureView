from datetime import date

import polars as pl

from futureview.config import RankingConfig, ScreenerConfig
from futureview.screener.filters import apply_hard_filters
from futureview.screener.ranking import rank_cross_sections


def _feature_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "date": [date(2026, 8, 21)] * 3,
            "close": [120.0, 110.0, 105.0],
            "sma20": [115.0, 108.0, 100.0],
            "sma50": [108.0, 105.0, 98.0],
            "sma200": [95.0, 96.0, 90.0],
            "sma50_slope10": [0.05, 0.03, 0.02],
            "avg_dollar_volume20": [200_000_000.0, 150_000_000.0, 120_000_000.0],
            "extension_atr": [1.2, 1.8, 4.2],
            "rs20": [0.18, 0.10, 0.25],
            "rs60": [0.30, 0.20, 0.35],
            "volume_ratio20": [1.8, 1.2, 2.0],
            "distance_from_high20": [0.01, -0.02, 0.02],
            "breakout20": [True, False, True],
        }
    )


def test_hard_filter_rejects_overextended_name() -> None:
    filtered = apply_hard_filters(_feature_frame(), ScreenerConfig(max_extension_atr=3.0))
    assert filtered.get_column("symbol").to_list() == ["AAA", "BBB"]


def test_stronger_candidate_ranks_first() -> None:
    filtered = apply_hard_filters(_feature_frame(), ScreenerConfig(max_extension_atr=3.0))
    ranked = rank_cross_sections(filtered, RankingConfig())
    assert ranked.row(0, named=True)["symbol"] == "AAA"
    assert ranked.row(0, named=True)["rank"] == 1

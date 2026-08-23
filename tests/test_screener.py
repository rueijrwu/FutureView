from datetime import date, timedelta

import polars as pl

from futureview.config import RankingConfig, ScreenerConfig
from futureview.screener.filters import apply_hard_filters
from futureview.screener.incremental_ranking import (
    RankingSymbolState,
    advance_ranking_state,
    bootstrap_ranking_states,
    new_ranking_state,
    persistence_for_current_session,
    rank_changes_for_current_session,
    ranking_state_shard,
)
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


def test_ranking_state_bootstrap_includes_absent_sessions_as_zero() -> None:
    start = date(2026, 7, 1)
    rows: list[dict[str, object]] = []
    for offset in range(25):
        session = start + timedelta(days=offset)
        rows.append({"symbol": "AAA", "date": session, "base_rank": 10, "rank": 12})
        if offset not in {3, 7, 20}:
            rows.append({"symbol": "BBB", "date": session, "base_rank": 40, "rank": 44})

    states = bootstrap_ranking_states(pl.DataFrame(rows))
    bbb = states["BBB"]
    assert len(bbb.base_top50_flags) == 19
    assert sum(bbb.base_top50_flags) == 17
    assert len(bbb.rank_history) == 20
    assert bbb.rank_history[-5] is None
    assert bbb.rank_history[-20] == 44


def test_incremental_ranking_state_matches_persistence_and_rank_change_semantics() -> None:
    state = RankingSymbolState(
        symbol="AAA",
        as_of=date(2026, 8, 19),
        base_top50_flags=(1,) * 18 + (0,),
        rank_history=tuple(range(21, 1, -1)),
    )

    persistence = persistence_for_current_session(state, is_base_top50=True)
    assert persistence == 0.95

    change_5d, change_20d = rank_changes_for_current_session(state, current_rank=3)
    assert change_5d == 4
    assert change_20d == 18

    next_state = advance_ranking_state(
        state,
        trading_date=date(2026, 8, 20),
        is_base_top50=True,
        current_rank=3,
    )
    assert next_state.base_top50_flags[-1] == 1
    assert len(next_state.base_top50_flags) == 19
    assert next_state.rank_history[-1] == 3
    assert len(next_state.rank_history) == 20


def test_new_symbol_state_backfills_prior_sessions_and_round_trips() -> None:
    state = new_ranking_state(
        "NEW",
        as_of=date(2026, 8, 19),
        prior_session_count=100,
    )
    assert state.base_top50_flags == (0,) * 19
    assert state.rank_history == (None,) * 20
    assert RankingSymbolState.from_dict(state.to_dict()) == state
    assert ranking_state_shard("NEW") == ranking_state_shard("NEW")

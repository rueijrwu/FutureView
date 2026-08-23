from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import polars as pl

RANKING_STATE_VERSION = 1
RANKING_STATE_SHARDS = 32
PERSISTENCE_LOOKBACK = 20
RANK_CHANGE_LOOKBACK = 20


@dataclass(frozen=True)
class RankingSymbolState:
    """Minimal per-symbol history needed for incremental ranking outputs.

    `base_top50_flags` stores up to the previous 19 market sessions, including
    zeros for sessions where the symbol was absent from the filtered candidate
    set. `rank_history` stores up to the previous 20 final ranks aligned to
    market sessions; absence is represented by ``None``.
    """

    symbol: str
    as_of: date
    base_top50_flags: tuple[int, ...]
    rank_history: tuple[int | None, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "as_of": self.as_of.isoformat(),
            "base_top50_flags": list(self.base_top50_flags),
            "rank_history": list(self.rank_history),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RankingSymbolState:
        return cls(
            symbol=str(payload["symbol"]),
            as_of=date.fromisoformat(str(payload["as_of"])),
            base_top50_flags=tuple(int(value) for value in payload["base_top50_flags"]),
            rank_history=tuple(
                None if value is None else int(value) for value in payload["rank_history"]
            ),
        )


def ranking_state_shard(symbol: str, shard_count: int = RANKING_STATE_SHARDS) -> int:
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    return sum(ord(character) for character in symbol) % shard_count


def _session_dates(frame: pl.DataFrame, as_of: date | None = None) -> list[date]:
    selected = frame if as_of is None else frame.filter(pl.col("date") <= as_of)
    return selected.select("date").unique().sort("date").get_column("date").to_list()


def bootstrap_ranking_states(
    ranking_history: pl.DataFrame,
    *,
    as_of: date | None = None,
) -> dict[str, RankingSymbolState]:
    """Bootstrap exact online state from canonical batch ranking history."""
    required = {"symbol", "date", "base_rank", "rank"}
    missing = required.difference(ranking_history.columns)
    if missing:
        raise ValueError(f"ranking frame is missing required columns: {sorted(missing)}")
    if ranking_history.is_empty():
        return {}

    dates = _session_dates(ranking_history, as_of)
    if not dates:
        return {}
    state_as_of = dates[-1]
    selected = ranking_history.filter(pl.col("date") <= state_as_of)
    symbols = selected.select("symbol").unique().get_column("symbol").to_list()

    by_symbol_date = {
        (str(row["symbol"]), row["date"]): row
        for row in selected.select("symbol", "date", "base_rank", "rank").to_dicts()
    }

    states: dict[str, RankingSymbolState] = {}
    for symbol_value in symbols:
        symbol = str(symbol_value)
        flags: list[int] = []
        ranks: list[int | None] = []
        for session_date in dates:
            row = by_symbol_date.get((symbol, session_date))
            flags.append(1 if row is not None and int(row["base_rank"]) <= 50 else 0)
            ranks.append(None if row is None else int(row["rank"]))
        states[symbol] = RankingSymbolState(
            symbol=symbol,
            as_of=state_as_of,
            base_top50_flags=tuple(flags[-(PERSISTENCE_LOOKBACK - 1) :]),
            rank_history=tuple(ranks[-RANK_CHANGE_LOOKBACK:]),
        )
    return states


def new_ranking_state(
    symbol: str,
    *,
    as_of: date,
    prior_session_count: int,
) -> RankingSymbolState:
    """Create state for a symbol entering after prior market sessions."""
    return RankingSymbolState(
        symbol=symbol,
        as_of=as_of,
        base_top50_flags=(0,) * min(prior_session_count, PERSISTENCE_LOOKBACK - 1),
        rank_history=(None,) * min(prior_session_count, RANK_CHANGE_LOOKBACK),
    )


def persistence_for_current_session(
    state: RankingSymbolState,
    *,
    is_base_top50: bool,
) -> float:
    flags = (*state.base_top50_flags, int(is_base_top50))[-PERSISTENCE_LOOKBACK:]
    return sum(flags) / len(flags)


def rank_changes_for_current_session(
    state: RankingSymbolState,
    *,
    current_rank: int,
) -> tuple[int | None, int | None]:
    rank_5d = state.rank_history[-5] if len(state.rank_history) >= 5 else None
    rank_20d = state.rank_history[-20] if len(state.rank_history) >= 20 else None
    change_5d = None if rank_5d is None else int(rank_5d) - int(current_rank)
    change_20d = None if rank_20d is None else int(rank_20d) - int(current_rank)
    return change_5d, change_20d


def advance_ranking_state(
    state: RankingSymbolState,
    *,
    trading_date: date,
    is_base_top50: bool,
    current_rank: int | None,
) -> RankingSymbolState:
    if trading_date <= state.as_of:
        raise ValueError("ranking update date must be later than state.as_of")

    flags = (*state.base_top50_flags, int(is_base_top50))[-(PERSISTENCE_LOOKBACK - 1) :]
    ranks = (*state.rank_history, None if current_rank is None else int(current_rank))[
        -RANK_CHANGE_LOOKBACK:
    ]
    return RankingSymbolState(
        symbol=state.symbol,
        as_of=trading_date,
        base_top50_flags=flags,
        rank_history=ranks,
    )

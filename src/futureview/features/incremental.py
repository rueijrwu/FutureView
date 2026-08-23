from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import polars as pl

from futureview.features.core import REQUIRED_PRICE_COLUMNS

STATE_VERSION = 1
STATE_SHARDS = 32


@dataclass(frozen=True)
class RollingSymbolState:
    """Compact rolling state required to produce the next daily feature row.

    Arrays are ordered oldest -> newest. The state deliberately stores only the
    finite windows required by the canonical batch feature engine; it does not
    retain the full price history.
    """

    symbol: str
    as_of: date
    closes: tuple[float, ...]
    highs: tuple[float, ...]
    volumes: tuple[float, ...]
    true_ranges: tuple[float, ...]
    sma50_history: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "as_of": self.as_of.isoformat(),
            "closes": list(self.closes),
            "highs": list(self.highs),
            "volumes": list(self.volumes),
            "true_ranges": list(self.true_ranges),
            "sma50_history": list(self.sma50_history),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RollingSymbolState:
        return cls(
            symbol=str(payload["symbol"]),
            as_of=date.fromisoformat(str(payload["as_of"])),
            closes=tuple(float(value) for value in payload["closes"]),
            highs=tuple(float(value) for value in payload["highs"]),
            volumes=tuple(float(value) for value in payload["volumes"]),
            true_ranges=tuple(float(value) for value in payload["true_ranges"]),
            sma50_history=tuple(float(value) for value in payload["sma50_history"]),
        )


def state_shard(symbol: str, shard_count: int = STATE_SHARDS) -> int:
    """Deterministic shard id that is trivial to reproduce in JavaScript."""
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    return sum(ord(character) for character in symbol) % shard_count


def _trim(values: tuple[float, ...], value: float, size: int) -> tuple[float, ...]:
    return (*values, float(value))[-size:]


def _require_full(values: tuple[float, ...], size: int) -> float | None:
    if len(values) < size:
        return None
    return sum(values[-size:]) / size


def _true_range(high: float, low: float, previous_close: float) -> float:
    return max(high - low, abs(high - previous_close), abs(low - previous_close))


def bootstrap_symbol_state(history: pl.DataFrame, symbol: str) -> RollingSymbolState:
    missing = REQUIRED_PRICE_COLUMNS.difference(history.columns)
    if missing:
        raise ValueError(f"price frame is missing required columns: {sorted(missing)}")

    rows = history.filter(pl.col("symbol") == symbol).sort("date")
    if rows.height < 200:
        raise ValueError(f"{symbol} requires at least 200 sessions to bootstrap incremental state")

    closes = tuple(float(value) for value in rows.get_column("close").tail(200).to_list())
    highs = tuple(float(value) for value in rows.get_column("high").tail(50).to_list())
    volumes = tuple(float(value) for value in rows.get_column("volume").tail(20).to_list())

    recent = rows.tail(24)
    recent_close = recent.get_column("close").to_list()
    recent_high = recent.get_column("high").to_list()
    recent_low = recent.get_column("low").to_list()
    tr_values = [
        _true_range(float(recent_high[idx]), float(recent_low[idx]), float(recent_close[idx - 1]))
        for idx in range(1, len(recent_close))
    ]

    close_all = [float(value) for value in rows.get_column("close").to_list()]
    sma50_values: list[float] = []
    for end in range(max(49, len(close_all) - 11), len(close_all)):
        if end + 1 >= 50:
            sma50_values.append(sum(close_all[end - 49 : end + 1]) / 50.0)

    as_of = rows.select(pl.col("date").max()).item()
    if not isinstance(as_of, date):
        raise TypeError("history did not contain a valid date")

    return RollingSymbolState(
        symbol=symbol,
        as_of=as_of,
        closes=closes,
        highs=highs,
        volumes=volumes,
        true_ranges=tuple(tr_values[-14:]),
        sma50_history=tuple(sma50_values[-11:]),
    )


def bootstrap_states(history: pl.DataFrame) -> dict[str, RollingSymbolState]:
    """Bootstrap all symbols with enough history for the SMA200 strategy."""
    missing = REQUIRED_PRICE_COLUMNS.difference(history.columns)
    if missing:
        raise ValueError(f"price frame is missing required columns: {sorted(missing)}")

    states: dict[str, RollingSymbolState] = {}
    partitions = history.sort(["symbol", "date"]).partition_by("symbol", as_dict=True)
    for key, rows in partitions.items():
        symbol = key[0] if isinstance(key, tuple) else key
        if rows.height >= 200:
            states[str(symbol)] = bootstrap_symbol_state(rows, str(symbol))
    return states


def update_symbol_state(
    state: RollingSymbolState,
    *,
    trading_date: date,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> tuple[RollingSymbolState, dict[str, Any]]:
    if trading_date <= state.as_of:
        raise ValueError("incremental update date must be later than state.as_of")
    if len(state.closes) < 200 or len(state.highs) < 50 or len(state.volumes) < 20:
        raise ValueError("incremental state is not fully bootstrapped")

    prior_closes = state.closes
    prior_highs = state.highs
    prior_volumes = state.volumes
    previous_close = prior_closes[-1]
    true_range = _true_range(float(high), float(low), previous_close)

    closes = _trim(prior_closes, close, 200)
    highs = _trim(prior_highs, high, 50)
    volumes = _trim(prior_volumes, volume, 20)
    true_ranges = _trim(state.true_ranges, true_range, 14)

    sma5 = _require_full(closes, 5)
    sma10 = _require_full(closes, 10)
    sma20 = _require_full(closes, 20)
    sma50 = _require_full(closes, 50)
    sma200 = _require_full(closes, 200)
    avg_volume20 = _require_full(volumes, 20)
    atr14 = _require_full(true_ranges, 14)

    if None in (sma5, sma10, sma20, sma50, sma200, avg_volume20, atr14):
        raise ValueError("incremental feature windows are incomplete")

    assert sma20 is not None
    assert sma50 is not None
    assert sma200 is not None
    assert avg_volume20 is not None
    assert atr14 is not None

    sma50_history = _trim(state.sma50_history, sma50, 11)
    sma50_prior10 = sma50_history[0] if len(sma50_history) == 11 else None

    high20_prior = max(prior_highs[-20:])
    high50_prior = max(prior_highs[-50:])
    return20 = close / prior_closes[-20] - 1.0
    return60 = close / prior_closes[-60] - 1.0

    feature_row: dict[str, Any] = {
        "symbol": state.symbol,
        "date": trading_date,
        "open": float(open_),
        "high": float(high),
        "low": float(low),
        "close": float(close),
        "volume": float(volume),
        "sma5": sma5,
        "sma10": sma10,
        "sma20": sma20,
        "sma50": sma50,
        "sma200": sma200,
        "avg_volume20": avg_volume20,
        "return20": return20,
        "return60": return60,
        "high20_prior": high20_prior,
        "high50_prior": high50_prior,
        "true_range": true_range,
        "atr14": atr14,
        "avg_dollar_volume20": close * avg_volume20,
        "volume_ratio20": volume / avg_volume20 if avg_volume20 else None,
        "sma50_slope10": (sma50 / sma50_prior10 - 1.0) if sma50_prior10 else None,
        "extension_atr": (close - sma20) / atr14 if atr14 else None,
        "breakout20": close >= high20_prior,
        "breakout50": close >= high50_prior,
        "distance_from_high20": close / high20_prior - 1.0,
    }

    next_state = RollingSymbolState(
        symbol=state.symbol,
        as_of=trading_date,
        closes=closes,
        highs=highs,
        volumes=volumes,
        true_ranges=true_ranges,
        sma50_history=sma50_history,
    )
    return next_state, feature_row

from __future__ import annotations

from datetime import date
from typing import Protocol, Sequence

import polars as pl


class MarketDataProvider(Protocol):
    """Provider-neutral contract for historical daily market data.

    Provider implementations should normalize symbols, dates, corporate actions,
    and adjusted OHLCV into the canonical schema before returning data.
    """

    def fetch_daily_bars(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
    ) -> pl.DataFrame: ...

    def list_active_us_equities(self, as_of: date | None = None) -> pl.DataFrame: ...

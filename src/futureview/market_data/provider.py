from __future__ import annotations

from datetime import date
from typing import Protocol

import pandas as pd

CANONICAL_BAR_COLUMNS = [
    "timestamp",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
]


class HistoricalBarProvider(Protocol):
    """Provider-neutral contract for historical OHLCV bars.

    Providers must return one row per completed bar, ordered by timestamp, using
    UTC timestamps and the canonical FutureView price/volume schema.
    """

    def fetch_bars(
        self,
        symbol: str,
        start: str | date,
        end: str | date,
        *,
        interval: str = "5m",
    ) -> pd.DataFrame: ...

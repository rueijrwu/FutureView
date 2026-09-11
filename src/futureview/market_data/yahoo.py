from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf

from futureview.market_data.provider import CANONICAL_BAR_COLUMNS

DEFAULT_CACHE_DIR = Path(".cache/futureview/yahoo")
DEFAULT_CHUNK_DAYS = 59
_REQUIRED_YAHOO_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def _as_date_string(value: str | date) -> str:
    return pd.Timestamp(value).date().isoformat()


def _date_chunks(start: str | date, end: str | date, chunk_days: int) -> list[tuple[str, str]]:
    """Build [start, end) chunks suitable for yfinance downloads."""
    if chunk_days <= 0:
        raise ValueError("chunk_days must be positive")
    first = pd.Timestamp(start).normalize()
    last = pd.Timestamp(end).normalize()
    if first >= last:
        raise ValueError("start must be earlier than end")

    chunks: list[tuple[str, str]] = []
    cursor = first
    while cursor < last:
        chunk_end = min(cursor + pd.Timedelta(days=chunk_days), last)
        chunks.append((cursor.date().isoformat(), chunk_end.date().isoformat()))
        cursor = chunk_end
    return chunks


def _safe_symbol(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", symbol).strip("_") or "symbol"


def _cache_path(root: Path, symbol: str, interval: str, start: str, end: str) -> Path:
    return root / f"{_safe_symbol(symbol)}_{interval}_{start}_{end}.csv.gz"


def normalize_yfinance_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Normalize one yfinance symbol to FutureView's canonical OHLCV schema."""
    if frame.empty:
        return pd.DataFrame(columns=CANONICAL_BAR_COLUMNS)

    work = frame.copy()
    if isinstance(work.columns, pd.MultiIndex):
        last_level = work.columns.get_level_values(-1)
        if symbol in last_level:
            work = work.xs(symbol, axis=1, level=-1, drop_level=True)
        else:
            work.columns = work.columns.get_level_values(0)

    missing = set(_REQUIRED_YAHOO_COLUMNS).difference(work.columns)
    if missing:
        raise ValueError(f"Yahoo frame missing required columns: {sorted(missing)}")

    timestamps = pd.to_datetime(work.index)
    if timestamps.tz is None:
        timestamps = timestamps.tz_localize("UTC")
    else:
        timestamps = timestamps.tz_convert("UTC")

    out = pd.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": symbol,
            "open": pd.to_numeric(work["Open"], errors="raise").to_numpy(),
            "high": pd.to_numeric(work["High"], errors="raise").to_numpy(),
            "low": pd.to_numeric(work["Low"], errors="raise").to_numpy(),
            "close": pd.to_numeric(work["Close"], errors="raise").to_numpy(),
            "volume": pd.to_numeric(work["Volume"], errors="raise").to_numpy(),
        }
    )
    out = out.dropna(subset=["open", "high", "low", "close", "volume"])
    out = out.drop_duplicates(subset=["timestamp"], keep="last")
    out = out.sort_values("timestamp").reset_index(drop=True)
    return out.loc[:, CANONICAL_BAR_COLUMNS]


class YahooMarketDataProvider:
    """Free historical bar provider backed by Yahoo Finance via yfinance.

    Yahoo is intended as a bootstrap/prototyping source. Intraday history depth
    is controlled by Yahoo and may be shorter than the requested range. Each
    successful chunk is cached locally so repeated research runs do not redownload it.
    """

    def __init__(
        self,
        *,
        cache_dir: str | Path | None = None,
        chunk_days: int = DEFAULT_CHUNK_DAYS,
        use_cache: bool = True,
    ) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        self.chunk_days = chunk_days
        self.use_cache = use_cache
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _download_chunk(self, symbol: str, start: str, end: str, interval: str) -> pd.DataFrame:
        raw = yf.download(
            symbol,
            start=start,
            end=end,
            interval=interval,
            auto_adjust=False,
            actions=False,
            progress=False,
            threads=False,
            prepost=True,
        )
        return normalize_yfinance_frame(raw, symbol)

    def fetch_bars(
        self,
        symbol: str,
        start: str | date,
        end: str | date,
        *,
        interval: str = "5m",
    ) -> pd.DataFrame:
        symbol = symbol.strip()
        if not symbol:
            raise ValueError("symbol must not be empty")
        start_s = _as_date_string(start)
        end_s = _as_date_string(end)
        chunks = _date_chunks(start_s, end_s, self.chunk_days)
        frames: list[pd.DataFrame] = []

        for chunk_id, (chunk_start, chunk_end) in enumerate(chunks, start=1):
            cache_path = _cache_path(self.cache_dir, symbol, interval, chunk_start, chunk_end)
            if self.use_cache and cache_path.exists():
                frame = pd.read_csv(cache_path, parse_dates=["timestamp"])
                frame = frame.loc[:, CANONICAL_BAR_COLUMNS]
                print(
                    f"YAHOO CACHE_HIT chunk={chunk_id}/{len(chunks)} "
                    f"symbol={symbol} start={chunk_start} end={chunk_end} rows={len(frame)}"
                )
            else:
                print(
                    f"YAHOO DOWNLOAD chunk={chunk_id}/{len(chunks)} "
                    f"symbol={symbol} start={chunk_start} end={chunk_end} interval={interval}"
                )
                frame = self._download_chunk(symbol, chunk_start, chunk_end, interval)
                if not frame.empty and self.use_cache:
                    frame.to_csv(cache_path, index=False, compression="gzip")
                    print(f"YAHOO CACHE_WRITE path={cache_path} rows={len(frame)}")

            if not frame.empty:
                frames.append(frame)

        if not frames:
            raise RuntimeError(
                f"Yahoo returned no bars for {symbol} from {start_s} to {end_s} at {interval}. "
                "For intraday intervals, Yahoo may not retain history as far back as requested."
            )

        out = pd.concat(frames, ignore_index=True)
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
        out = out.drop_duplicates(subset=["timestamp", "symbol"], keep="last")
        out = out.sort_values("timestamp").reset_index(drop=True)
        if out["timestamp"].duplicated().any():
            raise ValueError("duplicate timestamps remain after Yahoo normalization")
        return out.loc[:, CANONICAL_BAR_COLUMNS]

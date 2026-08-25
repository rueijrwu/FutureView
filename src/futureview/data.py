from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

import pandas as pd
import yfinance as yf

CANONICAL_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


@dataclass(frozen=True)
class DataAudit:
    rows: int
    start: str
    end: str
    duplicate_dates: int
    missing_values: int


def _flatten_single_ticker_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.copy()
        frame.columns = frame.columns.get_level_values(0)
    return frame


def download_ticker_daily(symbol: str, period: str = "3y", attempts: int = 3) -> pd.DataFrame:
    ticker = symbol.strip().upper()
    if not ticker:
        raise ValueError("symbol must be non-empty")

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            frame = yf.download(
                ticker,
                period=period,
                interval="1d",
                auto_adjust=False,
                actions=False,
                progress=False,
                threads=False,
                timeout=30,
            )
            if frame is not None and not frame.empty:
                return canonicalize_ohlcv(frame)
            last_error = RuntimeError(f"Yahoo Finance returned an empty {ticker} frame")
        except Exception as exc:  # network/provider errors are retried, then surfaced
            last_error = exc
        if attempt < attempts:
            time.sleep(float(attempt))
    raise RuntimeError(
        f"Failed to download {ticker} daily data after {attempts} attempts"
    ) from last_error


def download_spy_daily(period: str = "3y", attempts: int = 3) -> pd.DataFrame:
    return download_ticker_daily("SPY", period=period, attempts=attempts)


def canonicalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    frame = _flatten_single_ticker_columns(frame)
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {missing}")

    out = frame[required].copy().reset_index()
    date_column = out.columns[0]
    out = out.rename(
        columns={
            date_column: "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    out["date"] = pd.to_datetime(out["date"], utc=True).dt.tz_convert(None).dt.normalize()
    out = out[CANONICAL_COLUMNS].sort_values("date").drop_duplicates("date", keep="last")
    out = out.reset_index(drop=True)
    out["volume"] = pd.to_numeric(out["volume"], errors="raise")
    return out


def validate_daily_ohlcv(frame: pd.DataFrame, minimum_rows: int = 650) -> DataAudit:
    if list(frame.columns) != CANONICAL_COLUMNS:
        raise ValueError(f"Unexpected canonical columns: {list(frame.columns)}")
    if len(frame) < minimum_rows:
        raise ValueError(f"Too few rows for daily data: {len(frame)} < {minimum_rows}")
    if not frame["date"].is_monotonic_increasing:
        raise ValueError("Dates are not strictly chronological")

    duplicate_dates = int(frame["date"].duplicated().sum())
    if duplicate_dates:
        raise ValueError(f"Duplicate dates found: {duplicate_dates}")

    missing_values = int(frame.isna().sum().sum())
    if missing_values:
        raise ValueError(f"Missing values found: {missing_values}")

    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("Non-positive OHLC price found")
    if (frame["volume"] < 0).any():
        raise ValueError("Negative volume found")
    if (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any():
        raise ValueError("Invalid OHLC row: high is below open/close/low")
    if (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("Invalid OHLC row: low is above open/close/high")

    return DataAudit(
        rows=len(frame),
        start=frame["date"].iloc[0].date().isoformat(),
        end=frame["date"].iloc[-1].date().isoformat(),
        duplicate_dates=duplicate_dates,
        missing_values=missing_values,
    )


def save_canonical_csv(frame: pd.DataFrame, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, date_format="%Y-%m-%d")
    return path

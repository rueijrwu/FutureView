from __future__ import annotations

import json
import os
import time as time_module
from datetime import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

CANONICAL_INTRADAY_COLUMNS = ["timestamp", "date", "open", "high", "low", "close", "volume"]
CANONICAL_DAILY_COLUMNS = ["date", "open", "high", "low", "close", "volume"]
ALPACA_BASE_URL = "https://data.alpaca.markets"
DEFAULT_CHUNK_DAYS = 365
DEFAULT_MAX_RETRIES = 8
DEFAULT_CACHE_DIR = Path(".cache/futureview/alpaca")


def _headers(key_id: str, secret_key: str) -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": key_id,
        "APCA-API-SECRET-KEY": secret_key,
        "Accept": "application/json",
    }


def _request_json(url: str, key_id: str, secret_key: str) -> dict:
    request = Request(url, headers=_headers(key_id, secret_key))
    for attempt in range(1, DEFAULT_MAX_RETRIES + 1):
        try:
            with urlopen(request, timeout=60) as response:  # noqa: S310 - fixed Alpaca host
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt >= DEFAULT_MAX_RETRIES:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers is not None else None
            try:
                delay = max(1.0, float(retry_after)) if retry_after else min(60.0, float(2 ** (attempt - 1)))
            except ValueError:
                delay = min(60.0, float(2 ** (attempt - 1)))
            print(f"ALPACA RETRY status={exc.code} retry={attempt}/{DEFAULT_MAX_RETRIES} sleep_seconds={delay:.1f}")
            time_module.sleep(delay)
    raise RuntimeError("Alpaca request retry loop exhausted")


def _date_chunks(start: str, end: str, chunk_days: int) -> list[tuple[str, str]]:
    first = pd.Timestamp(start).normalize()
    last = pd.Timestamp(end).normalize()
    if first > last:
        raise ValueError("start must be <= end")
    chunks: list[tuple[str, str]] = []
    cursor = first
    while cursor <= last:
        chunk_end = min(cursor + pd.Timedelta(days=chunk_days - 1), last)
        chunks.append((cursor.date().isoformat(), chunk_end.date().isoformat()))
        cursor = chunk_end + pd.Timedelta(days=1)
    return chunks


def _cache_path(cache_dir: Path, start: str, end: str, timeframe: str, feed: str) -> Path:
    safe_timeframe = timeframe.lower().replace(" ", "")
    return cache_dir / f"SPY_{feed}_{safe_timeframe}_{start}_{end}.csv.gz"


def _read_cache(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True).dt.tz_convert("America/New_York")
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    return frame[CANONICAL_INTRADAY_COLUMNS]


def _write_cache(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = frame.copy()
    out["timestamp"] = out["timestamp"].astype(str)
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out.to_csv(path, index=False, compression="gzip")


def download_spy_intraday_alpaca(
    start: str,
    end: str,
    *,
    key_id: str | None = None,
    secret_key: str | None = None,
    timeframe: str = "30Min",
    feed: str = "iex",
    chunk_days: int = DEFAULT_CHUNK_DAYS,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
) -> pd.DataFrame:
    """Download cached SPY intraday bars from Alpaca Historical Market Data.

    The default feed is IEX so the free Basic market-data plan can be used. Data is
    requested in bounded date chunks and each successful chunk is cached immediately
    as CSV.gz. Subsequent runs reuse the cache and do not call the provider again.
    """
    kid = key_id or os.environ.get("APCA_API_KEY_ID")
    secret = secret_key or os.environ.get("APCA_API_SECRET_KEY")
    if not kid or not secret:
        raise RuntimeError("APCA_API_KEY_ID and APCA_API_SECRET_KEY are required")
    if chunk_days <= 0:
        raise ValueError("chunk_days must be positive")

    cache_root = Path(cache_dir)
    chunks = _date_chunks(start, end, chunk_days)
    frames: list[pd.DataFrame] = []

    for chunk_id, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        cache_path = _cache_path(cache_root, chunk_start, chunk_end, timeframe, feed)
        if cache_path.exists():
            print(f"ALPACA CACHE_HIT chunk={chunk_id}/{len(chunks)} start={chunk_start} end={chunk_end}")
            frames.append(_read_cache(cache_path))
            continue

        print(f"ALPACA DOWNLOAD chunk={chunk_id}/{len(chunks)} start={chunk_start} end={chunk_end}")
        page_token: str | None = None
        bars: list[dict[str, object]] = []
        query_start = f"{chunk_start}T00:00:00Z"
        query_end = f"{(pd.Timestamp(chunk_end) + pd.Timedelta(days=1)).date().isoformat()}T00:00:00Z"
        while True:
            params = {
                "timeframe": timeframe,
                "start": query_start,
                "end": query_end,
                "adjustment": "raw",
                "feed": feed,
                "limit": 10000,
            }
            if page_token:
                params["page_token"] = page_token
            url = f"{ALPACA_BASE_URL}/v2/stocks/SPY/bars?{urlencode(params)}"
            payload = _request_json(url, kid, secret)
            bars.extend(payload.get("bars") or [])
            page_token = payload.get("next_page_token")
            if not page_token:
                break

        if not bars:
            continue

        raw = pd.DataFrame(bars)
        required = {"t", "o", "h", "l", "c", "v"}
        missing = required.difference(raw.columns)
        if missing:
            raise ValueError(f"Alpaca response missing fields: {sorted(missing)}")

        ts = pd.to_datetime(raw["t"], utc=True).dt.tz_convert("America/New_York")
        frame = pd.DataFrame(
            {
                "timestamp": ts,
                "date": ts.dt.tz_localize(None).dt.normalize(),
                "open": pd.to_numeric(raw["o"], errors="raise"),
                "high": pd.to_numeric(raw["h"], errors="raise"),
                "low": pd.to_numeric(raw["l"], errors="raise"),
                "close": pd.to_numeric(raw["c"], errors="raise"),
                "volume": pd.to_numeric(raw["v"], errors="raise"),
            }
        )
        clock = frame["timestamp"].dt.time
        regular = np.array([(t >= time(9, 30)) and (t < time(16, 0)) for t in clock], dtype=bool)
        frame = frame.loc[regular, CANONICAL_INTRADAY_COLUMNS]
        frame = frame[(frame["date"] >= pd.Timestamp(chunk_start)) & (frame["date"] <= pd.Timestamp(chunk_end))]
        frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)
        if not frame.empty:
            _write_cache(frame, cache_path)
            frames.append(frame)

    if not frames:
        raise RuntimeError("Alpaca returned no SPY intraday bars for the requested range")

    out = pd.concat(frames, ignore_index=True).sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)
    return out[CANONICAL_INTRADAY_COLUMNS]


def _complete_rth_dates(frame: pd.DataFrame) -> pd.Index:
    counts = frame.groupby("date").size()
    return counts[counts == 13].index


def aggregate_rth_daily(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate complete 30-minute Alpaca IEX regular sessions into daily OHLCV."""
    if frame.empty:
        raise ValueError("intraday frame is empty")
    complete_dates = _complete_rth_dates(frame)
    work = frame[frame["date"].isin(complete_dates)].sort_values("timestamp")
    rows: list[dict[str, object]] = []
    for date, group in work.groupby("date", sort=True):
        rows.append(
            {
                "date": pd.Timestamp(date),
                "open": float(group["open"].iloc[0]),
                "high": float(group["high"].max()),
                "low": float(group["low"].min()),
                "close": float(group["close"].iloc[-1]),
                "volume": float(group["volume"].sum()),
            }
        )
    if not rows:
        raise RuntimeError("no complete Alpaca IEX regular sessions for daily aggregation")
    return pd.DataFrame(rows, columns=CANONICAL_DAILY_COLUMNS).sort_values("date").reset_index(drop=True)


def aggregate_rth_two_bars(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 30-minute RTH bars into 09:30-13:30 and 13:30-16:00 ET bars."""
    if frame.empty:
        raise ValueError("intraday frame is empty")
    complete_dates = _complete_rth_dates(frame)
    work = frame[frame["date"].isin(complete_dates)].copy()
    local_time = work["timestamp"].dt.time
    work["session_bar"] = [0 if t < time(13, 30) else 1 for t in local_time]

    rows: list[dict[str, object]] = []
    for (date, session_bar), group in work.groupby(["date", "session_bar"], sort=True):
        group = group.sort_values("timestamp")
        expected = 8 if int(session_bar) == 0 else 5
        if len(group) != expected:
            continue
        rows.append(
            {
                "timestamp": group["timestamp"].iloc[-1],
                "date": pd.Timestamp(date),
                "session_bar": int(session_bar),
                "open": float(group["open"].iloc[0]),
                "high": float(group["high"].max()),
                "low": float(group["low"].min()),
                "close": float(group["close"].iloc[-1]),
                "volume": float(group["volume"].sum()),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError("no complete regular-session intraday bars after aggregation")
    counts = out.groupby("date")["session_bar"].nunique()
    complete_dates = counts[counts == 2].index
    return out[out["date"].isin(complete_dates)].sort_values(["date", "session_bar"]).reset_index(drop=True)

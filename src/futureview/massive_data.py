from __future__ import annotations

import json
import os
import time as time_module
from datetime import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

import numpy as np
import pandas as pd

CANONICAL_INTRADAY_COLUMNS = ["timestamp", "date", "open", "high", "low", "close", "volume"]
MASSIVE_BASE_URL = "https://api.massive.com"
DEFAULT_MAX_RETRIES = 8
DEFAULT_REQUEST_PAUSE_SECONDS = 1.0
DEFAULT_CHUNK_DAYS = 60


class MassiveForbiddenError(RuntimeError):
    """Raised when Massive rejects a request because the account lacks access."""


def _retry_delay_seconds(exc: HTTPError, attempt: int) -> float:
    retry_after = exc.headers.get("Retry-After") if exc.headers is not None else None
    if retry_after:
        try:
            return max(1.0, float(retry_after))
        except ValueError:
            pass
    return min(60.0, float(2 ** (attempt - 1)))


def _request_json(
    url: str,
    api_key: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict:
    separator = "&" if "?" in url else "?"
    if "apiKey=" not in url:
        url = f"{url}{separator}{urlencode({'apiKey': api_key})}"

    for attempt in range(1, max_retries + 1):
        try:
            with urlopen(url, timeout=60) as response:  # noqa: S310 - fixed Massive host / provider next_url
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 403:
                raise MassiveForbiddenError(
                    "Massive returned HTTP 403. The requested date range may be older than "
                    "your Stocks plan history entitlement, or the API key may not have Stocks access."
                ) from exc
            if exc.code != 429 or attempt >= max_retries:
                raise
            delay = _retry_delay_seconds(exc, attempt)
            print(
                f"MASSIVE RATE_LIMIT retry={attempt}/{max_retries} "
                f"sleep_seconds={delay:.1f}"
            )
            time_module.sleep(delay)

    raise RuntimeError("Massive request retry loop exhausted")


def _date_chunks(start: str, end: str, chunk_days: int) -> list[tuple[str, str]]:
    if chunk_days <= 0:
        raise ValueError("chunk_days must be positive")
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


def download_spy_intraday_massive(
    start: str,
    end: str,
    *,
    api_key: str | None = None,
    base_minutes: int = 30,
    chunk_days: int = DEFAULT_CHUNK_DAYS,
    request_pause_seconds: float = DEFAULT_REQUEST_PAUSE_SECONDS,
    skip_forbidden_history: bool = True,
) -> pd.DataFrame:
    """Download SPY intraday aggregates from Massive and keep NYSE regular session only.

    Requests are split into bounded date chunks and rate-limit-safe pagination. HTTP 429
    responses respect Retry-After when present and otherwise use exponential backoff.
    If an old chunk is rejected with HTTP 403, the default behavior is to skip that chunk
    and continue forward so Basic-plan two-year history can still be used. If every chunk
    is forbidden, a clear entitlement/key error is raised.
    """
    key = api_key or os.environ.get("MASSIVE_API_KEY")
    if not key:
        raise RuntimeError("MASSIVE_API_KEY is required for the intraday frequency experiment")
    if base_minutes <= 0:
        raise ValueError("base_minutes must be positive")
    if request_pause_seconds < 0:
        raise ValueError("request_pause_seconds must be non-negative")

    rows: list[dict[str, float | int]] = []
    chunks = _date_chunks(start, end, chunk_days)
    forbidden_chunks = 0
    successful_chunks = 0

    for chunk_id, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        print(
            f"MASSIVE DOWNLOAD chunk={chunk_id}/{len(chunks)} "
            f"start={chunk_start} end={chunk_end}"
        )
        url = (
            f"{MASSIVE_BASE_URL}/v2/aggs/ticker/SPY/range/{base_minutes}/minute/{chunk_start}/{chunk_end}"
            "?adjusted=false&sort=asc&limit=50000"
        )
        page = 0
        chunk_rows_before = len(rows)
        try:
            while url:
                page += 1
                payload = _request_json(url, key)
                status = str(payload.get("status", "")).upper()
                if status not in {"OK", "DELAYED"} and "results" not in payload:
                    raise RuntimeError(
                        f"Massive aggregate request failed: status={payload.get('status')} "
                        f"error={payload.get('error')}"
                    )
                rows.extend(payload.get("results", []))
                next_url = payload.get("next_url")
                if next_url:
                    parsed = urlparse(next_url)
                    if parsed.scheme != "https" or parsed.netloc not in {
                        "api.massive.com",
                        "massive.com",
                        "www.massive.com",
                    }:
                        raise RuntimeError(f"unexpected Massive pagination host: {parsed.netloc}")
                    url = next_url
                else:
                    url = ""
                if request_pause_seconds > 0 and (url or chunk_id < len(chunks)):
                    time_module.sleep(request_pause_seconds)
        except MassiveForbiddenError:
            if not skip_forbidden_history:
                raise
            forbidden_chunks += 1
            print(
                f"MASSIVE FORBIDDEN_SKIP chunk={chunk_id}/{len(chunks)} "
                f"start={chunk_start} end={chunk_end} reason=history_entitlement_or_key_access"
            )
            continue

        if len(rows) > chunk_rows_before:
            successful_chunks += 1

    if not rows:
        if forbidden_chunks == len(chunks):
            raise RuntimeError(
                "Massive returned HTTP 403 for every requested chunk. Check MASSIVE_API_KEY and "
                "Stocks plan access. Custom Bars are supported, but historical depth depends on plan."
            )
        raise RuntimeError("Massive returned no SPY intraday aggregates")

    if forbidden_chunks:
        print(
            f"MASSIVE ACCESS_SUMMARY requested_chunks={len(chunks)} "
            f"successful_chunks={successful_chunks} forbidden_chunks={forbidden_chunks}"
        )

    frame = pd.DataFrame(rows).drop_duplicates(subset=["t"], keep="last")
    required = {"t", "o", "h", "l", "c", "v"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Massive response missing fields: {sorted(missing)}")

    ts = pd.to_datetime(frame["t"], unit="ms", utc=True).dt.tz_convert("America/New_York")
    out = pd.DataFrame(
        {
            "timestamp": ts,
            "date": ts.dt.tz_localize(None).dt.normalize(),
            "open": pd.to_numeric(frame["o"], errors="raise"),
            "high": pd.to_numeric(frame["h"], errors="raise"),
            "low": pd.to_numeric(frame["l"], errors="raise"),
            "close": pd.to_numeric(frame["c"], errors="raise"),
            "volume": pd.to_numeric(frame["v"], errors="raise"),
        }
    )
    clock = out["timestamp"].dt.time
    regular = np.array([(t >= time(9, 30)) and (t < time(16, 0)) for t in clock], dtype=bool)
    out = out.loc[regular, CANONICAL_INTRADAY_COLUMNS].sort_values("timestamp").reset_index(drop=True)
    if out.empty:
        raise RuntimeError("Massive data contains no regular-session SPY bars")
    if out["timestamp"].duplicated().any():
        raise ValueError("duplicate intraday timestamps found")
    return out


def aggregate_rth_two_bars(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate each regular session into 2 bars: 09:30-13:30 and 13:30-16:00 ET."""
    if frame.empty:
        raise ValueError("intraday frame is empty")
    work = frame.copy()
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
    out = out[out["date"].isin(complete_dates)].sort_values(["date", "session_bar"]).reset_index(drop=True)
    return out

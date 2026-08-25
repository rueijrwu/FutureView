from __future__ import annotations

import json
import os
from datetime import time
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import urlopen

import numpy as np
import pandas as pd

CANONICAL_INTRADAY_COLUMNS = ["timestamp", "date", "open", "high", "low", "close", "volume"]
MASSIVE_BASE_URL = "https://api.massive.com"


def _request_json(url: str, api_key: str) -> dict:
    separator = "&" if "?" in url else "?"
    if "apiKey=" not in url:
        url = f"{url}{separator}{urlencode({'apiKey': api_key})}"
    with urlopen(url, timeout=60) as response:  # noqa: S310 - fixed Massive host / provider next_url
        return json.loads(response.read().decode("utf-8"))


def download_spy_intraday_massive(
    start: str,
    end: str,
    *,
    api_key: str | None = None,
    base_minutes: int = 30,
) -> pd.DataFrame:
    """Download SPY intraday aggregates from Massive and keep NYSE regular session only.

    The provider endpoint can contain pre/post-market bars, so regular-session filtering
    is performed locally in America/New_York time. A 30-minute base interval is used so
    session-aware 09:30-13:30 and 13:30-16:00 aggregates can be reconstructed exactly.
    """
    key = api_key or os.environ.get("MASSIVE_API_KEY")
    if not key:
        raise RuntimeError("MASSIVE_API_KEY is required for the intraday frequency experiment")
    if base_minutes <= 0:
        raise ValueError("base_minutes must be positive")

    url = (
        f"{MASSIVE_BASE_URL}/v2/aggs/ticker/SPY/range/{base_minutes}/minute/{start}/{end}"
        "?adjusted=false&sort=asc&limit=50000"
    )
    rows: list[dict[str, float | int]] = []
    while url:
        payload = _request_json(url, key)
        status = str(payload.get("status", "")).upper()
        if status not in {"OK", "DELAYED"} and "results" not in payload:
            raise RuntimeError(f"Massive aggregate request failed: status={payload.get('status')} error={payload.get('error')}")
        rows.extend(payload.get("results", []))
        next_url = payload.get("next_url")
        if next_url:
            # Massive next_url may omit apiKey; _request_json adds it. Restrict host.
            parsed = urlparse(next_url)
            if parsed.scheme != "https" or parsed.netloc not in {"api.massive.com", "massive.com", "www.massive.com"}:
                raise RuntimeError(f"unexpected Massive pagination host: {parsed.netloc}")
            url = next_url
        else:
            url = ""

    if not rows:
        raise RuntimeError("Massive returned no SPY intraday aggregates")

    frame = pd.DataFrame(rows)
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
    """Aggregate each regular session into 2 bars: 09:30-13:30 and 13:30-16:00 ET.

    The second bar is 2.5 hours because the U.S. regular session is 6.5 hours. This
    produces exactly two intraday observations per complete session and therefore
    approximately 100 observations over the same 50-session calendar history used by
    the daily baseline.
    """
    if frame.empty:
        raise ValueError("intraday frame is empty")
    work = frame.copy()
    local_time = work["timestamp"].dt.time
    work["session_bar"] = [0 if t < time(13, 30) else 1 for t in local_time]

    rows: list[dict[str, object]] = []
    for (date, session_bar), group in work.groupby(["date", "session_bar"], sort=True):
        group = group.sort_values("timestamp")
        expected = 8 if int(session_bar) == 0 else 5
        # Skip incomplete half-sessions / partial data so every retained day has a
        # comparable regular-session information budget.
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

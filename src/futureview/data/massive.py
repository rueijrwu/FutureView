from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import polars as pl

MASSIVE_BASE_URL = "https://api.massive.com"


class MassiveAPIError(RuntimeError):
    """Raised when Massive returns an unrecoverable API or transport error."""


@dataclass(frozen=True)
class MassiveSettings:
    api_key: str
    base_url: str = MASSIVE_BASE_URL

    @classmethod
    def from_env(cls) -> MassiveSettings:
        api_key = os.getenv("MASSIVE_API_KEY")
        if not api_key:
            raise RuntimeError("Missing MASSIVE_API_KEY environment variable")
        return cls(api_key=api_key)


def empty_daily_frame() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "symbol": pl.String,
            "date": pl.Date,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
        }
    )


def grouped_daily_payload_to_frame(payload: dict[str, object], trading_date: date) -> pl.DataFrame:
    """Normalize Massive grouped daily bars into FutureView's canonical OHLCV schema."""
    raw_results = payload.get("results")
    if not isinstance(raw_results, list) or not raw_results:
        return empty_daily_frame()

    rows: list[dict[str, object]] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        symbol = item.get("T")
        if not symbol:
            continue
        rows.append(
            {
                "symbol": str(symbol),
                "date": trading_date,
                "open": item.get("o"),
                "high": item.get("h"),
                "low": item.get("l"),
                "close": item.get("c"),
                "volume": item.get("v"),
            }
        )

    if not rows:
        return empty_daily_frame()

    return pl.DataFrame(rows).cast(
        {
            "symbol": pl.String,
            "date": pl.Date,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
        },
        strict=False,
    )


class MassiveMarketDataProvider:
    """Massive REST provider optimized for daily U.S. equity research."""

    def __init__(
        self,
        settings: MassiveSettings,
        *,
        timeout_seconds: float = 30.0,
        max_retries: int = 4,
    ) -> None:
        self.settings = settings
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    @classmethod
    def from_env(cls) -> MassiveMarketDataProvider:
        return cls(MassiveSettings.from_env())

    def _get_json(
        self,
        path: str,
        params: dict[str, object] | None = None,
    ) -> dict[str, object]:
        url = f"{self.settings.base_url.rstrip('/')}/{path.lstrip('/')}"
        query_params = dict(params or {})
        query_params["apiKey"] = self.settings.api_key
        url = f"{url}?{urlencode(query_params)}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "FutureView/0.1",
            },
        )

        for attempt in range(self.max_retries):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                    payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise MassiveAPIError("Massive returned a non-object JSON response")
                return payload
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt + 1 < self.max_retries:
                    retry_after = exc.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 15.0 * (attempt + 1)
                    time.sleep(delay)
                    continue
                raise MassiveAPIError(f"Massive HTTP {exc.code}: {body[:500]}") from exc
            except URLError as exc:
                if attempt + 1 < self.max_retries:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise MassiveAPIError(f"Massive transport error: {exc.reason}") from exc

        raise MassiveAPIError("Massive request failed after retries")

    def fetch_grouped_daily(self, trading_date: date) -> pl.DataFrame:
        payload = self._get_json(
            f"/v2/aggs/grouped/locale/us/market/stocks/{trading_date.isoformat()}",
            {"adjusted": "true"},
        )
        status = payload.get("status")
        if status not in (None, "OK"):
            raise MassiveAPIError(f"Massive returned status {status!r}")
        return grouped_daily_payload_to_frame(payload, trading_date)

    def fetch_latest_available_daily(
        self,
        on_or_before: date,
        *,
        lookback_days: int = 7,
    ) -> pl.DataFrame:
        """Find the most recent non-empty U.S. stock session on or before a date."""
        for offset in range(lookback_days + 1):
            candidate = on_or_before - timedelta(days=offset)
            if candidate.weekday() >= 5:
                continue
            frame = self.fetch_grouped_daily(candidate)
            if not frame.is_empty():
                return frame
        raise MassiveAPIError(
            f"No grouped daily market data found on or before {on_or_before} "
            f"within {lookback_days} days"
        )

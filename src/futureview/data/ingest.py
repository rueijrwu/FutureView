from __future__ import annotations

import argparse
import io
import json
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from futureview.data.massive import MassiveMarketDataProvider
from futureview.storage.r2 import R2Store

NEW_YORK = ZoneInfo("America/New_York")


def _frame_date(frame: pl.DataFrame) -> date:
    value = frame.select(pl.col("date").first()).item()
    if not isinstance(value, date):
        raise TypeError("daily frame did not contain a valid date")
    return value


def _write_daily_frame(store: R2Store, frame: pl.DataFrame) -> str:
    trading_date = _frame_date(frame)
    buffer = io.BytesIO()
    frame.write_parquet(buffer, compression="zstd")
    key = f"prices/daily/date={trading_date.isoformat()}/bars.parquet"
    store.put_bytes(key, buffer.getvalue(), content_type="application/vnd.apache.parquet")

    metadata = {
        "provider": "massive",
        "date": trading_date.isoformat(),
        "rows": frame.height,
        "updated_at": datetime.now(tz=NEW_YORK).isoformat(),
        "object_key": key,
    }
    store.put_bytes(
        "metadata/latest-market-data.json",
        json.dumps(metadata, indent=2).encode("utf-8"),
        content_type="application/json",
    )
    return key


def ingest_daily(on_or_before: date | None = None) -> tuple[date, int, str]:
    provider = MassiveMarketDataProvider.from_env()
    store = R2Store.from_env()
    target = on_or_before or datetime.now(tz=NEW_YORK).date()
    frame = provider.fetch_latest_available_daily(target)
    key = _write_daily_frame(store, frame)
    return _frame_date(frame), frame.height, key


def ingest_bootstrap(*, end: date | None = None, calendar_days: int = 420) -> int:
    """Backfill enough calendar history for SMA200/RS60 research.

    Massive Basic is rate limited, so requests are deliberately spaced. Empty
    holiday sessions are ignored. Existing R2 objects are safely overwritten.
    """
    provider = MassiveMarketDataProvider.from_env()
    store = R2Store.from_env()
    end_date = end or datetime.now(tz=NEW_YORK).date()
    start_date = end_date - timedelta(days=calendar_days - 1)
    written = 0

    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            frame = provider.fetch_grouped_daily(current)
            if not frame.is_empty():
                key = _write_daily_frame(store, frame)
                print(f"stored {current}: {frame.height} rows -> {key}", flush=True)
                written += 1
            else:
                print(f"no market data for {current}", flush=True)
            if current < end_date:
                time.sleep(13.0)
        current += timedelta(days=1)

    return written


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest Massive daily U.S. stock data into R2")
    parser.add_argument("--mode", choices=("daily", "bootstrap"), default="daily")
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--calendar-days", type=int, default=420)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.mode == "daily":
        trading_date, rows, key = ingest_daily(args.date)
        print(f"stored {trading_date}: {rows} rows -> {key}")
        return

    written = ingest_bootstrap(end=args.date, calendar_days=args.calendar_days)
    print(f"bootstrap complete: {written} trading sessions stored")


if __name__ == "__main__":
    main()

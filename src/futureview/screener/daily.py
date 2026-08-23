from __future__ import annotations

import io
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from futureview.config import load_strategy_config
from futureview.dashboard.export import write_dashboard_snapshot
from futureview.data.massive import MassiveMarketDataProvider
from futureview.screener.pipeline import build_ranking_history, top_n_for_date
from futureview.storage.r2 import R2Store

NEW_YORK = ZoneInfo("America/New_York")
PRICE_PREFIX = "prices/daily/date="
PRICE_SUFFIX = "/bars.parquet"
DASHBOARD_KEY = "dashboard/latest.json"


def _price_keys(store: R2Store) -> list[str]:
    return [
        key
        for key in store.list_keys("prices/daily/")
        if key.startswith(PRICE_PREFIX) and key.endswith(PRICE_SUFFIX)
    ]


def _load_price_history(store: R2Store, *, max_sessions: int = 320) -> pl.DataFrame:
    keys = _price_keys(store)
    if not keys:
        raise RuntimeError("No daily market data found in R2. Run Market Data Ingest first.")

    selected = keys[-max_sessions:]
    frames = [pl.read_parquet(io.BytesIO(store.get_bytes(key))) for key in selected]
    history = pl.concat(frames, how="vertical_relaxed").sort(["symbol", "date"])

    session_count = history.select(pl.col("date").n_unique()).item()
    if session_count < 210:
        raise RuntimeError(
            f"Only {session_count} trading sessions are available; at least 210 are required "
            "for SMA200-based screening. Run Market Data Ingest in bootstrap mode first."
        )
    return history


def _with_rank_changes(ranking_history: pl.DataFrame, latest: pl.DataFrame) -> pl.DataFrame:
    dates = (
        ranking_history.select("date")
        .unique()
        .sort("date")
        .get_column("date")
        .to_list()
    )
    latest_date = dates[-1]
    out = latest

    for sessions, output_column in ((5, "rank_change_5d"), (20, "rank_change_20d")):
        if len(dates) <= sessions:
            out = out.with_columns(pl.lit(None, dtype=pl.Int32).alias(output_column))
            continue
        prior_date = dates[-(sessions + 1)]
        prior = (
            ranking_history.filter(pl.col("date") == prior_date)
            .select("symbol", pl.col("rank").alias("prior_rank"))
        )
        out = (
            out.join(prior, on="symbol", how="left")
            .with_columns(
                (pl.col("prior_rank") - pl.col("rank"))
                .cast(pl.Int32)
                .alias(output_column)
            )
            .drop("prior_rank")
        )

    return out.with_columns(pl.lit(latest_date).alias("date"))


def _write_parquet(store: R2Store, frame: pl.DataFrame, key: str) -> None:
    buffer = io.BytesIO()
    frame.write_parquet(buffer, compression="zstd")
    store.put_bytes(key, buffer.getvalue(), content_type="application/vnd.apache.parquet")


def run_daily_scanner(
    *,
    config_path: str | Path = "config/strategy.yaml",
    dashboard_path: str | Path = "site/data/latest.json",
) -> tuple[date, int, int]:
    store = R2Store.from_env()
    prices = _load_price_history(store)
    config = load_strategy_config(config_path)
    provider = MassiveMarketDataProvider.from_env()
    common_stock_symbols = provider.fetch_active_common_stock_symbols()

    ranking_history = build_ranking_history(
        prices,
        config,
        eligible_symbols=common_stock_symbols,
    )
    if ranking_history.is_empty():
        raise RuntimeError("No common stocks passed the configured hard filters.")

    latest_date = ranking_history.select(pl.col("date").max()).item()
    if not isinstance(latest_date, date):
        raise TypeError("ranking history did not contain a valid latest date")

    latest_all = ranking_history.filter(pl.col("date") == latest_date).sort("rank")
    latest_all = _with_rank_changes(ranking_history, latest_all)
    top50 = top_n_for_date(latest_all, top_n=config.screener.top_n, as_of=latest_date)

    ranking_key = f"rankings/date={latest_date.isoformat()}/ranking.parquet"
    top_key = f"rankings/date={latest_date.isoformat()}/top50.parquet"
    _write_parquet(store, latest_all, ranking_key)
    _write_parquet(store, top50, top_key)

    latest_prices = prices.filter(pl.col("date") == latest_date)
    universe_count = latest_prices.filter(
        pl.col("symbol").is_in(sorted(common_stock_symbols))
    ).height
    dashboard_file = write_dashboard_snapshot(
        top50,
        dashboard_path,
        as_of=latest_date,
        universe_count=universe_count,
        market_regime="Research",
        cash_posture="Rule-based",
        top_n=config.screener.top_n,
    )
    store.put_bytes(
        DASHBOARD_KEY,
        dashboard_file.read_bytes(),
        content_type="application/json",
    )

    metadata = {
        "date": latest_date.isoformat(),
        "universe": "active_common_stocks",
        "universe_count": universe_count,
        "ranked_count": latest_all.height,
        "top_count": top50.height,
        "ranking_key": ranking_key,
        "top_key": top_key,
        "dashboard_key": DASHBOARD_KEY,
        "updated_at": datetime.now(tz=NEW_YORK).isoformat(),
    }
    store.put_bytes(
        "metadata/latest-ranking.json",
        json.dumps(metadata, indent=2).encode("utf-8"),
        content_type="application/json",
    )
    return latest_date, latest_all.height, top50.height


def main() -> None:
    trading_date, ranked_count, top_count = run_daily_scanner()
    print(
        f"scanner complete for {trading_date}: "
        f"{ranked_count} ranked common stocks, {top_count} dashboard rows"
    )


if __name__ == "__main__":
    main()

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
from futureview.features.incremental import (
    STATE_SHARDS,
    STATE_VERSION,
    bootstrap_states,
    state_shard,
)
from futureview.screener.pipeline import build_ranking_history, top_n_for_date
from futureview.storage.r2 import R2Store

NEW_YORK = ZoneInfo("America/New_York")
PARQUET_PRICE_PREFIX = "prices/daily/date="
PARQUET_PRICE_SUFFIX = "/bars.parquet"
JSON_PRICE_PREFIX = "prices/daily-json/date="
JSON_PRICE_SUFFIX = "/bars.json"
DASHBOARD_KEY = "dashboard/latest.json"
STATE_PREFIX = f"state/rolling/v{STATE_VERSION}"


def _price_keys(store: R2Store, prefix: str, suffix: str) -> list[str]:
    return [
        key
        for key in store.list_keys(prefix.rsplit("date=", 1)[0])
        if key.startswith(prefix) and key.endswith(suffix)
    ]


def _load_cloudflare_json_frame(store: R2Store, key: str) -> pl.DataFrame:
    payload = json.loads(store.get_bytes(key))
    bars = payload.get("bars", [])
    if not bars:
        return pl.DataFrame()

    return (
        pl.DataFrame(bars)
        .select("symbol", "date", "open", "high", "low", "close", "volume")
        .with_columns(
            pl.col("symbol").cast(pl.Utf8),
            pl.col("date").str.strptime(pl.Date, "%Y-%m-%d", strict=True),
            pl.col("open").cast(pl.Float64),
            pl.col("high").cast(pl.Float64),
            pl.col("low").cast(pl.Float64),
            pl.col("close").cast(pl.Float64),
            pl.col("volume").cast(pl.Float64),
        )
    )


def _load_price_history(store: R2Store, *, max_sessions: int = 320) -> pl.DataFrame:
    parquet_keys = _price_keys(store, PARQUET_PRICE_PREFIX, PARQUET_PRICE_SUFFIX)
    json_keys = _price_keys(store, JSON_PRICE_PREFIX, JSON_PRICE_SUFFIX)
    if not parquet_keys and not json_keys:
        raise RuntimeError("No daily market data found in R2.")

    frames: list[pl.DataFrame] = []
    for key in parquet_keys[-max_sessions:]:
        frames.append(pl.read_parquet(io.BytesIO(store.get_bytes(key))))
    for key in json_keys[-max_sessions:]:
        frame = _load_cloudflare_json_frame(store, key)
        if not frame.is_empty():
            frames.append(frame)

    history = pl.concat(frames, how="vertical_relaxed")
    history = history.unique(subset=["symbol", "date"], keep="last")

    dates = history.select("date").unique().sort("date").get_column("date").to_list()
    selected_dates = dates[-max_sessions:]
    history = history.filter(pl.col("date").is_in(selected_dates)).sort(["symbol", "date"])

    session_count = len(selected_dates)
    if session_count < 210:
        raise RuntimeError(
            f"Only {session_count} trading sessions are available; at least 210 are required "
            "for SMA200-based screening."
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


def _write_incremental_state(store: R2Store, prices: pl.DataFrame, as_of: date) -> dict[str, object]:
    states = bootstrap_states(prices)
    shards: list[list[dict[str, object]]] = [[] for _ in range(STATE_SHARDS)]
    for symbol, state in sorted(states.items()):
        shards[state_shard(symbol)].append(state.to_dict())

    keys: list[str] = []
    for shard_id, records in enumerate(shards):
        key = f"{STATE_PREFIX}/shard={shard_id:02d}.json"
        payload = {
            "version": STATE_VERSION,
            "as_of": as_of.isoformat(),
            "shard": shard_id,
            "shard_count": STATE_SHARDS,
            "count": len(records),
            "states": records,
        }
        store.put_bytes(
            key,
            json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            content_type="application/json",
        )
        keys.append(key)

    metadata: dict[str, object] = {
        "version": STATE_VERSION,
        "as_of": as_of.isoformat(),
        "shard_count": STATE_SHARDS,
        "symbol_count": len(states),
        "prefix": STATE_PREFIX,
        "keys": keys,
        "updated_at": datetime.now(tz=NEW_YORK).isoformat(),
    }
    store.put_bytes(
        f"{STATE_PREFIX}/metadata.json",
        json.dumps(metadata, indent=2).encode("utf-8"),
        content_type="application/json",
    )
    store.put_bytes(
        "metadata/latest-feature-state.json",
        json.dumps(metadata, indent=2).encode("utf-8"),
        content_type="application/json",
    )
    return metadata


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

    state_metadata = _write_incremental_state(store, prices, latest_date)

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
        "market_data_sources": ["r2_parquet_history", "cloudflare_daily_json"],
        "feature_state": {
            "version": state_metadata["version"],
            "prefix": state_metadata["prefix"],
            "shard_count": state_metadata["shard_count"],
            "symbol_count": state_metadata["symbol_count"],
        },
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

from __future__ import annotations

import argparse
import json
from datetime import date

import polars as pl

from futureview.config import load_strategy_config
from futureview.features.incremental import bootstrap_states
from futureview.screener.daily import _load_price_history, _with_rank_changes
from futureview.screener.incremental_ranking import (
    RANKING_STATE_SHARDS,
    RANKING_STATE_VERSION,
    bootstrap_ranking_states,
    ranking_state_shard,
)
from futureview.screener.pipeline import build_ranking_history
from futureview.storage.r2 import R2Store

LATEST_COMMON_STOCK_UNIVERSE_KEY = "metadata/latest-common-stock-universe.json"


def _write_json(store: R2Store, key: str, payload: object) -> None:
    store.put_bytes(
        key,
        json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8"),
        content_type="application/json",
    )


def _read_json(store: R2Store, key: str) -> dict[str, object]:
    return json.loads(store.get_bytes(key))


def prepare_ranking_replay(target_date: date) -> dict[str, object]:
    store = R2Store.from_env()
    prices = _load_price_history(store)
    source_prices = prices.filter(pl.col("date") < target_date)
    target_prices = prices.filter(pl.col("date") <= target_date)
    source_as_of = source_prices.select(pl.col("date").max()).item()
    if not isinstance(source_as_of, date):
        raise RuntimeError("unable to resolve ranking replay source date")

    universe_metadata = _read_json(store, LATEST_COMMON_STOCK_UNIVERSE_KEY)
    universe_payload = _read_json(store, str(universe_metadata["data_key"]))
    universe_symbols = {str(symbol) for symbol in universe_payload.get("symbols", [])}

    feature_state_symbols = set(bootstrap_states(source_prices))
    eligible_symbols = universe_symbols.intersection(feature_state_symbols)
    if not eligible_symbols:
        raise RuntimeError("ranking replay has no eligible symbols")

    config = load_strategy_config("config/strategy.yaml")
    source_ranking = build_ranking_history(
        source_prices,
        config,
        eligible_symbols=eligible_symbols,
    )
    target_ranking = build_ranking_history(
        target_prices,
        config,
        eligible_symbols=eligible_symbols,
    )
    if source_ranking.is_empty() or target_ranking.is_empty():
        raise RuntimeError("ranking replay batch reference is empty")

    root = f"validation/replay/date={target_date.isoformat()}"
    state_prefix = f"{root}/source-ranking-state"
    states = bootstrap_ranking_states(source_ranking, as_of=source_as_of)
    shards: list[list[dict[str, object]]] = [[] for _ in range(RANKING_STATE_SHARDS)]
    for symbol, state in sorted(states.items()):
        shards[ranking_state_shard(symbol)].append(state.to_dict())

    state_keys: list[str] = []
    for shard_id, records in enumerate(shards):
        key = f"{state_prefix}/shard={shard_id:02d}.json"
        _write_json(
            store,
            key,
            {
                "version": RANKING_STATE_VERSION,
                "as_of": source_as_of.isoformat(),
                "shard": shard_id,
                "shard_count": RANKING_STATE_SHARDS,
                "count": len(records),
                "states": records,
            },
        )
        state_keys.append(key)

    prior_session_count = min(
        source_ranking.select("date").unique().height,
        20,
    )
    state_metadata_key = f"{state_prefix}/metadata.json"
    state_metadata = {
        "version": RANKING_STATE_VERSION,
        "as_of": source_as_of.isoformat(),
        "shard_count": RANKING_STATE_SHARDS,
        "symbol_count": len(states),
        "prior_session_count": prior_session_count,
        "prefix": state_prefix,
        "keys": state_keys,
        "producer": "python-ranking-replay-bootstrap",
    }
    _write_json(store, state_metadata_key, state_metadata)

    latest = target_ranking.filter(pl.col("date") == target_date).sort("rank")
    latest = _with_rank_changes(target_ranking, latest)
    reference_key = f"{root}/reference/ranking.json"
    _write_json(
        store,
        reference_key,
        {
            "date": target_date.isoformat(),
            "count": latest.height,
            "rankings": latest.to_dicts(),
            "producer": "python-batch-reference",
        },
    )

    universe_key = f"{root}/input/common-stocks.json"
    _write_json(
        store,
        universe_key,
        {
            "as_of": target_date.isoformat(),
            "count": len(eligible_symbols),
            "symbols": sorted(eligible_symbols),
            "source": "latest-common-stock-universe-intersect-feature-state",
            "producer": "python-ranking-replay-bootstrap",
        },
    )

    metadata = {
        "target_date": target_date.isoformat(),
        "source_as_of": source_as_of.isoformat(),
        "ranking_state_metadata_key": state_metadata_key,
        "ranking_reference_key": reference_key,
        "universe_key": universe_key,
        "eligible_symbol_count": len(eligible_symbols),
        "root": root,
    }
    _write_json(store, f"{root}/ranking-metadata.json", metadata)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    result = prepare_ranking_replay(date.fromisoformat(args.date))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

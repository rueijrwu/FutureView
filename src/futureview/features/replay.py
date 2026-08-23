from __future__ import annotations

import argparse
import json
from datetime import date

import polars as pl

from futureview.config import load_strategy_config
from futureview.features.incremental import STATE_SHARDS, STATE_VERSION, bootstrap_states, state_shard
from futureview.screener.daily import _load_price_history
from futureview.screener.pipeline import build_feature_history
from futureview.storage.r2 import R2Store


def _write_json(store: R2Store, key: str, payload: object) -> None:
    store.put_bytes(
        key,
        json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        content_type="application/json",
    )


def prepare_historical_replay(target_date: date) -> dict[str, object]:
    store = R2Store.from_env()
    prices = _load_price_history(store)
    source_prices = prices.filter(pl.col("date") < target_date)
    target_prices = prices.filter(pl.col("date") <= target_date)
    source_as_of = source_prices.select(pl.col("date").max()).item()
    if not isinstance(source_as_of, date):
        raise RuntimeError("unable to resolve replay source date")

    states = bootstrap_states(source_prices)
    root = f"validation/replay/date={target_date.isoformat()}"
    state_prefix = f"{root}/source-state"
    state_shards: list[list[dict[str, object]]] = [[] for _ in range(STATE_SHARDS)]
    for symbol, state in sorted(states.items()):
        state_shards[state_shard(symbol)].append(state.to_dict())

    state_keys: list[str] = []
    for shard_id, records in enumerate(state_shards):
        key = f"{state_prefix}/shard={shard_id:02d}.json"
        _write_json(
            store,
            key,
            {
                "version": STATE_VERSION,
                "as_of": source_as_of.isoformat(),
                "shard": shard_id,
                "shard_count": STATE_SHARDS,
                "count": len(records),
                "states": records,
            },
        )
        state_keys.append(key)

    state_metadata = {
        "version": STATE_VERSION,
        "as_of": source_as_of.isoformat(),
        "shard_count": STATE_SHARDS,
        "symbol_count": len(states),
        "prefix": state_prefix,
        "keys": state_keys,
        "producer": "python-replay-bootstrap",
    }
    state_metadata_key = f"{state_prefix}/metadata.json"
    _write_json(store, state_metadata_key, state_metadata)

    config = load_strategy_config("config/strategy.yaml")
    batch = build_feature_history(target_prices, config).filter(pl.col("date") == target_date)
    reference = {row["symbol"]: row for row in batch.to_dicts()}
    reference_key = f"{root}/reference/features.json"
    _write_json(
        store,
        reference_key,
        {
            "date": target_date.isoformat(),
            "count": len(reference),
            "features": reference,
            "producer": "python-batch-reference",
        },
    )

    metadata = {
        "target_date": target_date.isoformat(),
        "source_as_of": source_as_of.isoformat(),
        "state_metadata_key": state_metadata_key,
        "reference_key": reference_key,
        "root": root,
    }
    _write_json(store, f"{root}/metadata.json", metadata)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    target_date = date.fromisoformat(args.date)
    metadata = prepare_historical_replay(target_date)
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()

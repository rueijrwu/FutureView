from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import polars as pl

from futureview.screener.incremental_ranking import (
    RANKING_STATE_SHARDS,
    RANKING_STATE_VERSION,
    bootstrap_ranking_states,
    ranking_state_shard,
)
from futureview.storage.r2 import R2Store

NEW_YORK = ZoneInfo("America/New_York")
LATEST_RANKING_STATE_KEY = "metadata/latest-ranking-state.json"


def publish_ranking_state(
    store: R2Store,
    ranking_history: pl.DataFrame,
    *,
    as_of: date,
) -> dict[str, object]:
    """Publish immutable sharded ranking state and atomically advance its pointer."""
    states = bootstrap_ranking_states(ranking_history, as_of=as_of)
    shards: list[list[dict[str, object]]] = [[] for _ in range(RANKING_STATE_SHARDS)]
    for symbol, state in sorted(states.items()):
        shards[ranking_state_shard(symbol)].append(state.to_dict())

    prefix = f"state/ranking/v{RANKING_STATE_VERSION}/date={as_of.isoformat()}"
    keys: list[str] = []
    for shard_id, records in enumerate(shards):
        key = f"{prefix}/shard={shard_id:02d}.json"
        payload = {
            "version": RANKING_STATE_VERSION,
            "as_of": as_of.isoformat(),
            "shard": shard_id,
            "shard_count": RANKING_STATE_SHARDS,
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
        "version": RANKING_STATE_VERSION,
        "as_of": as_of.isoformat(),
        "shard_count": RANKING_STATE_SHARDS,
        "symbol_count": len(states),
        "prefix": prefix,
        "keys": keys,
        "producer": "python-batch-reference",
        "updated_at": datetime.now(tz=NEW_YORK).isoformat(),
    }
    store.put_bytes(
        f"{prefix}/metadata.json",
        json.dumps(metadata, indent=2).encode("utf-8"),
        content_type="application/json",
    )
    store.put_bytes(
        LATEST_RANKING_STATE_KEY,
        json.dumps(metadata, indent=2).encode("utf-8"),
        content_type="application/json",
    )
    return metadata

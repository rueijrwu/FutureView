from __future__ import annotations

import argparse
import json
import math
import time
from datetime import date

import polars as pl

from futureview.data.massive import MassiveMarketDataProvider
from futureview.features.core import add_core_features
from futureview.features.incremental import (
    STATE_SHARDS,
    STATE_VERSION,
    bootstrap_states,
    state_shard,
)
from futureview.screener.daily import _load_price_history
from futureview.storage.r2 import R2Store

COMPARE_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "sma5",
    "sma10",
    "sma20",
    "sma50",
    "sma200",
    "avg_volume20",
    "return20",
    "return60",
    "high20_prior",
    "high50_prior",
    "true_range",
    "atr14",
    "avg_dollar_volume20",
    "volume_ratio20",
    "sma50_slope10",
    "extension_atr",
    "distance_from_high20",
)
BOOLEAN_COLUMNS = ("breakout20", "breakout50")


def _write_json(store: R2Store, key: str, payload: object) -> None:
    store.put_bytes(
        key,
        json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8"),
        content_type="application/json",
    )


def _read_json(store: R2Store, key: str) -> dict[str, object]:
    return json.loads(store.get_bytes(key))


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

    batch = add_core_features(target_prices).filter(pl.col("date") == target_date)
    reference = {str(row["symbol"]): row for row in batch.to_dicts()}
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

    provider = MassiveMarketDataProvider.from_env()
    bars = provider.fetch_grouped_daily(target_date)
    if bars.is_empty():
        raise RuntimeError(f"Massive returned no grouped-daily bars for {target_date}")
    bars_key = f"{root}/input/bars.json"
    _write_json(
        store,
        bars_key,
        {
            "date": target_date.isoformat(),
            "adjusted": True,
            "source": "massive",
            "producer": "historical-replay",
            "count": bars.height,
            "bars": bars.to_dicts(),
        },
    )

    metadata = {
        "target_date": target_date.isoformat(),
        "source_as_of": source_as_of.isoformat(),
        "state_metadata_key": state_metadata_key,
        "reference_key": reference_key,
        "bars_key": bars_key,
        "root": root,
    }
    _write_json(store, f"{root}/metadata.json", metadata)
    return metadata


def compare_historical_replay(
    target_date: date,
    *,
    timeout_seconds: int = 300,
    atol: float = 1e-10,
    rtol: float = 1e-10,
) -> dict[str, object]:
    store = R2Store.from_env()
    root = f"validation/replay/date={target_date.isoformat()}"
    cloudflare_metadata_key = f"{root}/cloudflare/metadata.json"
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            cloudflare_metadata = _read_json(store, cloudflare_metadata_key)
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise RuntimeError("timed out waiting for Cloudflare replay output") from None
            time.sleep(5)

    reference_payload = _read_json(store, f"{root}/reference/features.json")
    reference = reference_payload.get("features", {})
    if not isinstance(reference, dict):
        raise RuntimeError("invalid replay reference payload")

    actual: dict[str, dict[str, object]] = {}
    for key in cloudflare_metadata.get("feature_keys", []):
        payload = _read_json(store, str(key))
        for row in payload.get("features", []):
            if isinstance(row, dict) and row.get("symbol"):
                actual[str(row["symbol"])] = row

    common = sorted(set(reference).intersection(actual))
    mismatches: list[dict[str, object]] = []
    max_abs_error = 0.0
    for symbol in common:
        expected_row = reference[symbol]
        actual_row = actual[symbol]
        if not isinstance(expected_row, dict):
            continue
        for column in COMPARE_COLUMNS:
            expected = expected_row.get(column)
            observed = actual_row.get(column)
            if expected is None and observed is None:
                continue
            if expected is None or observed is None:
                mismatches.append(
                    {"symbol": symbol, "column": column, "expected": expected, "actual": observed}
                )
                continue
            expected_f = float(expected)
            observed_f = float(observed)
            error = abs(expected_f - observed_f)
            max_abs_error = max(max_abs_error, error)
            if not math.isclose(expected_f, observed_f, rel_tol=rtol, abs_tol=atol):
                mismatches.append(
                    {
                        "symbol": symbol,
                        "column": column,
                        "expected": expected_f,
                        "actual": observed_f,
                        "abs_error": error,
                    }
                )
        for column in BOOLEAN_COLUMNS:
            if bool(expected_row.get(column)) != bool(actual_row.get(column)):
                mismatches.append(
                    {
                        "symbol": symbol,
                        "column": column,
                        "expected": expected_row.get(column),
                        "actual": actual_row.get(column),
                    }
                )

    result = {
        "date": target_date.isoformat(),
        "reference_count": len(reference),
        "cloudflare_count": len(actual),
        "compared_symbol_count": len(common),
        "mismatch_count": len(mismatches),
        "max_abs_error": max_abs_error,
        "status": "pass" if not mismatches else "fail",
        "sample_mismatches": mismatches[:20],
    }
    _write_json(store, f"{root}/comparison.json", result)
    if mismatches:
        raise RuntimeError(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "compare"))
    parser.add_argument("--date", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    target_date = date.fromisoformat(args.date)
    if args.command == "prepare":
        result = prepare_historical_replay(target_date)
    else:
        result = compare_historical_replay(target_date, timeout_seconds=args.timeout)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import math
import time
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

NUMERIC_COMPARE_COLUMNS = (
    "rs20",
    "rs60",
    "rs20_rank",
    "rs60_rank",
    "volume_rank",
    "trend_score",
    "breakout_score",
    "base_score",
    "persistence_score",
    "extension_penalty",
    "stock_score",
)
INTEGER_COMPARE_COLUMNS = (
    "base_rank",
    "rank",
    "rank_change_5d",
    "rank_change_20d",
)


def _write_json(store: R2Store, key: str, payload: object) -> None:
    store.put_bytes(
        key,
        json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8"),
        content_type="application/json",
    )


def _read_json(store: R2Store, key: str) -> dict[str, object]:
    return json.loads(store.get_bytes(key))


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError):
        return False


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


def compare_ranking_replay(
    target_date: date,
    *,
    timeout_seconds: int = 300,
    atol: float = 1e-10,
    rtol: float = 1e-10,
) -> dict[str, object]:
    store = R2Store.from_env()
    root = f"validation/replay/date={target_date.isoformat()}"
    metadata_key = f"{root}/cloudflare/ranking/metadata.json"
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            cloudflare_metadata = _read_json(store, metadata_key)
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise RuntimeError("timed out waiting for Cloudflare ranking replay output") from None
            time.sleep(5)

    ranking_metadata = _read_json(store, f"{root}/ranking-metadata.json")
    reference_payload = _read_json(store, str(ranking_metadata["ranking_reference_key"]))
    actual_payload = _read_json(store, str(cloudflare_metadata["ranking_key"]))

    reference_rows = reference_payload.get("rankings", [])
    actual_rows = actual_payload.get("rankings", [])
    if not isinstance(reference_rows, list) or not isinstance(actual_rows, list):
        raise RuntimeError("invalid ranking replay payload")

    reference = {
        str(row["symbol"]): row
        for row in reference_rows
        if isinstance(row, dict) and row.get("symbol")
    }
    actual = {
        str(row["symbol"]): row
        for row in actual_rows
        if isinstance(row, dict) and row.get("symbol")
    }

    reference_symbols = set(reference)
    actual_symbols = set(actual)
    missing_symbols = sorted(reference_symbols - actual_symbols)
    unexpected_symbols = sorted(actual_symbols - reference_symbols)
    common = sorted(reference_symbols.intersection(actual_symbols))

    mismatches: list[dict[str, object]] = []
    max_abs_error = 0.0
    for symbol in common:
        expected_row = reference[symbol]
        observed_row = actual[symbol]
        for column in NUMERIC_COMPARE_COLUMNS:
            expected = expected_row.get(column)
            observed = observed_row.get(column)
            expected_missing = _is_missing(expected)
            observed_missing = _is_missing(observed)
            if expected_missing and observed_missing:
                continue
            if expected_missing != observed_missing:
                mismatches.append(
                    {
                        "symbol": symbol,
                        "column": column,
                        "expected": expected,
                        "actual": observed,
                    }
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

        for column in INTEGER_COMPARE_COLUMNS:
            expected = expected_row.get(column)
            observed = observed_row.get(column)
            if expected is None and observed is None:
                continue
            if expected is None or observed is None or int(expected) != int(observed):
                mismatches.append(
                    {
                        "symbol": symbol,
                        "column": column,
                        "expected": expected,
                        "actual": observed,
                    }
                )

    reference_top50 = [
        str(row["symbol"])
        for row in sorted(reference_rows, key=lambda row: int(row["rank"]))
        if int(row["rank"]) <= 50
    ]
    actual_top50 = [
        str(row["symbol"])
        for row in sorted(actual_rows, key=lambda row: int(row["rank"]))
        if int(row["rank"]) <= 50
    ]
    top50_ok = reference_top50 == actual_top50

    coverage_ok = not missing_symbols and not unexpected_symbols
    parity_ok = not mismatches
    result = {
        "date": target_date.isoformat(),
        "reference_candidate_count": len(reference),
        "cloudflare_candidate_count": len(actual),
        "compared_symbol_count": len(common),
        "missing_symbol_count": len(missing_symbols),
        "unexpected_symbol_count": len(unexpected_symbols),
        "mismatch_count": len(mismatches),
        "max_abs_error": max_abs_error,
        "coverage_status": "pass" if coverage_ok else "fail",
        "parity_status": "pass" if parity_ok else "fail",
        "top50_status": "pass" if top50_ok else "fail",
        "status": "pass" if coverage_ok and parity_ok and top50_ok else "fail",
        "sample_missing_symbols": missing_symbols[:20],
        "sample_unexpected_symbols": unexpected_symbols[:20],
        "sample_mismatches": mismatches[:20],
        "reference_top50": reference_top50,
        "cloudflare_top50": actual_top50,
    }
    _write_json(store, f"{root}/ranking-comparison.json", result)
    if result["status"] != "pass":
        raise RuntimeError(json.dumps(result, indent=2))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    target_date = date.fromisoformat(args.date)
    if args.compare:
        result = compare_ranking_replay(target_date, timeout_seconds=args.timeout)
    else:
        result = prepare_ranking_replay(target_date)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

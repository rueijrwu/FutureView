from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd

from futureview_replay.cloud_export import export_cloud


def test_cloud_manifest_contains_runtime_selection_inputs(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    parquet = runtime / "parquet" / "1m"
    parquet.mkdir(parents=True)
    rows = []
    volumes = {
        "2024-06-10T14:30:00Z": {"MESM24": 100, "MESU24": 10},
        "2024-06-11T14:30:00Z": {"MESM24": 80, "MESU24": 120},
        "2024-06-12T14:30:00Z": {"MESM24": 20, "MESU24": 200},
    }
    for timestamp, contract_volumes in volumes.items():
        for contract, volume in contract_volumes.items():
            rows.append({
                "timestamp": timestamp,
                "symbol": contract,
                "open": 5000,
                "high": 5001,
                "low": 4999,
                "close": 5000.5,
                "volume": volume,
            })
    path = parquet / "test.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    (runtime / "manifest.json").write_text(json.dumps({
        "dataset": "test",
        "product": "MES",
        "files": [{"one_minute": "parquet/1m/test.parquet", "symbols": ["MESM24", "MESU24"]}],
    }), encoding="utf-8")

    output = tmp_path / "cloud"
    result = export_cloud(runtime, output)
    manifest = json.loads(result.read_text(encoding="utf-8"))
    assert manifest["version"] == 7
    assert manifest["resolution"] == "1m"
    assert manifest["supported_display_resolutions"] == ["1", "5", "30", "240", "1D"]
    assert manifest["native_display_resolutions"] == ["1", "5", "30", "240", "1D"]
    assert manifest["intraday_multipliers"] == ["1", "5", "30", "240"]
    assert manifest["daily_multipliers"] == ["1"]
    assert manifest["display_cache"] == {
        "strategy": "rolling_precomputed_windows",
        "window_bars": 512,
        "prefetch_threshold": 0.75,
        "partial_bar_source": "released_1m_only",
    }
    assert manifest["roll_rule"] == "runtime_prior_session_max_volume"

    selection = manifest["contract_selection"]
    assert selection["rule"] == "runtime_prior_session_max_volume"
    assert selection["expiry_cutoff_et"] == "09:30"
    assert selection["sessions"] == ["2024-06-10", "2024-06-11", "2024-06-12"]
    assert selection["session_volumes"]["2024-06-11"]["MESU24"] == 120.0

    contract = manifest["contracts"]["MESM24"]
    for resolution in ["1", "5", "30", "240", "1D"]:
        assert contract["display_shards"][resolution]
    assert contract["display_shards"]["5"][0]["window"] == 0
    assert contract["display_shards"]["5"][0]["offset"] == 0

    daily_meta = contract["display_shards"]["1D"][0]
    with gzip.open(output / daily_meta["key"], "rt", encoding="utf-8") as f:
        daily = json.load(f)
    assert [bar["t"] for bar in daily] == [
        int(pd.Timestamp("2024-06-10T00:00:00Z").timestamp()),
        int(pd.Timestamp("2024-06-11T00:00:00Z").timestamp()),
        int(pd.Timestamp("2024-06-12T00:00:00Z").timestamp()),
    ]


def test_intraday_display_bars_are_session_aligned(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    parquet = runtime / "parquet" / "1m"
    parquet.mkdir(parents=True)
    timestamps = pd.date_range("2024-06-10T22:00:00Z", periods=7, freq="min")
    rows = [{
        "timestamp": ts,
        "symbol": "MESM24",
        "open": 5000 + i,
        "high": 5001 + i,
        "low": 4999 + i,
        "close": 5000.5 + i,
        "volume": 10 + i,
    } for i, ts in enumerate(timestamps)]
    path = parquet / "test.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    (runtime / "manifest.json").write_text(json.dumps({
        "dataset": "test",
        "product": "MES",
        "files": [{"one_minute": "parquet/1m/test.parquet"}],
    }), encoding="utf-8")

    output = tmp_path / "cloud"
    manifest = json.loads(export_cloud(runtime, output).read_text(encoding="utf-8"))
    meta = manifest["contracts"]["MESM24"]["display_shards"]["5"][0]
    with gzip.open(output / meta["key"], "rt", encoding="utf-8") as f:
        bars = json.load(f)

    assert len(bars) == 2
    assert bars[0]["t"] == int(pd.Timestamp("2024-06-10T22:00:00Z").timestamp())
    assert bars[0]["o"] == 5000.0
    assert bars[0]["c"] == 5004.5
    assert bars[0]["h"] == 5005.0
    assert bars[0]["l"] == 4999.0
    assert bars[0]["v"] == sum(range(10, 15))
    assert bars[1]["t"] == int(pd.Timestamp("2024-06-10T22:05:00Z").timestamp())

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from futureview_replay.cloud_export import export_cloud


def test_cloud_manifest_contains_causal_selection_calendar(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    parquet = runtime / "parquet" / "5m"
    parquet.mkdir(parents=True)
    rows = []
    volumes = {
        "2024-06-10T14:30:00Z": {"MESM24": 100, "MESU24": 10},
        "2024-06-11T14:30:00Z": {"MESM24": 80, "MESU24": 120},
        "2024-06-12T14:30:00Z": {"MESM24": 20, "MESU24": 200},
    }
    for timestamp, contract_volumes in volumes.items():
        for contract, volume in contract_volumes.items():
            rows.append(
                {
                    "timestamp": timestamp,
                    "symbol": contract,
                    "open": 5000,
                    "high": 5001,
                    "low": 4999,
                    "close": 5000.5,
                    "volume": volume,
                }
            )
    path = parquet / "test.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    (runtime / "manifest.json").write_text(
        json.dumps(
            {
                "dataset": "test",
                "product": "MES",
                "files": [{"five_minute": "parquet/5m/test.parquet", "symbols": ["MESM24", "MESU24"]}],
            }
        ),
        encoding="utf-8",
    )

    result = export_cloud(runtime, tmp_path / "cloud")
    manifest = json.loads(result.read_text(encoding="utf-8"))
    assert manifest["version"] == 3
    assert manifest["roll_rule"] == "prior_session_volume"
    sessions = manifest["contract_selection"]["sessions"]
    assert [item["contract"] for item in sessions] == ["MESM24", "MESM24", "MESU24"]
    assert sessions[2]["source_session"] == "2024-06-11"

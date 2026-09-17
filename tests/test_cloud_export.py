from __future__ import annotations

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
                "files": [{"one_minute": "parquet/1m/test.parquet", "symbols": ["MESM24", "MESU24"]}],
            }
        ),
        encoding="utf-8",
    )

    result = export_cloud(runtime, tmp_path / "cloud")
    manifest = json.loads(result.read_text(encoding="utf-8"))
    assert manifest["version"] == 5
    assert manifest["resolution"] == "1m"
    assert manifest["supported_display_resolutions"] == ["1", "5", "30", "240", "1D"]
    assert manifest["roll_rule"] == "runtime_prior_session_max_volume"
    selection = manifest["contract_selection"]
    assert selection["rule"] == "runtime_prior_session_max_volume"
    assert selection["expiry_cutoff_et"] == "09:30"
    assert selection["sessions"] == ["2024-06-10", "2024-06-11", "2024-06-12"]
    assert selection["session_volumes"]["2024-06-11"]["MESU24"] == 120.0

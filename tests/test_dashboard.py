from __future__ import annotations

import json
from datetime import date

import polars as pl

from futureview.dashboard import write_dashboard_snapshot


def test_dashboard_export_writes_rank_order_and_metadata(tmp_path):
    rankings = pl.DataFrame(
        {
            "rank": [2, 1],
            "symbol": ["BBB", "AAA"],
            "stock_score": [0.8, 0.9],
            "rs20": [0.1, 0.2],
            "rs60": [0.2, 0.3],
            "extension_atr": [1.2, 0.8],
            "breakout20": [False, True],
        }
    )

    path = write_dashboard_snapshot(
        rankings,
        tmp_path / "data" / "latest.json",
        as_of=date(2026, 8, 23),
        universe_count=3210,
        market_regime="risk-on",
        cash_posture="normal",
    )

    payload = json.loads(path.read_text())
    assert payload["as_of"] == "2026-08-23"
    assert payload["universe_count"] == 3210
    assert [row["symbol"] for row in payload["rankings"]] == ["AAA", "BBB"]

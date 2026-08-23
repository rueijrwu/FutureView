from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def write_dashboard_snapshot(
    rankings: pl.DataFrame,
    output_path: str | Path,
    *,
    as_of: date | datetime | str | None = None,
    universe_count: int | None = None,
    market_regime: str | None = None,
    cash_posture: str | None = None,
    top_n: int = 50,
) -> Path:
    """Write the static JSON contract consumed by the Cloudflare Pages dashboard.

    This exporter is intentionally presentation-only. It does not recompute any
    features or rankings, so the live dashboard and historical backtest continue
    to share the same point-in-time research pipeline.
    """
    if top_n <= 0:
        raise ValueError("top_n must be positive")

    selected = rankings.sort("rank").head(top_n) if rankings.height else rankings
    rows = [
        {key: _json_value(value) for key, value in row.items()}
        for row in selected.to_dicts()
    ]

    payload = {
        "as_of": _json_value(as_of),
        "universe_count": universe_count,
        "market_regime": market_regime,
        "cash_posture": cash_posture,
        "rankings": rows,
    }

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    return path

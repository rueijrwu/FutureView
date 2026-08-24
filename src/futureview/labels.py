from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (15, 30, 45, 60)


def make_forward_labels(df: pd.DataFrame, horizons: tuple[int, ...] = HORIZONS) -> pd.DataFrame:
    """Build forward-path metrics. These columns are labels/evaluation data only."""
    close = df["close"].to_numpy(dtype=float)
    dates = pd.to_datetime(df["date"]).to_numpy()
    max_h = max(horizons)
    rows: list[dict[str, float | object]] = []

    for i in range(len(df) - max_h):
        base = close[i]
        row: dict[str, float | object] = {"date": dates[i]}
        for h in horizons:
            path = close[i + 1 : i + h + 1]
            forward_return = path[-1] / base - 1.0
            rel_path = path / base - 1.0
            mae = min(0.0, float(rel_path.min()))
            mfe = max(0.0, float(rel_path.max()))
            full_path = np.concatenate(([base], path))
            path_length = float(np.abs(np.diff(full_path)).sum())
            efficiency = 0.0 if path_length == 0.0 else float((path[-1] - base) / path_length)

            # Provisional continuous target for pipeline validation only.
            # The exact target formula remains a research variable.
            quality = float(np.clip(np.tanh(12.0 * forward_return) * abs(efficiency) - 2.0 * abs(mae), -1.0, 1.0))

            row[f"return_{h}"] = float(forward_return)
            row[f"mae_{h}"] = mae
            row[f"mfe_{h}"] = mfe
            row[f"efficiency_{h}"] = efficiency
            row[f"trend_{h}"] = quality
        rows.append(row)

    return pd.DataFrame(rows)

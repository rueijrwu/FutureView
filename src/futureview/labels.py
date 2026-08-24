from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

HORIZONS = (15, 30, 45, 60)


@dataclass(frozen=True)
class SuccessProfile:
    min_return: dict[int, float]
    min_efficiency: float
    min_mae: dict[int, float]


SUCCESS_PROFILES: dict[str, SuccessProfile] = {
    "loose": SuccessProfile(
        min_return={15: 0.02, 30: 0.03, 45: 0.04, 60: 0.05},
        min_efficiency=0.20,
        min_mae={15: -0.04, 30: -0.05, 45: -0.06, 60: -0.07},
    ),
    "strict": SuccessProfile(
        min_return={15: 0.03, 30: 0.05, 45: 0.07, 60: 0.09},
        min_efficiency=0.30,
        min_mae={15: -0.03, 30: -0.04, 45: -0.05, 60: -0.06},
    ),
}


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

            # Provisional continuous target for pipeline/training validation only.
            # Final target formulation remains a research variable.
            quality = float(
                np.clip(
                    np.tanh(12.0 * forward_return) * abs(efficiency) - 2.0 * abs(mae),
                    -1.0,
                    1.0,
                )
            )

            row[f"return_{h}"] = float(forward_return)
            row[f"mae_{h}"] = mae
            row[f"mfe_{h}"] = mfe
            row[f"efficiency_{h}"] = efficiency
            row[f"trend_{h}"] = quality
        rows.append(row)

    return pd.DataFrame(rows)


def add_success_labels(
    labels: pd.DataFrame,
    profile_name: str = "loose",
    horizons: tuple[int, ...] = HORIZONS,
) -> pd.DataFrame:
    """Add binary successful-trend columns for evaluation only.

    Profiles are intentionally predeclared and horizon-aware. They are provisional
    research definitions and must not be tuned on the test set.
    """
    if profile_name not in SUCCESS_PROFILES:
        raise ValueError(f"unknown success profile: {profile_name}")
    profile = SUCCESS_PROFILES[profile_name]
    out = labels.copy()
    for h in horizons:
        if h not in profile.min_return or h not in profile.min_mae:
            raise ValueError(f"profile {profile_name} missing horizon {h}")
        out[f"success_{profile_name}_{h}"] = (
            (out[f"return_{h}"] >= profile.min_return[h])
            & (out[f"mae_{h}"] >= profile.min_mae[h])
            & (out[f"efficiency_{h}"] >= profile.min_efficiency)
        ).astype(np.int8)
    return out

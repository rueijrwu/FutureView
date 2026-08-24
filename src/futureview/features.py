from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_COLUMNS = ("open_rel", "high_rel", "low_rel", "close_rel", "volume_z")


def make_causal_features(df: pd.DataFrame, volume_window: int = 20) -> pd.DataFrame:
    """Create end-of-day features using only information available through each row."""
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")

    out = df.loc[:, ["date", "open", "high", "low", "close", "volume"]].copy()
    prev_close = out["close"].shift(1)
    out["open_rel"] = out["open"] / prev_close - 1.0
    out["high_rel"] = out["high"] / prev_close - 1.0
    out["low_rel"] = out["low"] / prev_close - 1.0
    out["close_rel"] = out["close"] / prev_close - 1.0

    log_volume = np.log(out["volume"].clip(lower=1).astype(float))
    rolling_mean = log_volume.rolling(volume_window, min_periods=volume_window).mean()
    rolling_std = log_volume.rolling(volume_window, min_periods=volume_window).std(ddof=0)
    out["volume_z"] = (log_volume - rolling_mean) / rolling_std.replace(0.0, np.nan)

    result = out.loc[:, ["date", *FEATURE_COLUMNS]].replace([np.inf, -np.inf], np.nan).dropna()
    return result.reset_index(drop=True)

from __future__ import annotations

import numpy as np
import pandas as pd

from .strategy1 import STRATEGY1_HORIZONS, make_strategy1_oracle_labels

STRATEGY1_TARGET_COLUMNS = tuple(f"oracle_s1_{h}" for h in STRATEGY1_HORIZONS)


def make_strategy1_targets(
    df: pd.DataFrame,
    horizons: tuple[int, ...] = STRATEGY1_HORIZONS,
) -> pd.DataFrame:
    """Return the formal Strategy 1 learning targets aligned by prediction date.

    The values are deterministic Oracle Values constructed from future data under
    the frozen Strategy 1 rules. Future information appears only in label
    construction; model inputs remain causal.
    """
    labels = make_strategy1_oracle_labels(df, horizons=horizons)
    rename = {f"oracle_value_{h}": f"oracle_s1_{h}" for h in horizons}
    out = labels.loc[:, ["date", *rename.keys()]].rename(columns=rename)

    target_columns = [f"oracle_s1_{h}" for h in horizons]
    values = out.loc[:, target_columns].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Non-finite Strategy 1 target found")
    if (values < -1e-12).any():
        raise ValueError("Strategy 1 Oracle targets must be non-negative")
    if out["date"].duplicated().any():
        raise ValueError("Duplicate Strategy 1 target dates found")

    return out.reset_index(drop=True)

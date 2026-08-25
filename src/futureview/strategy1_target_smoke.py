from __future__ import annotations

import numpy as np

from .data import download_spy_daily, validate_daily_ohlcv
from .datasets import build_windows
from .features import make_causal_features
from .strategy1_targets import STRATEGY1_TARGET_COLUMNS, make_strategy1_targets


def main() -> None:
    df = download_spy_daily(period="3y")
    audit = validate_daily_ohlcv(df)
    features = make_causal_features(df)
    targets = make_strategy1_targets(df)
    windows = build_windows(features, targets, lookback=50, target_columns=STRATEGY1_TARGET_COLUMNS)

    if windows.y.shape[1] != len(STRATEGY1_TARGET_COLUMNS):
        raise RuntimeError("Strategy 1 target width mismatch")
    if not np.isfinite(windows.y.numpy()).all():
        raise RuntimeError("Non-finite Strategy 1 window targets")
    if (windows.y.numpy() < -1e-12).any():
        raise RuntimeError("Negative Strategy 1 Oracle target")
    if len(windows.dates) == 0:
        raise RuntimeError("No Strategy 1 windows built")

    values = targets.loc[:, STRATEGY1_TARGET_COLUMNS].to_numpy(dtype=float)
    print(
        "STRATEGY1 TARGET DATASET "
        f"rows={audit.rows} target_rows={len(targets)} windows={len(windows.dates)} "
        f"x={tuple(windows.x.shape)} y={tuple(windows.y.shape)} "
        f"first_window_date={windows.dates[0]} last_window_date={windows.dates[-1]}"
    )

    for j, column in enumerate(STRATEGY1_TARGET_COLUMNS):
        v = values[:, j]
        q = np.quantile(v, [0.10, 0.25, 0.50, 0.75, 0.90, 0.95])
        print(
            f"STRATEGY1 TARGET {column} n={len(v)} zero={(v == 0.0).mean():.3f} "
            f"mean={v.mean():.6f} std={v.std(ddof=0):.6f} "
            f"p10={q[0]:.6f} p25={q[1]:.6f} p50={q[2]:.6f} "
            f"p75={q[3]:.6f} p90={q[4]:.6f} p95={q[5]:.6f} max={v.max():.6f}"
        )

    rank_corr = targets.loc[:, STRATEGY1_TARGET_COLUMNS].corr(method="spearman")
    for i in range(len(STRATEGY1_TARGET_COLUMNS)):
        for j in range(i + 1, len(STRATEGY1_TARGET_COLUMNS)):
            a = STRATEGY1_TARGET_COLUMNS[i]
            b = STRATEGY1_TARGET_COLUMNS[j]
            print(f"STRATEGY1 TARGET_RANK_CORR {a} {b} spearman={rank_corr.loc[a, b]:.3f}")

    print("STRATEGY1 TARGET SMOKE PASS")


if __name__ == "__main__":
    main()

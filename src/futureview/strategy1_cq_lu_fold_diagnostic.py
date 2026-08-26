from __future__ import annotations

import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1_cq_data import HORIZON, make_cq_labels, make_input_windows
from .strategy1_smh_cnn_close_volume_multiscale import _make_cq_folds

TICKER = "SMH"
DATA_PERIOD = "5y"


def _stats(x: np.ndarray) -> str:
    x = np.asarray(x, dtype=float)
    q25, med, q75 = np.quantile(x, [0.25, 0.50, 0.75])
    return (
        f"n={len(x)} mean={np.mean(x):.6f} min={np.min(x):.6f} "
        f"q25={q25:.6f} median={med:.6f} q75={q75:.6f} max={np.max(x):.6f}"
    )


def main() -> None:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    labels = make_cq_labels(df)

    x, kept_raw = make_input_windows(df, labels.raw_indices)
    del x
    pos = {int(r): i for i, r in enumerate(labels.raw_indices)}
    kept_label_idx = np.asarray([pos[int(r)] for r in kept_raw], dtype=int)

    raw_indices = labels.raw_indices[kept_label_idx]
    dates = pd.to_datetime(labels.dates[kept_label_idx])
    L = labels.L[kept_label_idx]
    mu = labels.mu[kept_label_idx]
    U = labels.U[kept_label_idx]
    C = labels.C[kept_label_idx]
    Q = labels.Q[kept_label_idx]

    raw_dates = pd.to_datetime(df["date"]).reset_index(drop=True)
    live_end = raw_dates.iloc[-1]
    live_start = live_end - pd.DateOffset(months=3)
    holdout_positions = np.flatnonzero(raw_dates.to_numpy() >= np.datetime64(live_start))
    holdout_start = int(holdout_positions[0]) if len(holdout_positions) else len(raw_dates)
    mature = raw_indices + HORIZON - 1 < holdout_start

    raw_indices = raw_indices[mature]
    dates = dates[mature]
    L, mu, U, C, Q = L[mature], mu[mature], U[mature], C[mature], Q[mature]

    folds = _make_cq_folds(raw_indices)
    print(
        f"S1 LU_DIAG DATA ticker={TICKER} rows={audit.rows} samples={len(raw_indices)} "
        f"folds={len(folds)} holdout_start={pd.Timestamp(live_start).date()}"
    )

    for fold_id, (train, test) in enumerate(folds, start=1):
        print(
            f"S1 LU_DIAG FOLD id={fold_id} "
            f"train_dates={pd.Timestamp(dates[train][0]).date()}..{pd.Timestamp(dates[train][-1]).date()} "
            f"test_dates={pd.Timestamp(dates[test][0]).date()}..{pd.Timestamp(dates[test][-1]).date()} "
            f"n_train={len(train)} n_test={len(test)}"
        )
        for name, arr in (("L", L), ("U", U), ("C", C), ("mu", mu), ("Q", Q)):
            print(f"S1 LU_DIAG TEST fold={fold_id} metric={name} {_stats(arr[test])}")

        # Useful endpoint geometry summaries for direct Fold-2/Fold-3 comparison.
        safe_lower = np.mean(L[test] >= 0.0)
        positive_upper = np.mean(U[test] > 0.0)
        both_positive = np.mean((L[test] >= 0.0) & (U[test] > 0.0))
        print(
            f"S1 LU_DIAG GEOMETRY fold={fold_id} "
            f"frac_L_ge_0={safe_lower:.6f} frac_U_gt_0={positive_upper:.6f} "
            f"frac_both_positive={both_positive:.6f} "
            f"mean_midpoint={np.mean((L[test] + U[test]) / 2.0):.6f} "
            f"median_midpoint={np.median((L[test] + U[test]) / 2.0):.6f}"
        )

    if len(folds) >= 3:
        _, test2 = folds[1]
        _, test3 = folds[2]
        print(
            "S1 LU_DIAG COMPARE fold2_vs_fold3 "
            f"delta_L_mean={np.mean(L[test3]) - np.mean(L[test2]):.6f} "
            f"delta_U_mean={np.mean(U[test3]) - np.mean(U[test2]):.6f} "
            f"delta_C_mean={np.mean(C[test3]) - np.mean(C[test2]):.6f} "
            f"delta_mu_mean={np.mean(mu[test3]) - np.mean(mu[test2]):.6f} "
            f"delta_midpoint_mean={np.mean((L[test3] + U[test3]) / 2.0) - np.mean((L[test2] + U[test2]) / 2.0):.6f}"
        )
    print("S1 LU_DIAG COMPLETE")


if __name__ == "__main__":
    main()

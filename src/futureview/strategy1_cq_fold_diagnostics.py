from __future__ import annotations

import numpy as np
import pandas as pd

from .data import download_ticker_daily
from .strategy1_cq_data import HORIZON, make_cq_labels, make_input_windows
from .strategy1_smh_cnn_close_volume_multiscale import _make_cq_folds, _make_preference_pairs

TICKER = "SMH"
DATA_PERIOD = "5y"


def _summary(x: np.ndarray) -> str:
    x = np.asarray(x, dtype=float)
    return (
        f"n={len(x)} mean={np.mean(x):.6f} median={np.median(x):.6f} "
        f"p25={np.quantile(x,0.25):.6f} p75={np.quantile(x,0.75):.6f} "
        f"min={np.min(x):.6f} max={np.max(x):.6f}"
    )


def main() -> None:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    raw_dates = pd.to_datetime(df["date"]).reset_index(drop=True)
    live_end = raw_dates.iloc[-1]
    live_start = live_end - pd.DateOffset(months=3)
    holdout_positions = np.flatnonzero(raw_dates.to_numpy() >= np.datetime64(live_start))
    holdout_start = int(holdout_positions[0]) if len(holdout_positions) else len(raw_dates)

    labels = make_cq_labels(df)
    mature = labels.raw_indices + HORIZON - 1 < holdout_start
    label_raw = labels.raw_indices[mature]
    _, kept_raw = make_input_windows(df, label_raw)
    lookup = {int(r): i for i, r in enumerate(labels.raw_indices)}
    li = np.asarray([lookup[int(r)] for r in kept_raw], dtype=int)
    raw_indices = kept_raw
    dates = pd.to_datetime(labels.dates[li])
    mu = labels.mu[li]
    C = labels.C[li]
    Q = labels.Q[li]

    folds = _make_cq_folds(raw_indices)
    print(f"S1 CQ_FOLD_DIAG DATA samples={len(raw_indices)} folds={len(folds)}")
    for fid, (train, test) in enumerate(folds, 1):
        gate = float(np.median(mu[train]))
        tg = train[mu[train] >= gate]
        vg = test[mu[test] >= gate]
        tb, tw = _make_preference_pairs(C[tg], Q[tg])
        vb, vw = _make_preference_pairs(C[vg], Q[vg])
        train_total_pairs = len(tg) * (len(tg)-1) // 2
        test_total_pairs = len(vg) * (len(vg)-1) // 2
        print(
            f"S1 CQ_FOLD_DIAG FOLD id={fid} "
            f"train_dates={dates[train[0]].date()}..{dates[train[-1]].date()} "
            f"test_dates={dates[test[0]].date()}..{dates[test[-1]].date()} "
            f"n_train={len(train)} n_test={len(test)} gate={gate:.6f} "
            f"n_train_gate={len(tg)} n_test_gate={len(vg)} "
            f"train_pairs={len(tb)} test_pairs={len(vb)} "
            f"train_pair_density={(len(tb)/train_total_pairs if train_total_pairs else np.nan):.6f} "
            f"test_pair_density={(len(vb)/test_total_pairs if test_total_pairs else np.nan):.6f}"
        )
        print(f"S1 CQ_FOLD_DIAG TRAIN_MU id={fid} {_summary(mu[tg])}")
        print(f"S1 CQ_FOLD_DIAG TRAIN_C id={fid} {_summary(C[tg])}")
        print(f"S1 CQ_FOLD_DIAG TRAIN_Q id={fid} {_summary(Q[tg])}")
        print(f"S1 CQ_FOLD_DIAG TEST_MU id={fid} {_summary(mu[vg])}")
        print(f"S1 CQ_FOLD_DIAG TEST_C id={fid} {_summary(C[vg])}")
        print(f"S1 CQ_FOLD_DIAG TEST_Q id={fid} {_summary(Q[vg])}")
    print("S1 CQ_FOLD_DIAG COMPLETE")


if __name__ == "__main__":
    main()

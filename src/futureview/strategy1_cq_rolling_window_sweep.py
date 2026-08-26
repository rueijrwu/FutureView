from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from .data import download_ticker_daily
from .strategy1_cq_data import HORIZON, make_cq_labels, make_input_windows
from .strategy1_smh_cnn_close_volume_multiscale import (
    DATA_PERIOD,
    SEEDS,
    TICKER,
    _fit_ranker,
    _make_cq_folds,
    _pair_accuracy,
)

WINDOWS = (20, 30, 35, 45, 60, 90)


def main() -> None:
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    raw_dates = pd.to_datetime(df["date"]).reset_index(drop=True)
    live_start = raw_dates.iloc[-1] - pd.DateOffset(months=3)
    holdout_positions = np.flatnonzero(raw_dates.to_numpy() >= np.datetime64(live_start))
    holdout_start = int(holdout_positions[0]) if len(holdout_positions) else len(raw_dates)

    labels = make_cq_labels(df)
    mature = labels.raw_indices + HORIZON - 1 < holdout_start
    label_raw = labels.raw_indices[mature]
    x_np, kept_raw = make_input_windows(df, label_raw)
    lookup = {int(r): i for i, r in enumerate(labels.raw_indices)}
    label_idx = np.asarray([lookup[int(r)] for r in kept_raw], dtype=int)

    x = torch.from_numpy(x_np)
    raw_indices = kept_raw
    mu = labels.mu[label_idx]
    C = labels.C[label_idx]
    Q = labels.Q[label_idx]
    dates = raw_dates.iloc[raw_indices].to_numpy()
    folds = _make_cq_folds(raw_indices)

    print(f"S1 CQ_ROLL DATA samples={len(raw_indices)} folds={len(folds)} windows={','.join(map(str, WINDOWS))}")
    summary_rows: dict[int, list[float]] = {w: [] for w in WINDOWS}

    for fold_id, (train, test) in enumerate(folds, start=1):
        gate = float(np.median(mu[train]))
        train_gate = train[mu[train] >= gate]
        test_gate = test[mu[test] >= gate]
        print(
            f"S1 CQ_ROLL FOLD id={fold_id} gate={gate:.6f} n_train_gate={len(train_gate)} "
            f"n_test_gate={len(test_gate)} test_dates={pd.Timestamp(dates[test_gate[0]]).date()}..{pd.Timestamp(dates[test_gate[-1]]).date()}"
        )
        for window in WINDOWS:
            if len(train_gate) < window or len(test_gate) < 2:
                print(f"S1 CQ_ROLL RESULT fold={fold_id} window={window} skipped=true")
                continue
            rolling_train = train_gate[-window:]
            seed_accs = []
            for seed in SEEDS:
                model = _fit_ranker(x[rolling_train], C[rolling_train], Q[rolling_train], seed)
                model.eval()
                with torch.no_grad():
                    scores = model(x[test_gate]).cpu().numpy().astype(float)
                _, pairs, acc = _pair_accuracy(scores, C[test_gate], Q[test_gate])
                seed_accs.append(acc)
            mean_acc = float(np.mean(seed_accs))
            summary_rows[window].append(mean_acc)
            print(
                f"S1 CQ_ROLL RESULT fold={fold_id} window={window} "
                f"train_dates={pd.Timestamp(dates[rolling_train[0]]).date()}..{pd.Timestamp(dates[rolling_train[-1]]).date()} "
                f"n_train={len(rolling_train)} pairs={pairs} seed_accs={','.join(f'{a:.6f}' for a in seed_accs)} mean_acc={mean_acc:.6f}"
            )

    for window in WINDOWS:
        vals = summary_rows[window]
        if vals:
            print(
                f"S1 CQ_ROLL SUMMARY window={window} folds_scored={len(vals)} "
                f"mean_acc={np.mean(vals):.6f} median_acc={np.median(vals):.6f} "
                f"better_than_random_folds={sum(v > 0.5 for v in vals)}/{len(vals)}"
            )
        else:
            print(f"S1 CQ_ROLL SUMMARY window={window} folds_scored=0")
    print("S1 CQ_ROLL COMPLETE")


if __name__ == "__main__":
    main()

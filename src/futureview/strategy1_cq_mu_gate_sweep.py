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

QUANTILES = (0.50, 0.60, 0.70, 0.80)
ROLLING_WINDOW = 20
MIN_TRAIN = 8
MIN_TEST = 4


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

    print(f"S1 CQ_MU_SWEEP DATA samples={len(raw_indices)} folds={len(folds)} rolling_window={ROLLING_WINDOW} quantiles={','.join(str(q) for q in QUANTILES)}")
    summaries = {q: [] for q in QUANTILES}
    trade_counts = {q: 0 for q in QUANTILES}

    for fold_id, (train, test) in enumerate(folds, start=1):
        recent_train = train[-min(len(train), ROLLING_WINDOW):]
        for q in QUANTILES:
            gate = float(np.quantile(mu[recent_train], q))
            train_gate = recent_train[mu[recent_train] >= gate]
            test_gate = test[mu[test] >= gate]

            if len(train_gate) < MIN_TRAIN or len(test_gate) < MIN_TEST:
                print(
                    f"S1 CQ_MU_SWEEP RESULT fold={fold_id} q={q:.2f} gate={gate:.6f} "
                    f"n_train={len(train_gate)} n_test={len(test_gate)} action=NO_TRADE reason=insufficient_gated_samples"
                )
                continue

            seed_accs = []
            pairs = 0
            for seed in SEEDS:
                model = _fit_ranker(x[train_gate], C[train_gate], Q[train_gate], seed)
                model.eval()
                with torch.no_grad():
                    scores = model(x[test_gate]).cpu().numpy().astype(float)
                _, pairs, acc = _pair_accuracy(scores, C[test_gate], Q[test_gate])
                seed_accs.append(acc)

            valid = [a for a in seed_accs if np.isfinite(a)]
            if not valid or pairs == 0:
                print(
                    f"S1 CQ_MU_SWEEP RESULT fold={fold_id} q={q:.2f} gate={gate:.6f} "
                    f"n_train={len(train_gate)} n_test={len(test_gate)} action=NO_TRADE reason=no_preference_pairs"
                )
                continue

            mean_acc = float(np.mean(valid))
            summaries[q].append(mean_acc)
            trade_counts[q] += 1
            print(
                f"S1 CQ_MU_SWEEP RESULT fold={fold_id} q={q:.2f} gate={gate:.6f} "
                f"train_dates={pd.Timestamp(dates[train_gate[0]]).date()}..{pd.Timestamp(dates[train_gate[-1]]).date()} "
                f"test_dates={pd.Timestamp(dates[test_gate[0]]).date()}..{pd.Timestamp(dates[test_gate[-1]]).date()} "
                f"n_train={len(train_gate)} n_test={len(test_gate)} pairs={pairs} "
                f"seed_accs={','.join(f'{a:.6f}' for a in seed_accs)} mean_acc={mean_acc:.6f} action=TRADE"
            )

    for q in QUANTILES:
        vals = summaries[q]
        if vals:
            print(
                f"S1 CQ_MU_SWEEP SUMMARY q={q:.2f} folds_traded={trade_counts[q]}/{len(folds)} "
                f"mean_acc={np.mean(vals):.6f} median_acc={np.median(vals):.6f} "
                f"better_than_random={sum(v > 0.5 for v in vals)}/{len(vals)}"
            )
        else:
            print(f"S1 CQ_MU_SWEEP SUMMARY q={q:.2f} folds_traded=0/{len(folds)}")

    print("S1 CQ_MU_SWEEP COMPLETE")


if __name__ == "__main__":
    main()

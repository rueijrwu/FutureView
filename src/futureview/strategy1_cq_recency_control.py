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

FIXED_N = 35
TARGET_FOLD = 3


def _segment(train_gate: np.ndarray, which: str) -> np.ndarray:
    n = len(train_gate)
    if n < FIXED_N:
        raise RuntimeError(f"need at least {FIXED_N} gated training samples, got {n}")
    if which == "oldest":
        return train_gate[:FIXED_N]
    if which == "latest":
        return train_gate[-FIXED_N:]
    if which == "middle":
        start = (n - FIXED_N) // 2
        return train_gate[start:start + FIXED_N]
    raise ValueError(which)


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
    if len(folds) < TARGET_FOLD:
        raise RuntimeError(f"need fold {TARGET_FOLD}, only have {len(folds)}")

    train, test = folds[TARGET_FOLD - 1]
    gate = float(np.median(mu[train]))
    train_gate = train[mu[train] >= gate]
    test_gate = test[mu[test] >= gate]

    print(
        f"S1 CQ_RECENCY DATA samples={len(raw_indices)} fold={TARGET_FOLD} gate={gate:.6f} "
        f"n_train_gate={len(train_gate)} n_test_gate={len(test_gate)} fixed_n={FIXED_N} "
        f"test_dates={pd.Timestamp(dates[test_gate[0]]).date()}..{pd.Timestamp(dates[test_gate[-1]]).date()}"
    )

    for which in ("oldest", "middle", "latest"):
        subset = _segment(train_gate, which)
        seed_accs = []
        pair_counts = []
        for seed in SEEDS:
            model = _fit_ranker(x[subset], C[subset], Q[subset], seed)
            model.eval()
            with torch.no_grad():
                scores = model(x[test_gate]).cpu().numpy().astype(float)
            _, pairs, acc = _pair_accuracy(scores, C[test_gate], Q[test_gate])
            seed_accs.append(acc)
            pair_counts.append(pairs)
        print(
            f"S1 CQ_RECENCY RESULT segment={which} "
            f"train_dates={pd.Timestamp(dates[subset[0]]).date()}..{pd.Timestamp(dates[subset[-1]]).date()} "
            f"n_train={len(subset)} pairs={pair_counts[0]} "
            f"seed_accs={','.join(f'{a:.6f}' for a in seed_accs)} mean_acc={np.mean(seed_accs):.6f}"
        )

    print("S1 CQ_RECENCY COMPLETE")


if __name__ == "__main__":
    main()

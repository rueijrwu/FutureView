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

FIXED_TRAIN_GATED = 35
BOOT_REPS = 1000
BLOCK_LEN = 5
BOOT_SEED = 20260826


def _score_models(models, x_test: torch.Tensor) -> np.ndarray:
    rows = []
    for model in models:
        model.eval()
        with torch.no_grad():
            rows.append(model(x_test).cpu().numpy().astype(float))
    return np.stack(rows, axis=0)


def _mean_pair_accuracy(score_matrix: np.ndarray, C: np.ndarray, Q: np.ndarray) -> float:
    vals = []
    for scores in score_matrix:
        _, _, acc = _pair_accuracy(scores, C, Q)
        if np.isfinite(acc):
            vals.append(acc)
    return float(np.mean(vals)) if vals else float("nan")


def _entry_bootstrap_ci(score_matrix: np.ndarray, C: np.ndarray, Q: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    n = len(C)
    vals = []
    for _ in range(BOOT_REPS):
        idx = rng.integers(0, n, size=n)
        acc = _mean_pair_accuracy(score_matrix[:, idx], C[idx], Q[idx])
        if np.isfinite(acc):
            vals.append(acc)
    if not vals:
        return float("nan"), float("nan")
    return tuple(np.quantile(vals, [0.025, 0.975]).astype(float))


def _block_bootstrap_ci(score_matrix: np.ndarray, C: np.ndarray, Q: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    n = len(C)
    vals = []
    for _ in range(BOOT_REPS):
        chosen = []
        while len(chosen) < n:
            start = int(rng.integers(0, n))
            chosen.extend((start + j) % n for j in range(BLOCK_LEN))
        idx = np.asarray(chosen[:n], dtype=int)
        acc = _mean_pair_accuracy(score_matrix[:, idx], C[idx], Q[idx])
        if np.isfinite(acc):
            vals.append(acc)
    if not vals:
        return float("nan"), float("nan")
    return tuple(np.quantile(vals, [0.025, 0.975]).astype(float))


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
    rng = np.random.default_rng(BOOT_SEED)

    print(f"S1 CQ_CONTROL DATA samples={len(raw_indices)} folds={len(folds)} fixed_train_gated={FIXED_TRAIN_GATED} bootstrap_reps={BOOT_REPS} block_len={BLOCK_LEN}")
    for fold_id, (train, test) in enumerate(folds, start=1):
        gate = float(np.median(mu[train]))
        train_gate = train[mu[train] >= gate]
        test_gate = test[mu[test] >= gate]
        if len(train_gate) < FIXED_TRAIN_GATED or len(test_gate) < 2:
            print(f"S1 CQ_CONTROL FOLD id={fold_id} skipped=true n_train_gate={len(train_gate)} n_test_gate={len(test_gate)}")
            continue

        # Use the most recent gated training entries only: fixed N and causal.
        fixed_train = train_gate[-FIXED_TRAIN_GATED:]
        models = [_fit_ranker(x[fixed_train], C[fixed_train], Q[fixed_train], seed) for seed in SEEDS]
        score_matrix = _score_models(models, x[test_gate])
        base_acc = _mean_pair_accuracy(score_matrix, C[test_gate], Q[test_gate])
        entry_lo, entry_hi = _entry_bootstrap_ci(score_matrix, C[test_gate], Q[test_gate], rng)
        block_lo, block_hi = _block_bootstrap_ci(score_matrix, C[test_gate], Q[test_gate], rng)

        seed_accs = []
        for scores in score_matrix:
            _, pairs, acc = _pair_accuracy(scores, C[test_gate], Q[test_gate])
            seed_accs.append(acc)
        print(
            f"S1 CQ_CONTROL FOLD id={fold_id} train_dates={pd.Timestamp(dates[fixed_train[0]]).date()}..{pd.Timestamp(dates[fixed_train[-1]]).date()} "
            f"test_dates={pd.Timestamp(dates[test_gate[0]]).date()}..{pd.Timestamp(dates[test_gate[-1]]).date()} gate={gate:.6f} "
            f"n_train_gate_original={len(train_gate)} n_train_fixed={len(fixed_train)} n_test_gate={len(test_gate)} pairs={pairs} "
            f"seed_accs={','.join(f'{a:.6f}' for a in seed_accs)} mean_acc={base_acc:.6f} "
            f"entry_boot_ci95={entry_lo:.6f},{entry_hi:.6f} block_boot_ci95={block_lo:.6f},{block_hi:.6f}"
        )
    print("S1 CQ_CONTROL COMPLETE")


if __name__ == "__main__":
    main()

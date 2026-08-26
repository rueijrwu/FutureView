from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1_success_training import DATA_PERIOD, HORIZON, make_success_dataset

TICKER = "SMH"
TOP_FRACTION = 0.20
RIDGE_ALPHA = 10.0
MIN_TRAIN = 140
TEST_SIZE = 30
MAX_FOLDS = 4
PURGE_RAW_SESSIONS = HORIZON


def _rankdata(values: np.ndarray) -> np.ndarray:
    return pd.Series(np.asarray(values, dtype=float)).rank(method="average").to_numpy(dtype=float)


def _spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    if len(y_true) < 2 or np.std(y_true) < 1e-12 or np.std(y_pred) < 1e-12:
        return float("nan")
    return float(np.corrcoef(_rankdata(y_true), _rankdata(y_pred))[0, 1])


def _fit_ridge(x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray) -> np.ndarray:
    mean = x_train.mean(axis=0)
    std = x_train.std(axis=0)
    std = np.where(std < 1e-8, 1.0, std)
    z_train = (x_train - mean) / std
    z_test = (x_test - mean) / std

    y_mean = float(np.mean(y_train))
    yc = np.asarray(y_train, dtype=float) - y_mean

    # Dual ridge is efficient and stable because the number of entry samples is
    # smaller than the flattened 50-session feature dimension.
    gram = z_train @ z_train.T
    coef_dual = np.linalg.solve(
        gram + RIDGE_ALPHA * np.eye(len(z_train), dtype=float),
        yc,
    )
    return y_mean + z_test @ z_train.T @ coef_dual


def _bucket_metrics(y: np.ndarray, pred: np.ndarray) -> tuple[float, float, float]:
    n = max(1, int(math.ceil(len(pred) * TOP_FRACTION)))
    order = np.argsort(pred, kind="stable")
    bottom = order[:n]
    top = order[-n:]
    top_mean = float(np.mean(y[top]))
    bottom_mean = float(np.mean(y[bottom]))
    return top_mean, bottom_mean, top_mean - bottom_mean


def _make_folds(raw_indices: np.ndarray) -> tuple[tuple[np.ndarray, np.ndarray], ...]:
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for test_start in range(MIN_TRAIN, len(raw_indices), TEST_SIZE):
        test = np.arange(test_start, min(test_start + TEST_SIZE, len(raw_indices)), dtype=int)
        if len(test) != TEST_SIZE:
            continue
        cutoff = int(raw_indices[test[0]]) - PURGE_RAW_SESSIONS - 1
        train = np.where(raw_indices[:test_start] <= cutoff)[0]
        if len(train) < MIN_TRAIN:
            continue
        folds.append((train, test))
    if not folds:
        raise RuntimeError("no complete purged chronological SMH Ridge folds")
    return tuple(folds[-MAX_FOLDS:])


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


def main() -> None:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    ds = make_success_dataset(df)

    raw_dates = pd.to_datetime(df["date"]).reset_index(drop=True)
    live_end = raw_dates.iloc[-1]
    live_start = live_end - pd.DateOffset(months=3)
    holdout_positions = np.flatnonzero(raw_dates.to_numpy() >= np.datetime64(live_start))
    holdout_start = int(holdout_positions[0]) if len(holdout_positions) else len(raw_dates)

    target_end = np.asarray(ds.raw_indices, dtype=int) + HORIZON - 1
    history_mask = target_end < holdout_start
    history_idx = np.flatnonzero(history_mask)

    x = ds.x.cpu().numpy().astype(float)[history_idx].reshape(len(history_idx), -1)
    raw_indices = np.asarray(ds.raw_indices, dtype=int)[history_idx]
    dates = pd.to_datetime(np.asarray(ds.dates)[history_idx])
    targets = {
        "L": np.asarray(ds.entry_lower, dtype=float)[history_idx],
        "mu": np.asarray(ds.net_expected_return, dtype=float)[history_idx],
        "U": np.asarray(ds.entry_upper, dtype=float)[history_idx],
    }
    folds = _make_folds(raw_indices)

    print(
        "S1 SMH_RIDGE DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"history_entries={len(history_idx)} folds={len(folds)} lookback=50 horizon={HORIZON} "
        f"live_holdout_start={pd.Timestamp(live_start).date()} live_holdout_end={pd.Timestamp(live_end).date()} "
        "history_rule=target_end_strictly_before_live_start"
    )
    print(
        "S1 SMH_RIDGE MODEL "
        f"name=RIDGE alpha={RIDGE_ALPHA:.6f} input=flattened_causal_daily_50x5 "
        "standardization=train_only targets=L,mu,U no_Q=true no_composite_score=true"
    )
    print(
        "S1 SMH_RIDGE EVAL "
        f"chronological=true purge_raw_sessions={PURGE_RAW_SESSIONS} top_fraction={TOP_FRACTION:.2f} "
        "metrics=spearman,realized_target_top20,bottom20,top_minus_bottom"
    )

    aggregate: dict[str, list[tuple[float, float, float, float]]] = {k: [] for k in targets}

    for fold_id, (train, test) in enumerate(folds, start=1):
        gap = int(raw_indices[test[0]] - raw_indices[train[-1]] - 1)
        print(
            f"S1 SMH_RIDGE FOLD id={fold_id} n_train={len(train)} n_test={len(test)} "
            f"train_first={pd.Timestamp(dates[train[0]]).date()} train_last={pd.Timestamp(dates[train[-1]]).date()} "
            f"test_first={pd.Timestamp(dates[test[0]]).date()} test_last={pd.Timestamp(dates[test[-1]]).date()} "
            f"raw_session_gap={gap}"
        )
        for name, y in targets.items():
            pred = _fit_ridge(x[train], y[train], x[test])
            rho = _spearman(y[test], pred)
            top, bottom, spread = _bucket_metrics(y[test], pred)
            aggregate[name].append((rho, top, bottom, spread))
            print(
                f"S1 SMH_RIDGE FOLD_TARGET id={fold_id} target={name} "
                f"spearman={_fmt(rho)} realized_top20_mean={top:.6f} "
                f"realized_bottom20_mean={bottom:.6f} top_minus_bottom={spread:.6f}"
            )

    for name, rows in aggregate.items():
        arr = np.asarray(rows, dtype=float)
        print(
            f"S1 SMH_RIDGE SUMMARY target={name} folds={len(rows)} "
            f"spearman_mean={_fmt(float(np.nanmean(arr[:,0])))} "
            f"spearman_positive_folds={int(np.sum(arr[:,0] > 0.0))}/{len(rows)} "
            f"realized_top20_mean={np.mean(arr[:,1]):.6f} "
            f"realized_bottom20_mean={np.mean(arr[:,2]):.6f} "
            f"top_minus_bottom_mean={np.mean(arr[:,3]):.6f} "
            f"positive_separation_folds={int(np.sum(arr[:,3] > 0.0))}/{len(rows)}"
        )

    print("S1 SMH_RIDGE COMPLETE")


if __name__ == "__main__":
    main()

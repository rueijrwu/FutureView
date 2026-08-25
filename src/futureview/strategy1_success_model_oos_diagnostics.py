from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1_success_live_campaign_expanded_oos import _expanded_event_folds
from .strategy1_success_training import (
    DATA_PERIOD,
    HORIZON,
    LOOKBACK,
    PURGE_RAW_SESSIONS,
    REFERENCE_LOOKBACK,
    SEEDS,
    TICKER,
    _fit,
    _spearman,
    make_success_dataset,
)

PROBABILITY_BIN_EDGES = np.linspace(0.0, 1.0, 6)


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


def _calibration_line(y_true: np.ndarray, prediction: np.ndarray) -> tuple[float, float]:
    y_true = np.asarray(y_true, dtype=float)
    prediction = np.asarray(prediction, dtype=float)
    if len(y_true) < 2 or np.std(prediction) < 1e-12:
        return float("nan"), float("nan")
    slope, intercept = np.polyfit(prediction, y_true, 1)
    return float(intercept), float(slope)


def _probability_bins(
    y_true: np.ndarray,
    prediction: np.ndarray,
    *,
    edges: np.ndarray = PROBABILITY_BIN_EDGES,
) -> list[tuple[float, float, int, float, float, float]]:
    y_true = np.asarray(y_true, dtype=float)
    prediction = np.asarray(prediction, dtype=float)
    rows: list[tuple[float, float, int, float, float, float]] = []
    for i in range(len(edges) - 1):
        lo = float(edges[i])
        hi = float(edges[i + 1])
        if i == len(edges) - 2:
            mask = (prediction >= lo) & (prediction <= hi)
        else:
            mask = (prediction >= lo) & (prediction < hi)
        n = int(np.sum(mask))
        if n == 0:
            rows.append((lo, hi, 0, float("nan"), float("nan"), float("nan")))
            continue
        pred_mean = float(np.mean(prediction[mask]))
        q_mean = float(np.mean(y_true[mask]))
        rows.append((lo, hi, n, pred_mean, q_mean, q_mean - pred_mean))
    return rows


def _ece(rows: list[tuple[float, float, int, float, float, float]]) -> float:
    total = sum(row[2] for row in rows)
    if total <= 0:
        return float("nan")
    return float(sum(row[2] * abs(row[5]) for row in rows if row[2] > 0) / total)


def main() -> None:
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    ds = make_success_dataset(df)
    folds = _expanded_event_folds(ds.raw_indices)

    print(
        "S1 Q_DIAGNOSTICS DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"samples={len(ds.success_probability)} folds={len(folds)} lookback={LOOKBACK} horizon={HORIZON} "
        f"reference_lookback={REFERENCE_LOOKBACK} purge_raw_sessions={PURGE_RAW_SESSIONS} "
        f"seeds={','.join(map(str, SEEDS))} no_random_split=true"
    )
    print(
        "S1 Q_DIAGNOSTICS RULE "
        "purpose=predict_entry_path_profitability_rate_q threshold_used=false gate_used=false "
        "primary_target=q_equals_mean_unique_legal_path_return_gt_0 "
        "probability_bins=fixed_0.20_width future_labels_not_features=true "
        "return_metrics_not_used_for_model_selection=true"
    )

    pooled_y: list[np.ndarray] = []
    pooled_pred: list[np.ndarray] = []
    fold_mae: list[float] = []
    fold_brier: list[float] = []
    fold_spearman: list[float] = []
    fold_ece: list[float] = []

    for fold_id, fold in enumerate(folds, start=1):
        y_train = ds.success_probability[fold.train]
        y_test = ds.success_probability[fold.test]
        seed_pred = [
            _fit(ds.x[fold.train].cpu(), y_train, ds.x[fold.test].cpu(), seed=seed)
            for seed in SEEDS
        ]
        pred_matrix = np.stack(seed_pred, axis=0)
        prediction = pred_matrix.mean(axis=0)
        disagreement = pred_matrix.std(axis=0)

        mae = float(np.mean(np.abs(y_test - prediction)))
        brier = float(np.mean((y_test - prediction) ** 2))
        spearman = _spearman(y_test, prediction)
        intercept, slope = _calibration_line(y_test, prediction)
        rows = _probability_bins(y_test, prediction)
        ece = _ece(rows)

        fold_mae.append(mae)
        fold_brier.append(brier)
        fold_spearman.append(spearman)
        fold_ece.append(ece)
        pooled_y.append(y_test.copy())
        pooled_pred.append(prediction.copy())

        print(
            f"S1 Q_DIAGNOSTICS FOLD id={fold_id} "
            f"test_first={pd.Timestamp(ds.dates[fold.test[0]]).date()} "
            f"test_last={pd.Timestamp(ds.dates[fold.test[-1]]).date()} n={len(fold.test)} "
            f"q_mean={np.mean(y_test):.6f} pred_mean={np.mean(prediction):.6f} "
            f"mae={mae:.6f} brier={brier:.6f} ece={ece:.6f} "
            f"calibration_intercept={_fmt(intercept)} calibration_slope={_fmt(slope)} "
            f"spearman={_fmt(spearman)} seed_disagreement_mean={np.mean(disagreement):.6f}"
        )

        for lo, hi, n, pred_mean, q_mean, gap in rows:
            print(
                f"S1 Q_DIAGNOSTICS BIN fold={fold_id} range=[{lo:.1f},{hi:.1f}] "
                f"n={n} pred_mean={_fmt(pred_mean)} q_mean={_fmt(q_mean)} "
                f"q_minus_pred={_fmt(gap)}"
            )

    y_all = np.concatenate(pooled_y)
    pred_all = np.concatenate(pooled_pred)
    pooled_rows = _probability_bins(y_all, pred_all)
    pooled_mae = float(np.mean(np.abs(y_all - pred_all)))
    pooled_brier = float(np.mean((y_all - pred_all) ** 2))
    pooled_spearman = _spearman(y_all, pred_all)
    pooled_intercept, pooled_slope = _calibration_line(y_all, pred_all)
    pooled_ece = _ece(pooled_rows)

    for lo, hi, n, pred_mean, q_mean, gap in pooled_rows:
        print(
            f"S1 Q_DIAGNOSTICS POOLED_BIN range=[{lo:.1f},{hi:.1f}] "
            f"n={n} pred_mean={_fmt(pred_mean)} q_mean={_fmt(q_mean)} "
            f"q_minus_pred={_fmt(gap)}"
        )

    print(
        "S1 Q_DIAGNOSTICS SUMMARY "
        f"ticker={TICKER} oos_n={len(y_all)} folds={len(folds)} "
        f"q_mean={np.mean(y_all):.6f} pred_mean={np.mean(pred_all):.6f} "
        f"mae={pooled_mae:.6f} brier={pooled_brier:.6f} ece={pooled_ece:.6f} "
        f"calibration_intercept={_fmt(pooled_intercept)} "
        f"calibration_slope={_fmt(pooled_slope)} "
        f"spearman={_fmt(pooled_spearman)} "
        f"fold_mae_mean={np.mean(fold_mae):.6f} "
        f"fold_brier_mean={np.mean(fold_brier):.6f} "
        f"fold_ece_mean={np.mean(fold_ece):.6f} "
        f"fold_spearman_mean={np.nanmean(fold_spearman):.6f}"
    )
    print("S1 Q_DIAGNOSTICS PASS")


if __name__ == "__main__":
    main()

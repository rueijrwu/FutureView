from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1_success_training import (
    DATA_PERIOD,
    HORIZON,
    LOOKBACK,
    PURGE_RAW_SESSIONS,
    REFERENCE_LOOKBACK,
    SEEDS,
    TICKER,
    TOP_FRACTION,
    _event_folds,
    _fit,
    make_success_dataset,
)

THRESHOLD_QUANTILE = 1.0 - TOP_FRACTION
CALIBRATION_EVENTS = 30
MIN_INNER_TRAIN_EVENTS = 100


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


def _calibration_split(train: np.ndarray, raw_indices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Chronological inner split with the same raw-session purge used by outer OOS folds."""
    train = np.asarray(train, dtype=int)
    if len(train) <= CALIBRATION_EVENTS:
        raise RuntimeError("not enough historical entries for threshold calibration")

    calibration = train[-CALIBRATION_EVENTS:]
    calibration_first_raw = int(raw_indices[calibration[0]])
    cutoff = calibration_first_raw - PURGE_RAW_SESSIONS - 1
    model_train = train[raw_indices[train] <= cutoff]
    if len(model_train) < MIN_INNER_TRAIN_EVENTS:
        raise RuntimeError(
            f"inner model train too small after purge: {len(model_train)} < {MIN_INNER_TRAIN_EVENTS}"
        )
    return model_train, calibration


def main() -> None:
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    ds = make_success_dataset(df)
    folds = _event_folds(ds.raw_indices)

    print(
        "S1 LIVE_THRESHOLD DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"samples={len(ds.success_probability)} folds={len(folds)} lookback={LOOKBACK} horizon={HORIZON} "
        f"reference_lookback={REFERENCE_LOOKBACK} purge_raw_sessions={PURGE_RAW_SESSIONS} "
        f"calibration_events={CALIBRATION_EVENTS} seeds={','.join(map(str, SEEDS))} no_random_split=true"
    )
    print(
        "S1 LIVE_THRESHOLD RULE "
        f"threshold_source=historical_calibration_predictions threshold_quantile={THRESHOLD_QUANTILE:.2f} "
        "inner_split=chronological_purged same_model_for_calibration_and_test=true "
        "test_ranking_used=false test_labels_used=false decision=enter_if_p_hat_gte_threshold "
        "actual_execution=deterministic_strategy1"
    )

    rows: list[dict[str, float]] = []
    for fold_id, fold in enumerate(folds, start=1):
        outer_train, test = fold.train, fold.test
        model_train, calibration = _calibration_split(outer_train, ds.raw_indices)
        y_model_train = ds.success_probability[model_train]
        realized_test = ds.realized_return[test]
        x_eval = torch.cat([ds.x[calibration].cpu(), ds.x[test].cpu()], dim=0)

        inner_gap = int(ds.raw_indices[calibration[0]] - ds.raw_indices[model_train[-1]] - 1)
        outer_gap = int(ds.raw_indices[test[0]] - ds.raw_indices[outer_train[-1]] - 1)

        for seed in SEEDS:
            pred_eval = _fit(ds.x[model_train].cpu(), y_model_train, x_eval, seed=seed)
            calibration_pred = pred_eval[: len(calibration)]
            test_pred = pred_eval[len(calibration) :]
            threshold = float(np.quantile(calibration_pred, THRESHOLD_QUANTILE))
            selected = test_pred >= threshold
            selected_count = int(np.sum(selected))
            selection_rate = float(np.mean(selected))

            all_success = float(np.mean(realized_test > 0.0))
            all_net = float(np.mean(realized_test))
            if selected_count:
                selected_success = float(np.mean(realized_test[selected] > 0.0))
                selected_net = float(np.mean(realized_test[selected]))
                success_lift = selected_success - all_success
            else:
                selected_success = float("nan")
                selected_net = float("nan")
                success_lift = float("nan")

            row = {
                "threshold": threshold,
                "selected_count": float(selected_count),
                "selection_rate": selection_rate,
                "all_success": all_success,
                "selected_success": selected_success,
                "success_lift": success_lift,
                "all_net": all_net,
                "selected_net": selected_net,
            }
            rows.append(row)
            print(
                f"S1 LIVE_THRESHOLD FOLD_METRIC id={fold_id} seed={seed} "
                f"model_train_n={len(model_train)} calibration_n={len(calibration)} test_n={len(test)} "
                f"inner_gap={inner_gap} outer_gap={outer_gap} "
                f"test_first={pd.Timestamp(ds.dates[test[0]]).date()} "
                f"test_last={pd.Timestamp(ds.dates[test[-1]]).date()} "
                f"threshold={threshold:.6f} selected={selected_count}/{len(test)} "
                f"selection_rate={selection_rate:.6f} "
                f"realized_all_success={all_success:.6f} "
                f"realized_selected_success={_fmt(selected_success)} "
                f"realized_success_lift={_fmt(success_lift)} "
                f"realized_all_net_return={all_net:.6f} "
                f"realized_selected_net_return={_fmt(selected_net)}"
            )

    valid = [row for row in rows if np.isfinite(row["selected_success"])]
    if not valid:
        raise RuntimeError("calibrated live threshold selected no OOS entries in every run")

    selection_rate = np.asarray([row["selection_rate"] for row in rows], dtype=float)
    selected_count = np.asarray([row["selected_count"] for row in rows], dtype=float)
    all_success = np.asarray([row["all_success"] for row in valid], dtype=float)
    selected_success = np.asarray([row["selected_success"] for row in valid], dtype=float)
    lift = np.asarray([row["success_lift"] for row in valid], dtype=float)
    all_net = np.asarray([row["all_net"] for row in valid], dtype=float)
    selected_net = np.asarray([row["selected_net"] for row in valid], dtype=float)

    print(
        "S1 LIVE_THRESHOLD SUMMARY "
        f"ticker={TICKER} runs={len(rows)} valid_runs={len(valid)} "
        f"selected_count_mean={selected_count.mean():.3f} selection_rate_mean={selection_rate.mean():.6f} "
        f"realized_all_success_mean={all_success.mean():.6f} "
        f"realized_selected_success_mean={selected_success.mean():.6f} "
        f"realized_success_lift_mean={lift.mean():.6f} "
        f"realized_success_lift_positive={int(np.sum(lift > 0.0))}/{len(lift)} "
        f"realized_all_net_return_mean={all_net.mean():.6f} "
        f"realized_selected_net_return_mean={selected_net.mean():.6f} "
        f"selected_net_positive={int(np.sum(selected_net > 0.0))}/{len(selected_net)}"
    )
    print("S1 LIVE_THRESHOLD PASS")


if __name__ == "__main__":
    main()

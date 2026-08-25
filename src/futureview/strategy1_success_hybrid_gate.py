from __future__ import annotations

import numpy as np
import torch

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_success_adaptive_gate import (
    ADAPTIVE_QUANTILE,
    ROLLING_SCORE_EVENTS,
    _adaptive_mask,
    _metric_row,
    _realize_delayed,
    _summary,
)
from .strategy1_success_entry_window import ENTRY_DELAY_MAX
from .strategy1_success_threshold import CALIBRATION_EVENTS, _calibration_split
from .strategy1_success_training import (
    DATA_PERIOD,
    HORIZON,
    LOOKBACK,
    PURGE_RAW_SESSIONS,
    REFERENCE_LOOKBACK,
    SEEDS,
    TICKER,
    _event_folds,
    _fit,
    make_success_dataset,
)

ABSOLUTE_FLOOR_QUANTILE = 0.50


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


def _hybrid_mask(
    calibration_pred: np.ndarray,
    test_pred: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Causal rolling-Q70 gate with a historical calibration-Q50 floor."""
    history = list(np.asarray(calibration_pred, dtype=float))
    floor = float(np.quantile(np.asarray(calibration_pred, dtype=float), ABSOLUTE_FLOOR_QUANTILE))
    selected = np.zeros(len(test_pred), dtype=bool)
    thresholds = np.full(len(test_pred), np.nan, dtype=float)

    for i, score in enumerate(np.asarray(test_pred, dtype=float)):
        recent = np.asarray(history[-ROLLING_SCORE_EVENTS:], dtype=float)
        rolling_threshold = float(np.quantile(recent, ADAPTIVE_QUANTILE))
        threshold = max(rolling_threshold, floor)
        thresholds[i] = threshold
        selected[i] = bool(score >= threshold)
        history.append(float(score))

    return selected, thresholds, floor


def main() -> None:
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    ds = make_success_dataset(df)
    folds = _event_folds(ds.raw_indices)
    events = add_strategy1_events(df).reset_index(drop=True)
    entry_candidate = events["entry_candidate"].to_numpy(dtype=bool)

    print(
        "S1 HYBRID_GATE DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"samples={len(ds.success_probability)} folds={len(folds)} lookback={LOOKBACK} horizon={HORIZON} "
        f"reference_lookback={REFERENCE_LOOKBACK} purge_raw_sessions={PURGE_RAW_SESSIONS} "
        f"calibration_events={CALIBRATION_EVENTS} rolling_score_events={ROLLING_SCORE_EVENTS} "
        f"adaptive_quantile={ADAPTIVE_QUANTILE:.2f} floor_quantile={ABSOLUTE_FLOOR_QUANTILE:.2f} "
        f"seeds={','.join(map(str, SEEDS))} no_random_split=true"
    )
    print(
        "S1 HYBRID_GATE RULE "
        "fixed_baseline=calibration_Q70 adaptive_baseline=rolling_Q70_of_last_30_observed_scores "
        "hybrid=max(rolling_Q70,calibration_Q50) current_score_added_after_decision=true "
        "labels_not_used_for_adaptation=true floor_uses_historical_calibration_only=true "
        f"delayed_entry_window=t_plus_1_to_t_plus_{ENTRY_DELAY_MAX} "
        "future_return_not_used_for_entry_day=true test_ranking_used=false test_labels_used=false"
    )

    fixed_rows: list[dict[str, float]] = []
    adaptive_rows: list[dict[str, float]] = []
    hybrid_rows: list[dict[str, float]] = []

    for fold_id, fold in enumerate(folds, start=1):
        outer_train, test = fold.train, fold.test
        model_train, calibration = _calibration_split(outer_train, ds.raw_indices)
        y_model_train = ds.success_probability[model_train]
        x_eval = torch.cat([ds.x[calibration].cpu(), ds.x[test].cpu()], dim=0)

        for seed in SEEDS:
            pred_eval = _fit(ds.x[model_train].cpu(), y_model_train, x_eval, seed=seed)
            calibration_pred = pred_eval[: len(calibration)]
            test_pred = pred_eval[len(calibration) :]

            fixed_threshold = float(np.quantile(calibration_pred, ADAPTIVE_QUANTILE))
            fixed_selected = test_pred >= fixed_threshold
            fixed_returns, fixed_signals = _realize_delayed(
                fixed_selected, test, ds.raw_indices, entry_candidate, len(events)
            )
            fixed_row = _metric_row(fixed_returns, fixed_signals, len(test))
            fixed_rows.append(fixed_row)

            adaptive_selected, adaptive_thresholds = _adaptive_mask(calibration_pred, test_pred)
            adaptive_returns, adaptive_signals = _realize_delayed(
                adaptive_selected, test, ds.raw_indices, entry_candidate, len(events)
            )
            adaptive_row = _metric_row(adaptive_returns, adaptive_signals, len(test))
            adaptive_rows.append(adaptive_row)

            hybrid_selected, hybrid_thresholds, floor = _hybrid_mask(calibration_pred, test_pred)
            hybrid_returns, hybrid_signals = _realize_delayed(
                hybrid_selected, test, ds.raw_indices, entry_candidate, len(events)
            )
            hybrid_row = _metric_row(hybrid_returns, hybrid_signals, len(test))
            hybrid_rows.append(hybrid_row)

            print(
                f"S1 HYBRID_GATE FOLD_METRIC id={fold_id} seed={seed} "
                f"fixed_threshold={fixed_threshold:.6f} floor={floor:.6f} "
                f"adaptive_threshold_last={adaptive_thresholds[-1]:.6f} "
                f"hybrid_threshold_last={hybrid_thresholds[-1]:.6f} "
                f"fixed_executions={int(fixed_row['execution_count'])}/{len(test)} "
                f"fixed_success={_fmt(fixed_row['success'])} fixed_net_return={_fmt(fixed_row['net'])} "
                f"adaptive_executions={int(adaptive_row['execution_count'])}/{len(test)} "
                f"adaptive_success={_fmt(adaptive_row['success'])} adaptive_net_return={_fmt(adaptive_row['net'])} "
                f"hybrid_signals={hybrid_signals}/{len(test)} "
                f"hybrid_executions={int(hybrid_row['execution_count'])}/{len(test)} "
                f"hybrid_coverage={hybrid_row['coverage']:.6f} "
                f"hybrid_success={_fmt(hybrid_row['success'])} hybrid_net_return={_fmt(hybrid_row['net'])}"
            )

    _summary("fixed_Q70", fixed_rows)
    _summary("adaptive_rolling_Q70", adaptive_rows)
    _summary("hybrid_rolling_Q70_floor_calibration_Q50", hybrid_rows)
    print("S1 HYBRID_GATE PASS")


if __name__ == "__main__":
    main()

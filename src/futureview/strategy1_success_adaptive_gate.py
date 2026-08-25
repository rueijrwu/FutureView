from __future__ import annotations

import numpy as np
import torch

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_success_entry_window import ENTRY_DELAY_MAX, _first_delayed_eligible_entry
from .strategy1_success_threshold import CALIBRATION_EVENTS, _calibration_split
from .strategy1_success_training import (
    DATA_PERIOD,
    HORIZON,
    LOOKBACK,
    PURGE_RAW_SESSIONS,
    REFERENCE_LOOKBACK,
    SEEDS,
    TICKER,
    _actual_entry_return,
    _event_folds,
    _fit,
    make_success_dataset,
)

ADAPTIVE_QUANTILE = 0.70
ROLLING_SCORE_EVENTS = 30


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


def _adaptive_mask(
    calibration_pred: np.ndarray,
    test_pred: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Causal rolling percentile gate using only scores observed before each decision."""
    history = list(np.asarray(calibration_pred, dtype=float))
    selected = np.zeros(len(test_pred), dtype=bool)
    thresholds = np.full(len(test_pred), np.nan, dtype=float)

    for i, score in enumerate(np.asarray(test_pred, dtype=float)):
        recent = np.asarray(history[-ROLLING_SCORE_EVENTS:], dtype=float)
        threshold = float(np.quantile(recent, ADAPTIVE_QUANTILE))
        thresholds[i] = threshold
        selected[i] = bool(score >= threshold)
        # Current score becomes historical only after today's decision is made.
        history.append(float(score))

    return selected, thresholds


def _realize_delayed(
    selected: np.ndarray,
    test: np.ndarray,
    raw_indices: np.ndarray,
    entry_candidate: np.ndarray,
    n_rows: int,
) -> tuple[np.ndarray, int]:
    signal_positions = np.flatnonzero(selected)
    executed_by_raw: dict[int, float] = {}

    for pos in signal_positions:
        signal_raw = int(raw_indices[test[pos]])
        entry_raw = _first_delayed_eligible_entry(signal_raw, entry_candidate, n_rows)
        if entry_raw is None or entry_raw in executed_by_raw:
            continue
        end = entry_raw + HORIZON - 1
        executed_by_raw[entry_raw] = _actual_entry_return(entry_raw, end)

    return np.asarray(list(executed_by_raw.values()), dtype=float), int(len(signal_positions))


def _metric_row(returns: np.ndarray, signal_count: int, test_n: int) -> dict[str, float]:
    execution_count = int(len(returns))
    return {
        "signal_count": float(signal_count),
        "execution_count": float(execution_count),
        "coverage": float(execution_count / test_n),
        "conversion": float(execution_count / signal_count) if signal_count else float("nan"),
        "success": float(np.mean(returns > 0.0)) if execution_count else float("nan"),
        "net": float(np.mean(returns)) if execution_count else float("nan"),
    }


def _summary(name: str, rows: list[dict[str, float]]) -> None:
    valid = [row for row in rows if np.isfinite(row["success"])]
    if not valid:
        print(
            f"S1 ADAPTIVE_GATE SUMMARY gate={name} runs={len(rows)} valid_runs=0 "
            "execution_count_mean=0.000 coverage_mean=0.000000 conversion_mean=nan "
            "realized_success_mean=nan realized_net_return_mean=nan net_positive=0/0"
        )
        return

    print(
        f"S1 ADAPTIVE_GATE SUMMARY gate={name} runs={len(rows)} valid_runs={len(valid)} "
        f"execution_count_mean={np.mean([r['execution_count'] for r in rows]):.3f} "
        f"coverage_mean={np.mean([r['coverage'] for r in rows]):.6f} "
        f"conversion_mean={np.nanmean([r['conversion'] for r in rows]):.6f} "
        f"realized_success_mean={np.mean([r['success'] for r in valid]):.6f} "
        f"realized_net_return_mean={np.mean([r['net'] for r in valid]):.6f} "
        f"net_positive={int(np.sum([r['net'] > 0.0 for r in valid]))}/{len(valid)}"
    )


def main() -> None:
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    ds = make_success_dataset(df)
    folds = _event_folds(ds.raw_indices)
    events = add_strategy1_events(df).reset_index(drop=True)
    entry_candidate = events["entry_candidate"].to_numpy(dtype=bool)

    print(
        "S1 ADAPTIVE_GATE DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"samples={len(ds.success_probability)} folds={len(folds)} lookback={LOOKBACK} horizon={HORIZON} "
        f"reference_lookback={REFERENCE_LOOKBACK} purge_raw_sessions={PURGE_RAW_SESSIONS} "
        f"calibration_events={CALIBRATION_EVENTS} rolling_score_events={ROLLING_SCORE_EVENTS} "
        f"quantile={ADAPTIVE_QUANTILE:.2f} seeds={','.join(map(str, SEEDS))} no_random_split=true"
    )
    print(
        "S1 ADAPTIVE_GATE RULE "
        "fixed_baseline=calibration_Q70 "
        "adaptive=rolling_Q70_of_last_30_observed_scores "
        "current_score_added_after_decision=true labels_not_used_for_adaptation=true "
        f"delayed_entry_window=t_plus_1_to_t_plus_{ENTRY_DELAY_MAX} "
        "future_return_not_used_for_entry_day=true test_ranking_used=false test_labels_used=false"
    )

    fixed_rows: list[dict[str, float]] = []
    adaptive_rows: list[dict[str, float]] = []

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

            print(
                f"S1 ADAPTIVE_GATE FOLD_METRIC id={fold_id} seed={seed} "
                f"fixed_threshold={fixed_threshold:.6f} "
                f"adaptive_threshold_first={adaptive_thresholds[0]:.6f} "
                f"adaptive_threshold_last={adaptive_thresholds[-1]:.6f} "
                f"fixed_signals={fixed_signals}/{len(test)} fixed_executions={int(fixed_row['execution_count'])}/{len(test)} "
                f"fixed_coverage={fixed_row['coverage']:.6f} fixed_success={_fmt(fixed_row['success'])} "
                f"fixed_net_return={_fmt(fixed_row['net'])} "
                f"adaptive_signals={adaptive_signals}/{len(test)} adaptive_executions={int(adaptive_row['execution_count'])}/{len(test)} "
                f"adaptive_coverage={adaptive_row['coverage']:.6f} adaptive_success={_fmt(adaptive_row['success'])} "
                f"adaptive_net_return={_fmt(adaptive_row['net'])}"
            )

    _summary("fixed_Q70", fixed_rows)
    _summary("adaptive_rolling_Q70", adaptive_rows)
    print("S1 ADAPTIVE_GATE PASS")


if __name__ == "__main__":
    main()

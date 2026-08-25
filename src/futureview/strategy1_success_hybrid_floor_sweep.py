from __future__ import annotations

import numpy as np
import torch

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_success_adaptive_gate import (
    ADAPTIVE_QUANTILE,
    ROLLING_SCORE_EVENTS,
    _metric_row,
    _realize_delayed,
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

FLOOR_QUANTILES = (0.50, 0.55, 0.60, 0.65)


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


def _hybrid_mask_for_floor(
    calibration_pred: np.ndarray,
    test_pred: np.ndarray,
    floor_quantile: float,
) -> tuple[np.ndarray, np.ndarray, float]:
    history = list(np.asarray(calibration_pred, dtype=float))
    calibration = np.asarray(calibration_pred, dtype=float)
    floor = float(np.quantile(calibration, floor_quantile))
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


def _summary(q: float, rows: list[dict[str, float]]) -> None:
    valid = [r for r in rows if np.isfinite(r["success"])]
    if not valid:
        print(
            f"S1 HYBRID_FLOOR_SWEEP SUMMARY floor_quantile={q:.2f} runs={len(rows)} valid_runs=0 "
            "execution_count_mean=0.000 coverage_mean=0.000000 conversion_mean=nan "
            "realized_success_mean=nan realized_net_return_mean=nan net_positive=0/0"
        )
        return

    print(
        f"S1 HYBRID_FLOOR_SWEEP SUMMARY floor_quantile={q:.2f} runs={len(rows)} valid_runs={len(valid)} "
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
        "S1 HYBRID_FLOOR_SWEEP DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"samples={len(ds.success_probability)} folds={len(folds)} lookback={LOOKBACK} horizon={HORIZON} "
        f"reference_lookback={REFERENCE_LOOKBACK} purge_raw_sessions={PURGE_RAW_SESSIONS} "
        f"calibration_events={CALIBRATION_EVENTS} rolling_score_events={ROLLING_SCORE_EVENTS} "
        f"adaptive_quantile={ADAPTIVE_QUANTILE:.2f} "
        f"floor_quantiles={','.join(f'{q:.2f}' for q in FLOOR_QUANTILES)} "
        f"seeds={','.join(map(str, SEEDS))} no_random_split=true"
    )
    print(
        "S1 HYBRID_FLOOR_SWEEP RULE "
        "hybrid=max(rolling_Q70,calibration_floor_quantile) "
        "current_score_added_after_decision=true labels_not_used_for_adaptation=true "
        "floor_uses_historical_calibration_only=true "
        f"delayed_entry_window=t_plus_1_to_t_plus_{ENTRY_DELAY_MAX} "
        "future_return_not_used_for_entry_day=true test_ranking_used=false test_labels_used=false"
    )

    rows: dict[float, list[dict[str, float]]] = {q: [] for q in FLOOR_QUANTILES}

    for fold_id, fold in enumerate(folds, start=1):
        outer_train, test = fold.train, fold.test
        model_train, calibration = _calibration_split(outer_train, ds.raw_indices)
        y_model_train = ds.success_probability[model_train]
        x_eval = torch.cat([ds.x[calibration].cpu(), ds.x[test].cpu()], dim=0)

        for seed in SEEDS:
            pred_eval = _fit(ds.x[model_train].cpu(), y_model_train, x_eval, seed=seed)
            calibration_pred = pred_eval[: len(calibration)]
            test_pred = pred_eval[len(calibration) :]

            for q in FLOOR_QUANTILES:
                selected, thresholds, floor = _hybrid_mask_for_floor(calibration_pred, test_pred, q)
                returns, signal_count = _realize_delayed(
                    selected, test, ds.raw_indices, entry_candidate, len(events)
                )
                row = _metric_row(returns, signal_count, len(test))
                rows[q].append(row)
                print(
                    f"S1 HYBRID_FLOOR_SWEEP FOLD_METRIC id={fold_id} seed={seed} "
                    f"floor_quantile={q:.2f} floor={floor:.6f} "
                    f"threshold_last={thresholds[-1]:.6f} signals={signal_count}/{len(test)} "
                    f"executions={int(row['execution_count'])}/{len(test)} coverage={row['coverage']:.6f} "
                    f"conversion={_fmt(row['conversion'])} realized_success={_fmt(row['success'])} "
                    f"realized_net_return={_fmt(row['net'])}"
                )

    for q in FLOOR_QUANTILES:
        _summary(q, rows[q])

    print("S1 HYBRID_FLOOR_SWEEP PASS")


if __name__ == "__main__":
    main()

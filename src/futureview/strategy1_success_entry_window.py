from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_success_threshold import (
    CALIBRATION_EVENTS,
    THRESHOLD_QUANTILE,
    _calibration_split,
)
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

ENTRY_DELAY_MAX = 3


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


def _first_delayed_eligible_entry(
    signal_raw_index: int,
    entry_candidate: np.ndarray,
    n_rows: int,
) -> int | None:
    """Return the first t+1..t+3 session whose Entry stack is still valid.

    Day 0 is intentionally excluded because the signal day is already an Entry candidate;
    including it would make this experiment identical to the Day-0 baseline.
    """
    for delay in range(1, ENTRY_DELAY_MAX + 1):
        candidate = signal_raw_index + delay
        if candidate >= n_rows:
            break
        if candidate + HORIZON - 1 >= n_rows:
            continue
        if bool(entry_candidate[candidate]):
            return candidate
    return None


def main() -> None:
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    ds = make_success_dataset(df)
    folds = _event_folds(ds.raw_indices)
    events = add_strategy1_events(df).reset_index(drop=True)
    entry_candidate = events["entry_candidate"].to_numpy(dtype=bool)

    print(
        "S1 ENTRY_WINDOW DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"samples={len(ds.success_probability)} folds={len(folds)} lookback={LOOKBACK} horizon={HORIZON} "
        f"reference_lookback={REFERENCE_LOOKBACK} purge_raw_sessions={PURGE_RAW_SESSIONS} "
        f"calibration_events={CALIBRATION_EVENTS} seeds={','.join(map(str, SEEDS))} no_random_split=true"
    )
    print(
        "S1 ENTRY_WINDOW RULE "
        f"threshold_source=historical_calibration_predictions threshold_quantile={THRESHOLD_QUANTILE:.2f} "
        f"signal_day=t delayed_entry_window=t_plus_1_to_t_plus_{ENTRY_DELAY_MAX} "
        "execution=first_future_session_with_entry_stack_true day0_excluded=true "
        "future_return_not_used_for_entry_day=true test_ranking_used=false test_labels_used=false"
    )

    rows: list[dict[str, float]] = []
    for fold_id, fold in enumerate(folds, start=1):
        outer_train, test = fold.train, fold.test
        model_train, calibration = _calibration_split(outer_train, ds.raw_indices)
        y_model_train = ds.success_probability[model_train]
        x_eval = torch.cat([ds.x[calibration].cpu(), ds.x[test].cpu()], dim=0)
        day0_test_return = ds.realized_return[test]

        for seed in SEEDS:
            pred_eval = _fit(ds.x[model_train].cpu(), y_model_train, x_eval, seed=seed)
            calibration_pred = pred_eval[: len(calibration)]
            test_pred = pred_eval[len(calibration) :]
            threshold = float(np.quantile(calibration_pred, THRESHOLD_QUANTILE))
            selected = test_pred >= threshold
            signal_positions = np.flatnonzero(selected)

            day0_selected = day0_test_return[selected]
            day0_count = int(len(day0_selected))
            day0_success = float(np.mean(day0_selected > 0.0)) if day0_count else float("nan")
            day0_net = float(np.mean(day0_selected)) if day0_count else float("nan")

            executed_by_raw: dict[int, float] = {}
            delays: list[int] = []
            for pos in signal_positions:
                signal_raw = int(ds.raw_indices[test[pos]])
                entry_raw = _first_delayed_eligible_entry(signal_raw, entry_candidate, len(events))
                if entry_raw is None:
                    continue
                if entry_raw not in executed_by_raw:
                    end = entry_raw + HORIZON - 1
                    executed_by_raw[entry_raw] = _actual_entry_return(entry_raw, end)
                    delays.append(entry_raw - signal_raw)

            delayed_returns = np.asarray(list(executed_by_raw.values()), dtype=float)
            delayed_count = int(len(delayed_returns))
            delayed_success = (
                float(np.mean(delayed_returns > 0.0)) if delayed_count else float("nan")
            )
            delayed_net = float(np.mean(delayed_returns)) if delayed_count else float("nan")
            conversion = float(delayed_count / day0_count) if day0_count else float("nan")
            mean_delay = float(np.mean(delays)) if delays else float("nan")

            row = {
                "signal_count": float(day0_count),
                "day0_success": day0_success,
                "day0_net": day0_net,
                "delayed_count": float(delayed_count),
                "delayed_success": delayed_success,
                "delayed_net": delayed_net,
                "conversion": conversion,
                "mean_delay": mean_delay,
            }
            rows.append(row)
            print(
                f"S1 ENTRY_WINDOW FOLD_METRIC id={fold_id} seed={seed} threshold={threshold:.6f} "
                f"signals={day0_count}/{len(test)} "
                f"day0_success={_fmt(day0_success)} day0_net_return={_fmt(day0_net)} "
                f"delayed_executions={delayed_count} delayed_conversion={_fmt(conversion)} "
                f"mean_delay_sessions={_fmt(mean_delay)} "
                f"delayed_success={_fmt(delayed_success)} delayed_net_return={_fmt(delayed_net)}"
            )

    valid_day0 = [r for r in rows if np.isfinite(r["day0_success"])]
    valid_delayed = [r for r in rows if np.isfinite(r["delayed_success"])]
    if not valid_day0:
        raise RuntimeError("Q80 baseline selected no OOS signals")
    if not valid_delayed:
        raise RuntimeError("Q80 +3-session delayed window produced no OOS executions")

    print(
        "S1 ENTRY_WINDOW SUMMARY "
        f"ticker={TICKER} runs={len(rows)} day0_valid_runs={len(valid_day0)} "
        f"delayed_valid_runs={len(valid_delayed)} "
        f"signal_count_mean={np.mean([r['signal_count'] for r in rows]):.3f} "
        f"delayed_execution_count_mean={np.mean([r['delayed_count'] for r in rows]):.3f} "
        f"delayed_conversion_mean={np.nanmean([r['conversion'] for r in rows]):.6f} "
        f"mean_delay_sessions={np.nanmean([r['mean_delay'] for r in rows]):.6f} "
        f"day0_success_mean={np.mean([r['day0_success'] for r in valid_day0]):.6f} "
        f"delayed_success_mean={np.mean([r['delayed_success'] for r in valid_delayed]):.6f} "
        f"day0_net_return_mean={np.mean([r['day0_net'] for r in valid_day0]):.6f} "
        f"delayed_net_return_mean={np.mean([r['delayed_net'] for r in valid_delayed]):.6f}"
    )
    print("S1 ENTRY_WINDOW PASS")


if __name__ == "__main__":
    main()

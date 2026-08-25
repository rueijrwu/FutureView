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

THRESHOLD_QUANTILES = (0.50, 0.60, 0.70, 0.80)


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


def main() -> None:
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    ds = make_success_dataset(df)
    folds = _event_folds(ds.raw_indices)
    events = add_strategy1_events(df).reset_index(drop=True)
    entry_candidate = events["entry_candidate"].to_numpy(dtype=bool)

    print(
        "S1 THRESHOLD_SWEEP DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"samples={len(ds.success_probability)} folds={len(folds)} lookback={LOOKBACK} horizon={HORIZON} "
        f"reference_lookback={REFERENCE_LOOKBACK} purge_raw_sessions={PURGE_RAW_SESSIONS} "
        f"calibration_events={CALIBRATION_EVENTS} seeds={','.join(map(str, SEEDS))} no_random_split=true"
    )
    print(
        "S1 THRESHOLD_SWEEP RULE "
        "threshold_source=historical_calibration_predictions "
        f"quantiles={','.join(f'{q:.2f}' for q in THRESHOLD_QUANTILES)} "
        f"signal_day=t delayed_entry_window=t_plus_1_to_t_plus_{ENTRY_DELAY_MAX} "
        "execution=first_future_session_with_entry_stack_true day0_excluded=true "
        "future_return_not_used_for_entry_day=true test_ranking_used=false test_labels_used=false"
    )

    rows: dict[float, list[dict[str, float]]] = {q: [] for q in THRESHOLD_QUANTILES}

    for fold_id, fold in enumerate(folds, start=1):
        outer_train, test = fold.train, fold.test
        model_train, calibration = _calibration_split(outer_train, ds.raw_indices)
        y_model_train = ds.success_probability[model_train]
        x_eval = torch.cat([ds.x[calibration].cpu(), ds.x[test].cpu()], dim=0)

        for seed in SEEDS:
            pred_eval = _fit(ds.x[model_train].cpu(), y_model_train, x_eval, seed=seed)
            calibration_pred = pred_eval[: len(calibration)]
            test_pred = pred_eval[len(calibration) :]

            for q in THRESHOLD_QUANTILES:
                threshold = float(np.quantile(calibration_pred, q))
                signal_positions = np.flatnonzero(test_pred >= threshold)
                signal_count = int(len(signal_positions))

                executed_by_raw: dict[int, float] = {}
                for pos in signal_positions:
                    signal_raw = int(ds.raw_indices[test[pos]])
                    entry_raw = _first_delayed_eligible_entry(signal_raw, entry_candidate, len(events))
                    if entry_raw is None or entry_raw in executed_by_raw:
                        continue
                    end = entry_raw + HORIZON - 1
                    executed_by_raw[entry_raw] = _actual_entry_return(entry_raw, end)

                delayed_returns = np.asarray(list(executed_by_raw.values()), dtype=float)
                execution_count = int(len(delayed_returns))
                coverage = float(execution_count / len(test))
                conversion = float(execution_count / signal_count) if signal_count else float("nan")
                success = float(np.mean(delayed_returns > 0.0)) if execution_count else float("nan")
                net = float(np.mean(delayed_returns)) if execution_count else float("nan")

                rows[q].append(
                    {
                        "signal_count": float(signal_count),
                        "execution_count": float(execution_count),
                        "coverage": coverage,
                        "conversion": conversion,
                        "success": success,
                        "net": net,
                    }
                )
                print(
                    f"S1 THRESHOLD_SWEEP FOLD_METRIC id={fold_id} seed={seed} quantile={q:.2f} "
                    f"threshold={threshold:.6f} signals={signal_count}/{len(test)} "
                    f"executions={execution_count}/{len(test)} coverage={coverage:.6f} "
                    f"conversion={_fmt(conversion)} realized_success={_fmt(success)} "
                    f"realized_net_return={_fmt(net)}"
                )

    for q in THRESHOLD_QUANTILES:
        qrows = rows[q]
        valid = [r for r in qrows if np.isfinite(r["success"])]
        if not valid:
            print(
                f"S1 THRESHOLD_SWEEP SUMMARY quantile={q:.2f} runs={len(qrows)} valid_runs=0 "
                "execution_count_mean=0.000 coverage_mean=0.000000 conversion_mean=nan "
                "realized_success_mean=nan realized_net_return_mean=nan net_positive=0/0"
            )
            continue
        print(
            f"S1 THRESHOLD_SWEEP SUMMARY quantile={q:.2f} runs={len(qrows)} valid_runs={len(valid)} "
            f"execution_count_mean={np.mean([r['execution_count'] for r in qrows]):.3f} "
            f"coverage_mean={np.mean([r['coverage'] for r in qrows]):.6f} "
            f"conversion_mean={np.nanmean([r['conversion'] for r in qrows]):.6f} "
            f"realized_success_mean={np.mean([r['success'] for r in valid]):.6f} "
            f"realized_net_return_mean={np.mean([r['net'] for r in valid]):.6f} "
            f"net_positive={int(np.sum([r['net'] > 0.0 for r in valid]))}/{len(valid)}"
        )

    print("S1 THRESHOLD_SWEEP PASS")


if __name__ == "__main__":
    main()

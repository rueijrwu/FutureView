from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from .data import download_spy_daily
from .datasets import build_windows
from .features import make_causal_features
from .strategy1 import add_strategy1_events
from .strategy1_oos_portfolio import (
    GATE_QUANTILE,
    MIN_EXPANDING_TRAIN,
    PURGE,
    SEEDS,
    SLIDING_TRAIN,
    TARGET_HORIZON,
    TARGET_INDEX,
    TEST_SIZE,
    _fit_cnn_predict,
    _fmt,
    _hindsight_upper,
    _portfolio_metrics,
    _select_sequential,
)
from .strategy1_summary_baseline import _fit_ridge, _summary_features
from .strategy1_targets import STRATEGY1_TARGET_COLUMNS, make_strategy1_targets
from .walkforward import purged_expanding_walk_forward

RECENT_OOS_WINDOW = 60


def _recent_oos_rank_gate(
    scores: np.ndarray,
    *,
    window: int = RECENT_OOS_WINDOW,
    quantile: float = GATE_QUANTILE,
) -> tuple[np.ndarray, np.ndarray]:
    """Gate each score using only the most recent prior OOS scores.

    The first ``window`` OOS scores are a strict warm-up and cannot pass the gate.
    Thereafter score j is ranked only against scores[j-window:j]. The current score
    and all future scores are excluded.
    """
    scores = np.asarray(scores, dtype=float)
    if scores.ndim != 1:
        raise ValueError("recent-rank scores must be one-dimensional")
    if window <= 0:
        raise ValueError("window must be positive")
    if not (0.0 < quantile < 1.0):
        raise ValueError("quantile must be in (0, 1)")

    percentiles = np.full(len(scores), np.nan, dtype=float)
    gates = np.zeros(len(scores), dtype=bool)
    for i in range(window, len(scores)):
        history = scores[i - window : i]
        percentile = float(np.mean(history <= scores[i]))
        percentiles[i] = percentile
        gates[i] = percentile >= quantile
    return gates, percentiles


def main() -> None:
    torch.set_num_threads(2)
    df = download_spy_daily(period="3y")
    events = add_strategy1_events(df).reset_index(drop=True)
    features = make_causal_features(df)
    targets = make_strategy1_targets(df)
    windows = build_windows(features, targets, lookback=50, target_columns=STRATEGY1_TARGET_COLUMNS)
    dates = pd.DatetimeIndex(pd.to_datetime(windows.dates))
    y = windows.y.numpy().astype(float)[:, TARGET_INDEX]
    summary_x = _summary_features(windows.x)

    all_folds = purged_expanding_walk_forward(
        len(y), min_train=MIN_EXPANDING_TRAIN, test_size=TEST_SIZE, purge=PURGE, step=TEST_SIZE
    )
    folds = tuple(f for f in all_folds if len(f.test) == TEST_SIZE)
    if not folds:
        raise RuntimeError("no complete common OOS folds")

    event_index = {pd.Timestamp(d): i for i, d in enumerate(pd.to_datetime(events["date"]))}
    cnn_absolute_gate: dict[int, bool] = {}
    ridge_gate: dict[int, bool] = {}
    ordered_oos: list[tuple[int, int, float]] = []

    print(
        f"S1 OOS_RECENT_RANK DATA windows={len(y)} folds={len(folds)} horizon={TARGET_HORIZON} "
        f"train=SLIDING_{SLIDING_TRAIN} gate_quantile={GATE_QUANTILE:.2f} "
        f"recent_oos_window={RECENT_OOS_WINDOW} first={dates[0].date()} last={dates[-1].date()} "
        f"seeds={','.join(map(str, SEEDS))}"
    )
    print(
        "S1 OOS_RECENT_RANK RULE prediction_at_close_t_gates_entry1_at_t_plus_1 "
        "rank_history=last_60_prior_oos_predictions global_oos_warmup=60 "
        "training_predictions_excluded=true current_and_future_oos_excluded=true "
        "campaign_horizon=30_sessions flat_only=true overlapping_capital=false"
    )

    fold_payloads: list[dict[str, object]] = []
    for fold_id, fold in enumerate(folds, start=1):
        test_idx = fold.test
        train_end = int(fold.train[-1]) + 1
        train_idx = np.arange(train_end - SLIDING_TRAIN, train_end, dtype=int)
        if train_idx[0] < 0:
            raise RuntimeError("sliding train window begins before dataset")

        x_train = windows.x[train_idx].cpu()
        y_train_all = windows.y[train_idx].cpu()
        x_joined = torch.cat([windows.x[train_idx].cpu(), windows.x[test_idx].cpu()], dim=0)

        cnn_preds = [
            _fit_cnn_predict(x_train, y_train_all, x_joined, seed=seed) for seed in SEEDS
        ]
        cnn_ensemble = np.mean(np.vstack(cnn_preds), axis=0)
        cnn_train = cnn_ensemble[: len(train_idx)]
        cnn_test = cnn_ensemble[len(train_idx) :]
        cnn_threshold = float(np.quantile(cnn_train, GATE_QUANTILE))
        cnn_absolute_high = cnn_test >= cnn_threshold

        ridge_train = _fit_ridge(summary_x[train_idx], y[train_idx], summary_x[train_idx])
        ridge_test = _fit_ridge(summary_x[train_idx], y[train_idx], summary_x[test_idx])
        ridge_threshold = float(np.quantile(ridge_train, GATE_QUANTILE))
        ridge_high = ridge_test >= ridge_threshold

        for local, window_idx in enumerate(test_idx):
            ordered_oos.append((fold_id, int(window_idx), float(cnn_test[local])))
            pred_date = pd.Timestamp(dates[window_idx])
            if pred_date not in event_index:
                raise RuntimeError(f"prediction date missing from event frame: {pred_date}")
            entry_idx = event_index[pred_date] + 1
            if entry_idx < len(events):
                cnn_absolute_gate[entry_idx] = bool(cnn_absolute_high[local])
                ridge_gate[entry_idx] = bool(ridge_high[local])

        fold_payloads.append(
            {
                "fold_id": fold_id,
                "train_idx": train_idx,
                "test_idx": test_idx,
                "cnn_threshold": cnn_threshold,
                "cnn_absolute_high": cnn_absolute_high,
                "ridge_threshold": ridge_threshold,
                "ridge_high": ridge_high,
            }
        )

    ordered_oos.sort(key=lambda row: row[1])
    oos_scores = np.asarray([row[2] for row in ordered_oos], dtype=float)
    recent_high, recent_percentiles = _recent_oos_rank_gate(oos_scores)
    recent_gate: dict[int, bool] = {}
    recent_by_window: dict[int, tuple[bool, float]] = {}
    for i, (_, window_idx, _) in enumerate(ordered_oos):
        pred_date = pd.Timestamp(dates[window_idx])
        entry_idx = event_index[pred_date] + 1
        pct = float(recent_percentiles[i]) if np.isfinite(recent_percentiles[i]) else float("nan")
        recent_by_window[window_idx] = (bool(recent_high[i]), pct)
        if entry_idx < len(events):
            recent_gate[entry_idx] = bool(recent_high[i])

    for payload in fold_payloads:
        fold_id = int(payload["fold_id"])
        train_idx = payload["train_idx"]
        test_idx = payload["test_idx"]
        absolute = payload["cnn_absolute_high"]
        ridge_high = payload["ridge_high"]
        fold_recent = np.asarray([recent_by_window[int(i)][0] for i in test_idx], dtype=bool)
        fold_pcts = np.asarray([recent_by_window[int(i)][1] for i in test_idx], dtype=float)
        eligible = np.isfinite(fold_pcts)
        pct_mean = float(np.mean(fold_pcts[eligible])) if eligible.any() else float("nan")
        print(
            f"S1 OOS_RECENT_RANK FOLD id={fold_id} "
            f"train_first={dates[train_idx[0]].date()} train_last={dates[train_idx[-1]].date()} "
            f"test_first={dates[test_idx[0]].date()} test_last={dates[test_idx[-1]].date()} "
            f"cnn_absolute_threshold={float(payload['cnn_threshold']):.6f} "
            f"cnn_absolute_signal_rate={np.mean(absolute):.3f} "
            f"cnn_recent_rank_signal_rate={np.mean(fold_recent):.3f} "
            f"cnn_recent_rank_eligible={int(eligible.sum())}/{len(test_idx)} "
            f"cnn_recent_rank_percentile_mean={_fmt(pct_mean)} "
            f"ridge_threshold={float(payload['ridge_threshold']):.6f} "
            f"ridge_signal_rate={np.mean(ridge_high):.3f}"
        )

    first_test_window = int(folds[0].test[0])
    last_test_window = int(folds[-1].test[-1])
    first_pred_event = event_index[pd.Timestamp(dates[first_test_window])]
    last_pred_event = event_index[pd.Timestamp(dates[last_test_window])]
    first_entry = first_pred_event + 1
    last_entry = last_pred_event + 1
    evaluation_start = first_pred_event
    evaluation_end = min(last_entry + TARGET_HORIZON - 1, len(events) - 1)

    strategies = {
        "ALWAYS_ON": _select_sequential(events, first_entry, last_entry, gate=None),
        "SUMMARY_RIDGE_FILTERED": _select_sequential(events, first_entry, last_entry, gate=ridge_gate),
        "CNN_ABSOLUTE_TRAIN_P80": _select_sequential(
            events, first_entry, last_entry, gate=cnn_absolute_gate
        ),
        "CNN_RECENT_OOS_RANK60_P80": _select_sequential(
            events, first_entry, last_entry, gate=recent_gate
        ),
        "HINDSIGHT_ENTRY_UPPER": _hindsight_upper(events, first_entry, last_entry),
    }

    print(
        f"S1 OOS_RECENT_RANK PERIOD signal_first={events.at[evaluation_start, 'date'].date()} "
        f"signal_last={events.at[last_pred_event, 'date'].date()} "
        f"entry_first={events.at[first_entry, 'date'].date()} entry_last={events.at[last_entry, 'date'].date()} "
        f"evaluation_end={events.at[evaluation_end, 'date'].date()}"
    )

    for name, campaigns in strategies.items():
        m = _portfolio_metrics(events, campaigns, evaluation_start, evaluation_end)
        print(
            f"S1 OOS_RECENT_RANK RESULT model={name} campaigns={int(m['campaigns'])} "
            f"total_return={m['total_return']:.6f} annualized_return={m['annualized_return']:.6f} "
            f"max_drawdown={m['max_drawdown']:.6f} win_rate={_fmt(m['win_rate'])} "
            f"avg_campaign_return={_fmt(m['avg_campaign_return'])} "
            f"exposure_days={m['exposure_days']:.6f} holding_days={m['holding_days']:.0f} "
            f"exposure_ratio={m['exposure_ratio']:.6f} "
            f"return_per_exposure_day={_fmt(m['return_per_exposure_day'])}"
        )
        for k, c in enumerate(campaigns, start=1):
            print(
                f"S1 OOS_RECENT_RANK CAMPAIGN model={name} id={k} "
                f"start={events.at[c.start, 'date'].date()} end={events.at[c.end, 'date'].date()} "
                f"return={c.run.final_return:.6f} exposure_days={c.run.exposure_days:.6f} "
                f"entries={c.run.entries_used} partial_exit={int(c.run.partial_exit_used)} "
                f"full_exit={int(c.run.full_exit_used)} horizon_exit={int(c.run.horizon_exit_used)}"
            )

    print("S1 OOS_RECENT_RANK PASS")


if __name__ == "__main__":
    main()

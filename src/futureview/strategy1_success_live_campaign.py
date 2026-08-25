from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from . import strategy1_reference_distribution as base
from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import _simulate_from_start, add_strategy1_events
from .strategy1_success_adaptive_gate import ADAPTIVE_QUANTILE, ROLLING_SCORE_EVENTS
from .strategy1_success_entry_window import ENTRY_DELAY_MAX, _first_delayed_eligible_entry
from .strategy1_success_threshold import CALIBRATION_EVENTS, _calibration_split
from .strategy1_success_training import (
    ADDON2_SPACING_TOLERANCE,
    DATA_PERIOD,
    HORIZON,
    LOOKBACK,
    PURGE_RAW_SESSIONS,
    REFERENCE_LOOKBACK,
    SEEDS,
    TICKER,
    _actual_entry_return,
    _deterministic_addon_indices,
    _event_folds,
    _fit,
    make_success_dataset,
)

LOCKED_FLOOR_QUANTILE = 0.55


@dataclass(frozen=True)
class Campaign:
    signal_raw: int
    entry_raw: int
    exit_raw: int
    final_return: float


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


def _campaign_run(events, entry_raw: int):
    horizon_end = entry_raw + HORIZON - 1
    addon_indices = _deterministic_addon_indices(entry_raw)
    addon_levels = tuple((i, float(events.at[i, "close"])) for i in addon_indices)
    run = _simulate_from_start(
        events,
        entry_raw,
        horizon_end,
        addon_levels=addon_levels,
        addon2_spacing_tolerance=ADDON2_SPACING_TOLERANCE,
    )
    if not run.actions:
        raise RuntimeError("live campaign produced no Strategy 1 actions")
    fast_return = _actual_entry_return(entry_raw, horizon_end)
    if not np.isclose(float(run.final_return), fast_return, atol=1e-10, rtol=1e-10):
        raise RuntimeError(
            f"deterministic campaign mismatch entry={entry_raw}: "
            f"run={run.final_return:.12f} fast={fast_return:.12f}"
        )
    return run


def _live_campaigns(
    calibration_pred: np.ndarray,
    test_pred: np.ndarray,
    test: np.ndarray,
    raw_indices: np.ndarray,
    entry_candidate: np.ndarray,
    events,
) -> tuple[list[Campaign], int, int, int]:
    """Run a causal flat/pending/in-campaign state machine over one OOS fold."""
    history = list(np.asarray(calibration_pred, dtype=float))
    floor = float(np.quantile(np.asarray(calibration_pred, dtype=float), LOCKED_FLOOR_QUANTILE))
    busy_until = -1
    campaigns: list[Campaign] = []
    accepted_signals = 0
    ignored_busy_signals = 0
    expired_pending = 0

    for local, score in enumerate(np.asarray(test_pred, dtype=float)):
        signal_raw = int(raw_indices[test[local]])
        recent = np.asarray(history[-ROLLING_SCORE_EVENTS:], dtype=float)
        rolling = float(np.quantile(recent, ADAPTIVE_QUANTILE))
        threshold = max(rolling, floor)
        selected = bool(score >= threshold)

        # Score becomes historical after today's decision, whether or not capital is busy.
        history.append(float(score))

        if not selected:
            continue
        if signal_raw <= busy_until:
            ignored_busy_signals += 1
            continue

        accepted_signals += 1
        entry_raw = _first_delayed_eligible_entry(signal_raw, entry_candidate, len(events))
        if entry_raw is None:
            # Reserve the pending-entry window so overlapping signals cannot create
            # multiple simultaneous chances to enter.
            busy_until = min(signal_raw + ENTRY_DELAY_MAX, len(events) - 1)
            expired_pending += 1
            continue

        run = _campaign_run(events, entry_raw)
        exit_raw = int(run.actions[-1].index)
        campaigns.append(
            Campaign(
                signal_raw=signal_raw,
                entry_raw=entry_raw,
                exit_raw=exit_raw,
                final_return=float(run.final_return),
            )
        )
        busy_until = exit_raw

    return campaigns, accepted_signals, ignored_busy_signals, expired_pending


def _metrics(campaigns: list[Campaign], test_n: int) -> dict[str, float]:
    returns = np.asarray([c.final_return for c in campaigns], dtype=float)
    compounded = float(np.prod(1.0 + returns) - 1.0) if len(returns) else 0.0
    return {
        "campaigns": float(len(campaigns)),
        "campaign_rate": float(len(campaigns) / test_n),
        "success": float(np.mean(returns > 0.0)) if len(returns) else float("nan"),
        "net": float(np.mean(returns)) if len(returns) else float("nan"),
        "compounded": compounded,
    }


def main() -> None:
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    ds = make_success_dataset(df)
    folds = _event_folds(ds.raw_indices)
    events = add_strategy1_events(df).reset_index(drop=True)
    base._prepare_worker_state(events)
    entry_candidate = events["entry_candidate"].to_numpy(dtype=bool)

    print(
        "S1 LIVE_CAMPAIGN DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"samples={len(ds.success_probability)} folds={len(folds)} lookback={LOOKBACK} horizon={HORIZON} "
        f"reference_lookback={REFERENCE_LOOKBACK} purge_raw_sessions={PURGE_RAW_SESSIONS} "
        f"calibration_events={CALIBRATION_EVENTS} rolling_score_events={ROLLING_SCORE_EVENTS} "
        f"adaptive_quantile={ADAPTIVE_QUANTILE:.2f} locked_floor_quantile={LOCKED_FLOOR_QUANTILE:.2f} "
        f"seeds={','.join(map(str, SEEDS))} no_random_split=true"
    )
    print(
        "S1 LIVE_CAMPAIGN RULE "
        "gate=max(rolling_Q70,calibration_Q55) floor_locked_before_this_backtest=true "
        "current_score_added_after_decision=true labels_not_used_for_gate=true "
        f"pending_entry_window=t_plus_1_to_t_plus_{ENTRY_DELAY_MAX} pending_blocks_new_signals=true "
        "flat_only=true overlapping_capital=false campaign_busy_until_actual_exit=true "
        "execution=deterministic_strategy1 test_ranking_used=false test_labels_used=false"
    )

    rows: list[dict[str, float]] = []
    pooled_returns: list[float] = []

    for fold_id, fold in enumerate(folds, start=1):
        model_train, calibration = _calibration_split(fold.train, ds.raw_indices)
        y_model_train = ds.success_probability[model_train]
        x_eval = torch.cat([ds.x[calibration].cpu(), ds.x[fold.test].cpu()], dim=0)

        for seed in SEEDS:
            pred_eval = _fit(ds.x[model_train].cpu(), y_model_train, x_eval, seed=seed)
            calibration_pred = pred_eval[: len(calibration)]
            test_pred = pred_eval[len(calibration) :]
            campaigns, accepted, ignored_busy, expired = _live_campaigns(
                calibration_pred,
                test_pred,
                fold.test,
                ds.raw_indices,
                entry_candidate,
                events,
            )
            m = _metrics(campaigns, len(fold.test))
            rows.append(m)
            pooled_returns.extend(c.final_return for c in campaigns)

            print(
                f"S1 LIVE_CAMPAIGN FOLD_METRIC id={fold_id} seed={seed} "
                f"accepted_signals={accepted} ignored_busy_signals={ignored_busy} expired_pending={expired} "
                f"campaigns={int(m['campaigns'])}/{len(fold.test)} campaign_rate={m['campaign_rate']:.6f} "
                f"success={_fmt(m['success'])} net_expected_return={_fmt(m['net'])} "
                f"compounded_return={m['compounded']:.6f}"
            )
            for campaign_id, c in enumerate(campaigns, start=1):
                print(
                    f"S1 LIVE_CAMPAIGN CAMPAIGN fold={fold_id} seed={seed} id={campaign_id} "
                    f"signal={events.at[c.signal_raw, 'date'].date()} "
                    f"entry={events.at[c.entry_raw, 'date'].date()} exit={events.at[c.exit_raw, 'date'].date()} "
                    f"delay={c.entry_raw - c.signal_raw} return={c.final_return:.6f}"
                )

    valid = [r for r in rows if np.isfinite(r["success"])]
    pooled = np.asarray(pooled_returns, dtype=float)
    pooled_success = float(np.mean(pooled > 0.0)) if len(pooled) else float("nan")
    pooled_net = float(np.mean(pooled)) if len(pooled) else float("nan")

    print(
        "S1 LIVE_CAMPAIGN SUMMARY "
        f"ticker={TICKER} runs={len(rows)} valid_runs={len(valid)} "
        f"campaign_count_mean={np.mean([r['campaigns'] for r in rows]):.3f} "
        f"campaign_rate_mean={np.mean([r['campaign_rate'] for r in rows]):.6f} "
        f"run_weighted_success={np.mean([r['success'] for r in valid]):.6f} "
        f"run_weighted_net_expected_return={np.mean([r['net'] for r in valid]):.6f} "
        f"run_weighted_compounded_return={np.mean([r['compounded'] for r in rows]):.6f} "
        f"pooled_campaigns={len(pooled)} pooled_success={_fmt(pooled_success)} pooled_net_expected_return={_fmt(pooled_net)} "
        f"net_positive={int(np.sum([r['net'] > 0.0 for r in valid]))}/{len(valid)}"
    )
    if not valid:
        raise RuntimeError("locked Q55 live campaign policy produced no OOS campaigns")
    print("S1 LIVE_CAMPAIGN PASS")


if __name__ == "__main__":
    main()

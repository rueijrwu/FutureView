from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch

from . import strategy1_reference_distribution as base
from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_success_adaptive_gate import ADAPTIVE_QUANTILE, ROLLING_SCORE_EVENTS
from .strategy1_success_entry_window import ENTRY_DELAY_MAX, _first_delayed_eligible_entry
from .strategy1_success_live_campaign import Campaign, LOCKED_FLOOR_QUANTILE, _campaign_run, _fmt
from .strategy1_success_threshold import CALIBRATION_EVENTS, _calibration_split
from .strategy1_success_training import (
    DATA_PERIOD,
    HORIZON,
    LOOKBACK,
    MIN_TRAIN_EVENTS,
    PURGE_RAW_SESSIONS,
    REFERENCE_LOOKBACK,
    SEEDS,
    TEST_EVENTS,
    TICKER,
    EventFold,
    _fit,
    make_success_dataset,
)

EXPANDED_TEST_EVENTS = 20


@dataclass
class FoldCounters:
    accepted_signals: int = 0
    ignored_busy_signals: int = 0
    expired_pending: int = 0
    campaigns: int = 0


def _expanded_event_folds(raw_indices: np.ndarray) -> tuple[EventFold, ...]:
    """More granular chronological OOS blocks; policy and purge remain unchanged."""
    raw_indices = np.asarray(raw_indices, dtype=int)
    folds: list[EventFold] = []
    for test_start in range(MIN_TRAIN_EVENTS, len(raw_indices), EXPANDED_TEST_EVENTS):
        test = np.arange(test_start, min(test_start + EXPANDED_TEST_EVENTS, len(raw_indices)), dtype=int)
        if len(test) != EXPANDED_TEST_EVENTS:
            continue
        cutoff = int(raw_indices[test[0]]) - PURGE_RAW_SESSIONS - 1
        train = np.where(raw_indices[:test_start] <= cutoff)[0]
        if len(train) < MIN_TRAIN_EVENTS:
            continue
        folds.append(EventFold(train=train, test=test))
    if not folds:
        raise RuntimeError("no expanded chronological OOS folds")
    return tuple(folds)


def _prepare_predictions(ds, folds: tuple[EventFold, ...], seed: int):
    prepared = []
    for fold_id, fold in enumerate(folds, start=1):
        model_train, calibration = _calibration_split(fold.train, ds.raw_indices)
        y_model_train = ds.success_probability[model_train]
        x_eval = torch.cat([ds.x[calibration].cpu(), ds.x[fold.test].cpu()], dim=0)
        pred_eval = _fit(ds.x[model_train].cpu(), y_model_train, x_eval, seed=seed)
        calibration_pred = pred_eval[: len(calibration)]
        test_pred = pred_eval[len(calibration) :]
        prepared.append((fold_id, fold, calibration_pred, test_pred, model_train, calibration))
    return prepared


def _walk_seed(ds, prepared, entry_candidate: np.ndarray, events, seed: int):
    busy_until = -1
    all_campaigns: list[Campaign] = []
    counters: dict[int, FoldCounters] = {}

    for fold_id, fold, calibration_pred, test_pred, model_train, calibration in prepared:
        history = list(np.asarray(calibration_pred, dtype=float))
        floor = float(np.quantile(np.asarray(calibration_pred, dtype=float), LOCKED_FLOOR_QUANTILE))
        c = FoldCounters()
        counters[fold_id] = c

        inner_gap = int(ds.raw_indices[calibration[0]] - ds.raw_indices[model_train[-1]] - 1)
        outer_gap = int(ds.raw_indices[fold.test[0]] - ds.raw_indices[fold.train[-1]] - 1)

        for local, score in enumerate(np.asarray(test_pred, dtype=float)):
            signal_raw = int(ds.raw_indices[fold.test[local]])
            recent = np.asarray(history[-ROLLING_SCORE_EVENTS:], dtype=float)
            rolling = float(np.quantile(recent, ADAPTIVE_QUANTILE))
            threshold = max(rolling, floor)
            selected = bool(score >= threshold)
            history.append(float(score))

            if not selected:
                continue
            if signal_raw <= busy_until:
                c.ignored_busy_signals += 1
                continue

            c.accepted_signals += 1
            entry_raw = _first_delayed_eligible_entry(signal_raw, entry_candidate, len(events))
            if entry_raw is None:
                busy_until = min(signal_raw + ENTRY_DELAY_MAX, len(events) - 1)
                c.expired_pending += 1
                continue

            run = _campaign_run(events, entry_raw)
            exit_raw = int(run.actions[-1].index)
            campaign = Campaign(
                signal_raw=signal_raw,
                entry_raw=entry_raw,
                exit_raw=exit_raw,
                final_return=float(run.final_return),
            )
            all_campaigns.append(campaign)
            c.campaigns += 1
            busy_until = exit_raw

        fold_returns = np.asarray(
            [x.final_return for x in all_campaigns if int(ds.raw_indices[fold.test[0]]) <= x.signal_raw <= int(ds.raw_indices[fold.test[-1]])],
            dtype=float,
        )
        success = float(np.mean(fold_returns > 0.0)) if len(fold_returns) else float("nan")
        net = float(fold_returns.mean()) if len(fold_returns) else float("nan")
        compounded = float(np.prod(1.0 + fold_returns) - 1.0) if len(fold_returns) else 0.0
        print(
            f"S1 LIVE_CAMPAIGN_EXPANDED FOLD_METRIC id={fold_id} seed={seed} "
            f"test_first={pd.Timestamp(ds.dates[fold.test[0]]).date()} "
            f"test_last={pd.Timestamp(ds.dates[fold.test[-1]]).date()} test_n={len(fold.test)} "
            f"model_train_n={len(model_train)} calibration_n={len(calibration)} "
            f"inner_gap={inner_gap} outer_gap={outer_gap} floor={floor:.6f} "
            f"accepted_signals={c.accepted_signals} ignored_busy_signals={c.ignored_busy_signals} "
            f"expired_pending={c.expired_pending} campaigns={c.campaigns}/{len(fold.test)} "
            f"success={_fmt(success)} net_expected_return={_fmt(net)} compounded_return={compounded:.6f}"
        )

    return all_campaigns, counters


def main() -> None:
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    ds = make_success_dataset(df)
    folds = _expanded_event_folds(ds.raw_indices)
    events = add_strategy1_events(df).reset_index(drop=True)
    base._prepare_worker_state(events)
    entry_candidate = events["entry_candidate"].to_numpy(dtype=bool)

    print(
        "S1 LIVE_CAMPAIGN_EXPANDED DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"samples={len(ds.success_probability)} folds={len(folds)} original_test_events={TEST_EVENTS} "
        f"expanded_test_events={EXPANDED_TEST_EVENTS} lookback={LOOKBACK} horizon={HORIZON} "
        f"reference_lookback={REFERENCE_LOOKBACK} purge_raw_sessions={PURGE_RAW_SESSIONS} "
        f"calibration_events={CALIBRATION_EVENTS} rolling_score_events={ROLLING_SCORE_EVENTS} "
        f"adaptive_quantile={ADAPTIVE_QUANTILE:.2f} locked_floor_quantile={LOCKED_FLOOR_QUANTILE:.2f} "
        f"seeds={','.join(map(str, SEEDS))} no_random_split=true"
    )
    print(
        "S1 LIVE_CAMPAIGN_EXPANDED RULE "
        "policy_locked=true gate=max(rolling_Q70,calibration_Q55) "
        "evaluation_change_only=outer_test_block_40_to_20_events use_all_eligible_blocks=true "
        "busy_state_carries_across_fold_boundaries=true calibration_resets_with_each_refit=true "
        "current_score_added_after_decision=true labels_not_used_for_gate=true "
        f"pending_entry_window=t_plus_1_to_t_plus_{ENTRY_DELAY_MAX} pending_blocks_new_signals=true "
        "flat_only=true overlapping_capital=false campaign_busy_until_actual_exit=true "
        "execution=deterministic_strategy1 test_ranking_used=false test_labels_used=false"
    )

    pooled_returns: list[float] = []
    seed_summaries = []
    unique_campaign_keys: set[tuple[int, int, int]] = set()

    for seed in SEEDS:
        prepared = _prepare_predictions(ds, folds, seed)
        campaigns, counters = _walk_seed(ds, prepared, entry_candidate, events, seed)
        returns = np.asarray([c.final_return for c in campaigns], dtype=float)
        pooled_returns.extend(returns.tolist())
        unique_campaign_keys.update((c.signal_raw, c.entry_raw, c.exit_raw) for c in campaigns)
        accepted = sum(c.accepted_signals for c in counters.values())
        ignored = sum(c.ignored_busy_signals for c in counters.values())
        expired = sum(c.expired_pending for c in counters.values())
        success = float(np.mean(returns > 0.0)) if len(returns) else float("nan")
        net = float(returns.mean()) if len(returns) else float("nan")
        compounded = float(np.prod(1.0 + returns) - 1.0) if len(returns) else 0.0
        seed_summaries.append((len(campaigns), success, net, compounded, accepted, ignored, expired))
        print(
            f"S1 LIVE_CAMPAIGN_EXPANDED SEED_SUMMARY seed={seed} campaigns={len(campaigns)} "
            f"accepted_signals={accepted} ignored_busy_signals={ignored} expired_pending={expired} "
            f"success={_fmt(success)} net_expected_return={_fmt(net)} compounded_return={compounded:.6f}"
        )
        for campaign_id, c in enumerate(campaigns, start=1):
            print(
                f"S1 LIVE_CAMPAIGN_EXPANDED CAMPAIGN seed={seed} id={campaign_id} "
                f"signal={events.at[c.signal_raw, 'date'].date()} entry={events.at[c.entry_raw, 'date'].date()} "
                f"exit={events.at[c.exit_raw, 'date'].date()} delay={c.entry_raw - c.signal_raw} "
                f"return={c.final_return:.6f}"
            )

    pooled = np.asarray(pooled_returns, dtype=float)
    valid_seed = [s for s in seed_summaries if np.isfinite(s[1])]
    pooled_success = float(np.mean(pooled > 0.0)) if len(pooled) else float("nan")
    pooled_net = float(pooled.mean()) if len(pooled) else float("nan")
    print(
        "S1 LIVE_CAMPAIGN_EXPANDED SUMMARY "
        f"ticker={TICKER} folds={len(folds)} seeds={len(SEEDS)} valid_seeds={len(valid_seed)} "
        f"oos_first={pd.Timestamp(ds.dates[folds[0].test[0]]).date()} "
        f"oos_last={pd.Timestamp(ds.dates[folds[-1].test[-1]]).date()} "
        f"campaigns_per_seed_mean={np.mean([s[0] for s in seed_summaries]):.3f} "
        f"seed_weighted_success={np.mean([s[1] for s in valid_seed]):.6f} "
        f"seed_weighted_net_expected_return={np.mean([s[2] for s in valid_seed]):.6f} "
        f"seed_weighted_compounded_return={np.mean([s[3] for s in seed_summaries]):.6f} "
        f"pooled_campaigns={len(pooled)} unique_campaign_paths={len(unique_campaign_keys)} "
        f"pooled_success={_fmt(pooled_success)} pooled_net_expected_return={_fmt(pooled_net)}"
    )
    if not valid_seed:
        raise RuntimeError("locked Q55 expanded OOS policy produced no campaigns")
    print("S1 LIVE_CAMPAIGN_EXPANDED PASS")


if __name__ == "__main__":
    main()

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch

from . import strategy1_reference_distribution as base
from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_success_entry_window import ENTRY_DELAY_MAX, _first_delayed_eligible_entry
from .strategy1_success_live_campaign import Campaign, LOCKED_FLOOR_QUANTILE, _campaign_run, _fmt
from .strategy1_success_live_campaign_expanded_oos import (
    EXPANDED_TEST_EVENTS,
    _expanded_event_folds,
    _prepare_predictions,
    _walk_seed,
)
from .strategy1_success_training import (
    DATA_PERIOD,
    HORIZON,
    LOOKBACK,
    PURGE_RAW_SESSIONS,
    REFERENCE_LOOKBACK,
    SEEDS,
    TICKER,
    make_success_dataset,
)


@dataclass
class BaselineCounters:
    setup_signals: int = 0
    ignored_busy_signals: int = 0
    expired_pending: int = 0
    campaigns: int = 0


def _walk_baseline(ds, folds, entry_candidate: np.ndarray, events):
    """Sequential Strategy 1 baseline with no model gate.

    Every formal Entry candidate in the expanded OOS blocks is a setup signal.
    The same t+1..t+3 delayed-entry, pending reservation, flat-only and
    non-overlapping-capital rules used by the locked Q55 policy are preserved.
    Busy state carries across fold boundaries.
    """
    busy_until = -1
    all_campaigns: list[Campaign] = []
    counters: dict[int, BaselineCounters] = {}

    for fold_id, fold in enumerate(folds, start=1):
        c = BaselineCounters()
        counters[fold_id] = c
        fold_first_raw = int(ds.raw_indices[fold.test[0]])
        fold_last_raw = int(ds.raw_indices[fold.test[-1]])

        for event_idx in fold.test:
            signal_raw = int(ds.raw_indices[event_idx])
            c.setup_signals += 1

            if signal_raw <= busy_until:
                c.ignored_busy_signals += 1
                continue

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
            [
                x.final_return
                for x in all_campaigns
                if fold_first_raw <= x.signal_raw <= fold_last_raw
            ],
            dtype=float,
        )
        success = float(np.mean(fold_returns > 0.0)) if len(fold_returns) else float("nan")
        net = float(fold_returns.mean()) if len(fold_returns) else float("nan")
        compounded = float(np.prod(1.0 + fold_returns) - 1.0) if len(fold_returns) else 0.0
        print(
            f"S1 EXPANDED_BASELINE_COMPARE BASELINE_FOLD id={fold_id} "
            f"test_first={pd.Timestamp(ds.dates[fold.test[0]]).date()} "
            f"test_last={pd.Timestamp(ds.dates[fold.test[-1]]).date()} test_n={len(fold.test)} "
            f"setup_signals={c.setup_signals} ignored_busy_signals={c.ignored_busy_signals} "
            f"expired_pending={c.expired_pending} campaigns={c.campaigns}/{len(fold.test)} "
            f"success={_fmt(success)} net_expected_return={_fmt(net)} compounded_return={compounded:.6f}"
        )

    return all_campaigns, counters


def _campaign_metrics(campaigns: list[Campaign]) -> tuple[float, float, float]:
    returns = np.asarray([c.final_return for c in campaigns], dtype=float)
    success = float(np.mean(returns > 0.0)) if len(returns) else float("nan")
    net = float(returns.mean()) if len(returns) else float("nan")
    compounded = float(np.prod(1.0 + returns) - 1.0) if len(returns) else 0.0
    return success, net, compounded


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
        "S1 EXPANDED_BASELINE_COMPARE DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"samples={len(ds.success_probability)} folds={len(folds)} expanded_test_events={EXPANDED_TEST_EVENTS} "
        f"lookback={LOOKBACK} horizon={HORIZON} reference_lookback={REFERENCE_LOOKBACK} "
        f"purge_raw_sessions={PURGE_RAW_SESSIONS} seeds={','.join(map(str, SEEDS))} no_random_split=true"
    )
    print(
        "S1 EXPANDED_BASELINE_COMPARE RULE "
        "q55_policy=locked_max_rolling_Q70_calibration_Q55 baseline_gate=none "
        "baseline_signal=every_formal_entry_candidate_in_oos_block "
        f"delayed_entry_window=t_plus_1_to_t_plus_{ENTRY_DELAY_MAX} "
        "same_pending_reservation=true flat_only=true overlapping_capital=false "
        "busy_state_carries_across_fold_boundaries=true campaign_busy_until_actual_exit=true "
        "execution=deterministic_strategy1"
    )

    baseline_campaigns, baseline_counters = _walk_baseline(ds, folds, entry_candidate, events)
    b_success, b_net, b_compounded = _campaign_metrics(baseline_campaigns)
    print(
        "S1 EXPANDED_BASELINE_COMPARE BASELINE_SUMMARY "
        f"campaigns={len(baseline_campaigns)} "
        f"setup_signals={sum(c.setup_signals for c in baseline_counters.values())} "
        f"ignored_busy_signals={sum(c.ignored_busy_signals for c in baseline_counters.values())} "
        f"expired_pending={sum(c.expired_pending for c in baseline_counters.values())} "
        f"success={_fmt(b_success)} net_expected_return={_fmt(b_net)} compounded_return={b_compounded:.6f}"
    )
    for campaign_id, c in enumerate(baseline_campaigns, start=1):
        print(
            f"S1 EXPANDED_BASELINE_COMPARE BASELINE_CAMPAIGN id={campaign_id} "
            f"signal={events.at[c.signal_raw, 'date'].date()} entry={events.at[c.entry_raw, 'date'].date()} "
            f"exit={events.at[c.exit_raw, 'date'].date()} delay={c.entry_raw - c.signal_raw} "
            f"return={c.final_return:.6f}"
        )

    q55_seed_rows = []
    q55_unique: dict[tuple[int, int, int], float] = {}
    for seed in SEEDS:
        prepared = _prepare_predictions(ds, folds, seed)
        campaigns, counters = _walk_seed(ds, prepared, entry_candidate, events, seed)
        success, net, compounded = _campaign_metrics(campaigns)
        q55_seed_rows.append((len(campaigns), success, net, compounded))
        for c in campaigns:
            q55_unique[(c.signal_raw, c.entry_raw, c.exit_raw)] = c.final_return
        print(
            f"S1 EXPANDED_BASELINE_COMPARE Q55_SEED seed={seed} campaigns={len(campaigns)} "
            f"success={_fmt(success)} net_expected_return={_fmt(net)} compounded_return={compounded:.6f} "
            f"accepted_signals={sum(x.accepted_signals for x in counters.values())} "
            f"ignored_busy_signals={sum(x.ignored_busy_signals for x in counters.values())} "
            f"expired_pending={sum(x.expired_pending for x in counters.values())}"
        )

    q55_unique_returns = np.asarray(list(q55_unique.values()), dtype=float)
    q55_unique_success = (
        float(np.mean(q55_unique_returns > 0.0)) if len(q55_unique_returns) else float("nan")
    )
    q55_unique_net = float(q55_unique_returns.mean()) if len(q55_unique_returns) else float("nan")
    q55_seed_valid = [row for row in q55_seed_rows if np.isfinite(row[1])]

    baseline_keys = {(c.signal_raw, c.entry_raw, c.exit_raw) for c in baseline_campaigns}
    overlap = len(baseline_keys.intersection(q55_unique.keys()))

    print(
        "S1 EXPANDED_BASELINE_COMPARE SUMMARY "
        f"ticker={TICKER} folds={len(folds)} "
        f"oos_first={pd.Timestamp(ds.dates[folds[0].test[0]]).date()} "
        f"oos_last={pd.Timestamp(ds.dates[folds[-1].test[-1]]).date()} "
        f"baseline_campaigns={len(baseline_campaigns)} baseline_success={_fmt(b_success)} "
        f"baseline_net_expected_return={_fmt(b_net)} baseline_compounded_return={b_compounded:.6f} "
        f"q55_campaigns_per_seed_mean={np.mean([x[0] for x in q55_seed_rows]):.3f} "
        f"q55_seed_weighted_success={np.mean([x[1] for x in q55_seed_valid]):.6f} "
        f"q55_seed_weighted_net_expected_return={np.mean([x[2] for x in q55_seed_valid]):.6f} "
        f"q55_unique_campaigns={len(q55_unique_returns)} q55_unique_success={_fmt(q55_unique_success)} "
        f"q55_unique_net_expected_return={_fmt(q55_unique_net)} "
        f"success_lift_vs_baseline={_fmt(q55_unique_success - b_success)} "
        f"net_lift_vs_baseline={_fmt(q55_unique_net - b_net)} "
        f"campaign_path_overlap={overlap}"
    )

    if not baseline_campaigns:
        raise RuntimeError("ungated Strategy 1 baseline produced no OOS campaigns")
    if not q55_seed_valid:
        raise RuntimeError("locked Q55 policy produced no OOS campaigns")
    print("S1 EXPANDED_BASELINE_COMPARE PASS")


if __name__ == "__main__":
    main()

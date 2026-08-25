from __future__ import annotations

import numpy as np

from .data import download_spy_daily, validate_daily_ohlcv
from .strategy1 import (
    STRATEGY1_HORIZONS,
    add_strategy1_events,
    make_strategy1_oracle_labels,
    oracle_value_for_window,
)


def _group_stats(values: np.ndarray, mask: np.ndarray) -> tuple[int, float, float, float, float]:
    subset = values[mask]
    if len(subset) == 0:
        return 0, float("nan"), float("nan"), float("nan"), float("nan")
    return (
        len(subset),
        float(subset.mean()),
        float(np.median(subset)),
        float(np.quantile(subset, 0.90)),
        float(subset.max()),
    )


def _print_oracle_case(events, t: int, horizon: int, bucket: str) -> None:
    run = oracle_value_for_window(events, t, t + horizon)
    window_date = events.at[t, "date"].date()
    end_date = events.at[t + horizon, "date"].date()
    print(
        f"STRATEGY1 CASE {bucket} {horizon}D "
        f"window_start={window_date} window_end={end_date} "
        f"value={run.final_return:.6f} entries={run.entries_used}"
    )
    if not run.actions:
        print("STRATEGY1 CASE_ACTION no_trade")
        return
    for action in run.actions:
        date = events.at[action.index, "date"].date()
        print(
            f"STRATEGY1 CASE_ACTION date={date} action={action.action} "
            f"price={action.price:.4f} fraction={action.fraction:.3f}"
        )


def _print_representative_60d_cases(events, labels) -> None:
    horizon = 60
    values = labels[f"oracle_value_{horizon}"].to_numpy(dtype=float)
    traded = values > 0.0
    traded_indices = np.flatnonzero(traded)

    if len(traded_indices) < 6:
        raise RuntimeError("Not enough traded 60D cases for representative audit")

    high_indices = traded_indices[np.argsort(values[traded_indices])[-3:]][::-1]
    traded_median = float(np.median(values[traded_indices]))
    middle_indices = traded_indices[np.argsort(np.abs(values[traded_indices] - traded_median))[:3]]
    no_trade_indices = np.flatnonzero(~traded)[:3]

    print(f"STRATEGY1 REPRESENTATIVE_60D traded_median={traded_median:.6f}")
    for i in high_indices:
        _print_oracle_case(events, int(i), horizon, "HIGH")
    for i in middle_indices:
        _print_oracle_case(events, int(i), horizon, "MID")
    for i in no_trade_indices:
        _print_oracle_case(events, int(i), horizon, "NO_TRADE")


def main() -> None:
    df = download_spy_daily(period="3y")
    audit = validate_daily_ohlcv(df)
    events = add_strategy1_events(df).reset_index(drop=True)
    labels = make_strategy1_oracle_labels(df)

    if labels.empty:
        raise RuntimeError("Strategy 1 Oracle labels are empty")

    print(
        "STRATEGY1 DATA "
        f"rows={audit.rows} start={audit.start} end={audit.end} "
        f"entry1_events={int(events['entry1_event'].sum())} "
        f"breakout20_events={int(events['breakout20_event'].sum())} "
        f"exit5_events={int(events['exit5_event'].sum())} "
        f"exit10_events={int(events['exit10_event'].sum())}"
    )

    for h in STRATEGY1_HORIZONS:
        values = labels[f"oracle_value_{h}"].to_numpy(dtype=float)
        starts = labels[f"oracle_start_offset_{h}"].to_numpy(dtype=int)
        entries = labels[f"oracle_entries_{h}"].to_numpy(dtype=int)
        partial = labels[f"oracle_partial_exit_{h}"].to_numpy(dtype=bool)
        full = labels[f"oracle_full_exit_{h}"].to_numpy(dtype=bool)
        horizon_exit = labels[f"oracle_horizon_exit_{h}"].to_numpy(dtype=bool)

        if not np.isfinite(values).all():
            raise RuntimeError(f"Non-finite oracle values for {h}D")
        if (values < -1e-12).any():
            raise RuntimeError(f"Negative oracle values for {h}D despite no-trade option")
        if (entries < 0).any() or (entries > 3).any():
            raise RuntimeError(f"Invalid entry count for {h}D")
        if ((starts == -1) != (entries == 0)).any():
            raise RuntimeError(f"No-trade/start-offset mismatch for {h}D")
        if (full & horizon_exit).any():
            raise RuntimeError(f"Full-exit/horizon-exit overlap for {h}D")

        positive = float((values > 0.0).mean())
        no_trade = float((entries == 0).mean())
        e1 = float((entries == 1).mean())
        e2 = float((entries == 2).mean())
        e3 = float((entries == 3).mean())
        traded = entries > 0
        traded_n = int(traded.sum())

        print(
            f"STRATEGY1 ORACLE {h}D "
            f"n={len(values)} positive={positive:.3f} no_trade={no_trade:.3f} "
            f"mean={values.mean():.6f} median={np.median(values):.6f} "
            f"p90={np.quantile(values, 0.90):.6f} max={values.max():.6f}"
        )
        print(
            f"STRATEGY1 ACTIONS {h}D "
            f"entry1={e1:.3f} entry2={e2:.3f} entry3={e3:.3f} "
            f"partial_exit={partial.mean():.3f} full_exit={full.mean():.3f} "
            f"horizon_exit={horizon_exit.mean():.3f}"
        )
        if traded_n:
            print(
                f"STRATEGY1 ACTIONS_CONDITIONAL {h}D traded={traded_n} "
                f"entry1={(entries[traded] == 1).mean():.3f} "
                f"entry2={(entries[traded] == 2).mean():.3f} "
                f"entry3={(entries[traded] == 3).mean():.3f} "
                f"partial_exit={partial[traded].mean():.3f} "
                f"full_exit={full[traded].mean():.3f} "
                f"horizon_exit={horizon_exit[traded].mean():.3f}"
            )

        for k in (1, 2, 3):
            n, mean, median, p90, max_value = _group_stats(values, entries == k)
            print(
                f"STRATEGY1 VALUE_BY_ENTRIES {h}D entries={k} n={n} "
                f"mean={mean:.6f} median={median:.6f} p90={p90:.6f} max={max_value:.6f}"
            )

    _print_representative_60d_cases(events, labels)
    print("STRATEGY1 ORACLE SMOKE PASS")


if __name__ == "__main__":
    main()

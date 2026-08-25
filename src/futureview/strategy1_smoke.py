from __future__ import annotations

import numpy as np

from .data import download_spy_daily, validate_daily_ohlcv
from .strategy1 import STRATEGY1_HORIZONS, add_strategy1_events, make_strategy1_oracle_labels


def main() -> None:
    df = download_spy_daily(period="3y")
    audit = validate_daily_ohlcv(df)
    events = add_strategy1_events(df)
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

    print("STRATEGY1 ORACLE SMOKE PASS")


if __name__ == "__main__":
    main()

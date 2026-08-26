from __future__ import annotations

import os

import numpy as np

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_profitability_io import build_path_table, build_profitability_io

TICKER = os.environ.get("FUTUREVIEW_TICKER", "SMH")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
WINDOWS = tuple(
    int(x.strip())
    for x in os.environ.get("FUTUREVIEW_REGIME_WINDOWS", "20,30,40,60,90,120").split(",")
    if x.strip()
)


def main() -> None:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    path_table = build_path_table(events)

    print(
        f"S1 PROFITABILITY_WINDOW_AUDIT START ticker={TICKER} rows={audit.rows} "
        f"paths={len(path_table)} entries={path_table['entry_index'].nunique()}"
    )
    print("S1 PROFITABILITY_WINDOW_AUDIT HEADER W windows path_p10 path_p50 path_p90 U_lt_0 L_gt_0 mixed empty")

    for window in WINDOWS:
        io = build_profitability_io(events, path_table, window, stride=1)
        valid = io.path_count > 0
        bad = valid & (io.upper < 0)
        good = valid & (io.lower > 0)
        mixed = valid & (io.lower < 0) & (io.upper > 0)
        empty = ~valid
        print(
            "S1 PROFITABILITY_WINDOW_AUDIT ROW "
            f"W={window} windows={len(io.window_start)} "
            f"path_p10={np.quantile(io.path_count, 0.10):.1f} "
            f"path_p50={np.quantile(io.path_count, 0.50):.1f} "
            f"path_p90={np.quantile(io.path_count, 0.90):.1f} "
            f"U_lt_0={int(bad.sum())} L_gt_0={int(good.sum())} "
            f"mixed={int(mixed.sum())} empty={int(empty.sum())}"
        )

    print("S1 PROFITABILITY_WINDOW_AUDIT COMPLETE research_window_frozen=false")


if __name__ == "__main__":
    main()

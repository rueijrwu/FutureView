from __future__ import annotations

import os

import numpy as np

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_profitability_io import build_path_table

TICKER = os.environ.get("FUTUREVIEW_TICKER", "SMH")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
WINDOWS = tuple(
    int(x.strip())
    for x in os.environ.get("FUTUREVIEW_REGIME_WINDOWS", "20,30,60").split(",")
    if x.strip()
)
QUANTILES = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)


def _audit_window(path_table, window: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    valid_last_entry = int(path_table["entry_index"].max())
    starts = np.arange(0, valid_last_entry - window + 2, dtype=np.int32)
    returns_by_entry = {
        int(entry): group["campaign_return"].to_numpy(dtype=np.float64)
        for entry, group in path_table.groupby("entry_index", sort=False)
    }

    counts = np.zeros(len(starts), dtype=np.int32)
    lower = np.full(len(starts), np.nan, dtype=np.float64)
    upper = np.full(len(starts), np.nan, dtype=np.float64)

    for wi, start in enumerate(starts):
        pieces = [
            returns_by_entry[entry]
            for entry in range(int(start), int(start + window))
            if entry in returns_by_entry
        ]
        if not pieces:
            continue
        returns = np.concatenate(pieces)
        counts[wi] = len(returns)
        lower[wi] = float(returns.min())
        upper[wi] = float(returns.max())

    return counts, lower, upper


def _q(values: np.ndarray, q: float) -> float:
    return float(np.quantile(values, q))


def main() -> None:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    path_table = build_path_table(events)

    print(
        f"S1 PROFITABILITY_WINDOW_AUDIT START ticker={TICKER} rows={audit.rows} "
        f"paths={len(path_table)} entries={path_table['entry_index'].nunique()}"
    )
    print(
        "S1 PROFITABILITY_WINDOW_AUDIT PURPOSE "
        "pilot_windows=20,30,60 L_U_statistics_descriptive=true extreme_definition_frozen=false"
    )

    for window in WINDOWS:
        path_count, lower, upper = _audit_window(path_table, window)
        valid = path_count > 0
        lv = lower[valid]
        uv = upper[valid]
        mixed = valid & (lower < 0) & (upper > 0)
        all_negative = valid & (upper < 0)
        all_positive = valid & (lower > 0)
        empty = ~valid

        print(
            "S1 PROFITABILITY_WINDOW_AUDIT SUMMARY "
            f"W={window} windows={len(path_count)} valid={int(valid.sum())} empty={int(empty.sum())} "
            f"path_p10={np.quantile(path_count, 0.10):.1f} "
            f"path_p50={np.quantile(path_count, 0.50):.1f} "
            f"path_p90={np.quantile(path_count, 0.90):.1f} "
            f"all_negative={int(all_negative.sum())} all_positive={int(all_positive.sum())} "
            f"mixed={int(mixed.sum())}"
        )
        print(
            "S1 PROFITABILITY_WINDOW_AUDIT L_STATS "
            f"W={window} min={lv.min():.8f} "
            + " ".join(f"p{int(q*100):02d}={_q(lv, q):.8f}" for q in QUANTILES)
            + f" max={lv.max():.8f}"
        )
        print(
            "S1 PROFITABILITY_WINDOW_AUDIT U_STATS "
            f"W={window} min={uv.min():.8f} "
            + " ".join(f"p{int(q*100):02d}={_q(uv, q):.8f}" for q in QUANTILES)
            + f" max={uv.max():.8f}"
        )

    print(
        "S1 PROFITABILITY_WINDOW_AUDIT COMPLETE "
        "research_window_frozen=false extreme_definition_frozen=false"
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_causal_pipeline import (
    assert_complete_window_states,
    build_complete_window_consensus_states,
)

TICKER = "TSLA"
PERIOD = "8y"
W = 30


def main() -> None:
    df = download_ticker_daily(TICKER, period=PERIOD).reset_index(drop=True)
    req = ["open", "high", "low", "close", "volume"]
    bad = df[req].isna().any(axis=1)
    if bad.any():
        df = df.loc[~bad].reset_index(drop=True)
    validate_daily_ohlcv(df, minimum_rows=1800)

    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    states = build_complete_window_consensus_states(df, paths, window=W)
    assert_complete_window_states(states)

    high = int(states.consensus.eq("high").sum())
    neutral = int(states.consensus.eq("neutral").sum())
    low = int(states.consensus.eq("low").sum())

    entry_same = bool(
        (states.min_member_entry_index_entry == states.min_member_entry_index_exit).all()
        and (states.max_member_exit_index_entry == states.max_member_exit_index_exit).all()
    )

    print(
        f"S1 COMPLETE-WINDOW SMOKE PASS W={W} states={len(states)} H={high} N={neutral} L={low} "
        f"entry_exit_legal_bounds_same={int(entry_same)} rule='start<=entry<=final_exit<=end'"
    )


if __name__ == "__main__":
    main()

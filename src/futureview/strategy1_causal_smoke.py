from __future__ import annotations

import numpy as np

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_causal_pipeline import (
    EXTREMA_CONFIRMATION_LAG,
    assert_causal_states,
    build_causal_consensus_states,
    mature_train_indices,
)

TICKER = "TSLA"
PERIOD = "8y"
W = 30
MODEL_HISTORY = 90
HORIZON = 30
MEMORY = 30
ROLL_DAYS = 10


def main() -> None:
    df = download_ticker_daily(TICKER, period=PERIOD).reset_index(drop=True)
    req = ["open", "high", "low", "close", "volume"]
    bad = df[req].isna().any(axis=1)
    if bad.any():
        df = df.loc[~bad].reset_index(drop=True)
    validate_daily_ohlcv(df, minimum_rows=1800)

    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    states = build_causal_consensus_states(df, paths, window=W)
    assert_causal_states(states)

    selected = states.loc[states.consensus.eq("high")].copy()
    selected = selected.loc[
        (selected.end_index.astype(int) - MODEL_HISTORY + 1 >= 0)
        & (selected.end_index.astype(int) + HORIZON < len(df))
    ].sort_values("end_index").reset_index(drop=True)
    cut = selected.end_index.to_numpy(np.int64, copy=False)
    if cut.size == 0:
        raise RuntimeError("no causal H samples")

    folds = 0
    contaminated = 0
    first, last = int(cut.min()), int(cut.max())
    for block_start in range(first, last + 1, ROLL_DAYS):
        block_end = min(block_start + ROLL_DAYS - 1, last)
        if not np.any((cut >= block_start) & (cut <= block_end)):
            continue
        tr = mature_train_indices(cut, block_start=block_start, horizon=HORIZON, memory=MEMORY)
        if tr.size == 0:
            continue
        folds += 1
        contaminated += int(np.sum(cut[tr] + HORIZON >= block_start))

    if folds == 0:
        raise RuntimeError("no smoke folds with mature memory")
    if contaminated != 0:
        raise AssertionError(f"target leakage remains: contaminated={contaminated}")

    max_entry_lag = int(
        np.max(states.max_member_available_index_entry.to_numpy(np.int64) - states.end_index.to_numpy(np.int64))
    )
    max_exit_lag = int(
        np.max(states.max_member_available_index_exit.to_numpy(np.int64) - states.end_index.to_numpy(np.int64))
    )
    print(
        f"S1 CAUSAL SMOKE PASS W={W} horizon={HORIZON} memory={MEMORY} roll={ROLL_DAYS} "
        f"states={len(states)} H={len(selected)} folds={folds} target_contaminated={contaminated} "
        f"max_entry_availability_minus_end={max_entry_lag} max_exit_availability_minus_end={max_exit_lag} "
        f"extrema_confirmation_lag={EXTREMA_CONFIRMATION_LAG}"
    )


if __name__ == "__main__":
    main()

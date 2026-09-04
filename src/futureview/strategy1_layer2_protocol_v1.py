from __future__ import annotations

import os
import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_entry_exit_cq_compare import build_cq
from .strategy1_exit_window_cq_audit import classify_causal
from .strategy1_layer2_forward_smoke import make_input_features

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
MODEL_HISTORY = int(os.environ.get("FUTUREVIEW_MODEL_HISTORY", "90"))
ROLL_DAYS = int(os.environ.get("FUTUREVIEW_ROLL_DAYS", "15"))
TRAIN_MEMORY = int(os.environ.get("FUTUREVIEW_TRAIN_MEMORY", "150"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer2-protocol-v1.csv")


def build_states(df: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    entry = build_cq(df, paths, membership="entry")
    exit_ = build_cq(df, paths, membership="exit")
    ce = classify_causal(entry.rename(columns={"B": "B_periodic"}))
    cx = classify_causal(exit_.rename(columns={"B": "B_periodic"}))
    return (
        ce[["start_index", "end_index", "state"]]
        .merge(
            cx[["start_index", "end_index", "state"]],
            on=["start_index", "end_index"],
            suffixes=("_entry", "_exit"),
            how="inner",
        )
        .sort_values("end_index")
        .reset_index(drop=True)
    )


def main() -> None:
    if MODEL_HISTORY != 90 or ROLL_DAYS != 15 or TRAIN_MEMORY != 150:
        raise ValueError("protocol v1 is locked to 90D normalized P/V, 15D retrain cadence, and 150-sample memory")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    states = build_states(df, paths)

    rows: list[dict[str, object]] = []
    xs: list[np.ndarray] = []
    for r in states.itertuples(index=False):
        # Strict neutral removal: drop only when both entry-CQ and exit-CQ are neutral.
        if str(r.state_entry) == "neutral" and str(r.state_exit) == "neutral":
            continue
        cutoff = int(r.end_index)
        start = cutoff - MODEL_HISTORY + 1
        if start < 0:
            continue
        x = make_input_features(df, start, cutoff)
        xs.append(x)
        rows.append(
            {
                "cutoff_index": cutoff,
                "cutoff_date": pd.Timestamp(df.at[cutoff, "date"]).date().isoformat(),
                "state_entry": str(r.state_entry),
                "state_exit": str(r.state_exit),
            }
        )

    if not rows:
        raise RuntimeError("no Layer2 protocol samples")

    manifest = pd.DataFrame(rows).sort_values("cutoff_index").reset_index(drop=True)
    first_cut = int(manifest.cutoff_index.min())
    last_cut = int(manifest.cutoff_index.max())
    fold_id = 0
    assigned = []

    for block_start in range(first_cut, last_cut + 1, ROLL_DAYS):
        block_end = min(block_start + ROLL_DAYS - 1, last_cut)
        valid_idx = np.flatnonzero(
            ((manifest.cutoff_index >= block_start) & (manifest.cutoff_index <= block_end)).to_numpy()
        )
        if len(valid_idx) == 0:
            continue
        train_idx = np.flatnonzero((manifest.cutoff_index < block_start).to_numpy())
        if len(train_idx) < TRAIN_MEMORY:
            continue
        train_idx = train_idx[-TRAIN_MEMORY:]
        for i in valid_idx:
            assigned.append(
                {
                    **manifest.iloc[i].to_dict(),
                    "fold_id": fold_id,
                    "block_start_index": block_start,
                    "block_end_index": block_end,
                    "train_n": TRAIN_MEMORY,
                    "train_first_cutoff": int(manifest.iloc[train_idx[0]].cutoff_index),
                    "train_last_cutoff": int(manifest.iloc[train_idx[-1]].cutoff_index),
                }
            )
        fold_id += 1

    out = pd.DataFrame(assigned)
    out.to_csv(OUTPUT, index=False)

    print(
        f"S1 PROTOCOL START ticker={TICKER} rows={audit.rows} selected={len(manifest)} "
        f"history={MODEL_HISTORY} roll_days={ROLL_DAYS} train_memory={TRAIN_MEMORY}"
    )
    print(
        f"S1 PROTOCOL FILTER dual_neutral_drop={(states.state_entry.eq('neutral') & states.state_exit.eq('neutral')).sum()} "
        f"kept={len(manifest)}"
    )
    print(f"S1 PROTOCOL SCHEDULE folds={fold_id} scheduled_oos={len(out)}")
    print(f"S1 PROTOCOL OUTPUT file={OUTPUT}")
    print("S1 PROTOCOL COMPLETE")


if __name__ == "__main__":
    main()

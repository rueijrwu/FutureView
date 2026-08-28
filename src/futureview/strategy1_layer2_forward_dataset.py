from __future__ import annotations

import os
import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table
from .strategy1_cq_90d_rank_audit import build_window_q
from .strategy1_layer1_forward_w_audit import _classify

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
MODEL_HISTORY = int(os.environ.get("FUTUREVIEW_MODEL_HISTORY", "90"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer2-forward-dataset.csv")


def build_forward_dataset(classified: pd.DataFrame, n_rows: int, model_history: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for r in classified.itertuples(index=False):
        target_start = int(r.start_index)
        target_end = int(r.end_index)
        input_end = target_start - 1
        input_start = input_end - model_history + 1
        if input_start < 0 or target_end >= n_rows:
            continue
        rows.append({
            "input_start": input_start,
            "input_end": input_end,
            "target_start": target_start,
            "target_end": target_end,
            "C": float(r.past_C),
            "Q": float(r.past_Q),
            "state": str(r.state),
            "entry_count": int(r.past_entries),
        })
    return pd.DataFrame(rows)


def main() -> None:
    if W != 30 or MODEL_HISTORY != 90:
        raise ValueError("initial forward Layer2 dataset audit is locked to W=30 and model_history=90")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(df, paths, window=W, stride=1, random_samples=20, random_seed=SEED)
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)
    classified = _classify(wq).sort_values("start_index").reset_index(drop=True)
    out = build_forward_dataset(classified, len(df), MODEL_HISTORY)

    if out.empty:
        raise RuntimeError("no forward Layer2 samples")

    bad_len = int(((out.input_end - out.input_start + 1) != MODEL_HISTORY).sum())
    overlap = int((out.input_end >= out.target_start).sum())
    nonadjacent = int(((out.input_end + 1) != out.target_start).sum())
    bad_target = int(((out.target_end - out.target_start + 1) != W).sum())

    out.to_csv(OUTPUT, index=False)

    print(
        f"S1 L2FWD START ticker={TICKER} rows={audit.rows} W={W} model_history={MODEL_HISTORY} "
        f"classified={len(classified)} samples={len(out)}"
    )
    print(
        f"S1 L2FWD ALIGNMENT bad_input_length={bad_len} input_target_overlap={overlap} "
        f"nonadjacent={nonadjacent} bad_target_length={bad_target}"
    )
    for state in ("high", "neutral", "low"):
        g = out.loc[out.state == state]
        print(
            f"S1 L2FWD STATE state={state} n={len(g)} share={len(g)/len(out):.6f} "
            f"C_mean={g.C.mean():.6f} C_median={g.C.median():.6f} "
            f"Q_mean={g.Q.mean():.6f} Q_median={g.Q.median():.6f}"
        )
    print(
        f"S1 L2FWD TARGET C_mean={out.C.mean():.6f} C_std={out.C.std(ddof=0):.6f} "
        f"Q_mean={out.Q.mean():.6f} Q_std={out.Q.std(ddof=0):.6f}"
    )
    print(f"S1 L2FWD OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 L2FWD COMPLETE")


if __name__ == "__main__":
    main()

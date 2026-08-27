from __future__ import annotations

from pathlib import Path
import os

import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_cq_data import HORIZON
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
WINDOW = int(os.environ.get("FUTUREVIEW_LAYER1_WINDOW", "30"))
REFERENCE_WINDOWS = tuple(
    int(v) for v in os.environ.get("FUTUREVIEW_LAYER1_REFERENCE_WINDOWS", "60,90").split(",")
)
LOW_Q = float(os.environ.get("FUTUREVIEW_LAYER1_LOW_Q", "0.25"))
HIGH_Q = float(os.environ.get("FUTUREVIEW_LAYER1_HIGH_Q", "0.75"))
RANDOM_SAMPLES = int(os.environ.get("FUTUREVIEW_A_RANDOM_SAMPLES", "20"))
RANDOM_SEED = int(os.environ.get("FUTUREVIEW_A_RANDOM_SEED", "20260827"))
OUTPUT = Path(os.environ.get("FUTUREVIEW_LAYER1_THRESHOLD_OUTPUT", "strategy1-layer1-threshold-audit.csv"))


def build_outcome_table(df: pd.DataFrame, windows: pd.DataFrame) -> pd.DataFrame:
    out = windows.loc[:, [
        "ticker", "start_index", "end_index", "start_date", "end_date",
        "U", "B_periodic", "path_count",
    ]].copy()
    out["C"] = out["U"].astype(float) - out["B_periodic"].astype(float)
    # Conservative availability index: the evaluation window may contain an Entry
    # on its final day, whose fixed Strategy path may continue HORIZON sessions.
    out["dependency_end"] = out["end_index"].astype(int) + HORIZON
    return out.sort_values("start_index").reset_index(drop=True)


def rolling_labels(meta: pd.DataFrame, reference_days: int) -> pd.DataFrame:
    """Compute local 25/75 percentiles using outcomes completed in the prior R sessions.

    For a target window beginning at index s, a historical outcome is eligible for the
    reference set only when its dependency_end is in [s-R, s-1]. This keeps the local
    reference causal while measuring locality by when the historical outcome became
    fully known.
    """
    rows: list[dict[str, float | int | str]] = []
    for row in meta.itertuples(index=False):
        s = int(row.start_index)
        ref = meta.loc[
            (meta["dependency_end"] >= s - reference_days)
            & (meta["dependency_end"] < s)
        ]
        if len(ref) < max(10, reference_days // 3):
            continue

        c25 = float(ref["C"].quantile(LOW_Q))
        c75 = float(ref["C"].quantile(HIGH_Q))
        u25 = float(ref["U"].quantile(LOW_Q))
        u75 = float(ref["U"].quantile(HIGH_Q))
        c = float(row.C)
        u = float(row.U)

        label = 0
        if c > c75 and u > u75:
            label = 1
        elif c < c25 and u < u25:
            label = -1

        rows.append({
            "ticker": TICKER,
            "reference_days": reference_days,
            "start_index": s,
            "start_date": row.start_date,
            "end_date": row.end_date,
            "U": u,
            "C": c,
            "C25": c25,
            "C75": c75,
            "U25": u25,
            "U75": u75,
            "reference_count": int(len(ref)),
            "label": label,
        })

    if not rows:
        raise RuntimeError(f"no valid rolling labels for R={reference_days}")
    return pd.DataFrame(rows)


def print_audit(frame: pd.DataFrame, reference_days: int) -> None:
    counts = frame["label"].value_counts().reindex([-1, 0, 1], fill_value=0)
    n = len(frame)
    print(
        f"S1 LAYER1 ROLLING R={reference_days} n={n} "
        f"low={int(counts[-1])} low_rate={counts[-1]/n:.6f} "
        f"neutral={int(counts[0])} neutral_rate={counts[0]/n:.6f} "
        f"high={int(counts[1])} high_rate={counts[1]/n:.6f} "
        f"ref_count_median={frame['reference_count'].median():.1f} "
        f"first={frame['start_date'].iloc[0]} last={frame['start_date'].iloc[-1]}"
    )

    ordered = frame.sort_values("start_index").reset_index(drop=True)
    for part_id, idx in enumerate(np.array_split(np.arange(len(ordered)), 3), start=1):
        chunk = ordered.iloc[idx]
        c = chunk["label"].value_counts().reindex([-1, 0, 1], fill_value=0)
        m = len(chunk)
        print(
            f"S1 LAYER1 ROLLING_CHRONO R={reference_days} part={part_id} n={m} "
            f"low={int(c[-1])} low_rate={c[-1]/m:.6f} "
            f"neutral={int(c[0])} neutral_rate={c[0]/m:.6f} "
            f"high={int(c[1])} high_rate={c[1]/m:.6f}"
        )

    print(
        f"S1 LAYER1 ROLLING_THRESHOLD R={reference_days} "
        f"C25_median={frame['C25'].median():.6f} C75_median={frame['C75'].median():.6f} "
        f"U25_median={frame['U25'].median():.6f} U75_median={frame['U75'].median():.6f}"
    )


def main() -> None:
    if WINDOW != 30:
        raise ValueError("current Layer-1 threshold audit is locked to W=30")
    if not REFERENCE_WINDOWS or any(r <= 0 for r in REFERENCE_WINDOWS):
        raise ValueError("reference windows must be positive")
    if not (0.0 < LOW_Q < HIGH_Q < 1.0):
        raise ValueError("invalid quantiles")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(
        df,
        paths,
        window=WINDOW,
        stride=1,
        random_samples=RANDOM_SAMPLES,
        random_seed=RANDOM_SEED,
    )
    meta = build_outcome_table(df, windows)

    print(
        f"S1 LAYER1 ROLLING_START ticker={TICKER} rows={audit.rows} first={audit.start} last={audit.end} "
        f"W={WINDOW} horizon={HORIZON} refs={','.join(map(str, REFERENCE_WINDOWS))}"
    )
    print(
        "S1 LAYER1 ROLLING_DEFINITION C=U-B_periodic percentiles=25,75 "
        "high=(C>C75 and U>U75) low=(C<C25 and U<U25) neutral=otherwise "
        "reference=prior_completed_outcomes_only"
    )

    frames: list[pd.DataFrame] = []
    for reference_days in REFERENCE_WINDOWS:
        frame = rolling_labels(meta, reference_days)
        frames.append(frame)
        print_audit(frame, reference_days)

    combined = pd.concat(frames, ignore_index=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(OUTPUT, index=False)
    print(f"S1 LAYER1 ROLLING_OUTPUT file={OUTPUT} rows={len(combined)}")
    print("S1 LAYER1 ROLLING_COMPLETE")


if __name__ == "__main__":
    main()

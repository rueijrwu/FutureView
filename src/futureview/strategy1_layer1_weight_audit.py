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
HISTORY = int(os.environ.get("FUTUREVIEW_WEIGHT_HISTORY", "90"))
EXTREME_THRESHOLD = float(os.environ.get("FUTUREVIEW_EXTREME_THRESHOLD", "0.5"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer1-weight-audit.csv")


def has_true_reversal(states: list[str]) -> bool:
    """True iff the observed history contains High->Low or Low->High.

    Neutral rows may occur between the two extreme states. A return to the same
    extreme through Neutral is not counted as a reversal by itself.
    """
    last_extreme: str | None = None
    for state in states:
        if state not in ("high", "low"):
            continue
        if last_extreme is not None and state != last_extreme:
            return True
        last_extreme = state
    return False


def assign_weight(states: list[str], extreme_threshold: float = EXTREME_THRESHOLD) -> tuple[int, float, bool]:
    """Assign the simple Layer1 sample-importance weight.

    weight 1: no true reversal and < threshold of history is High/Low.
    weight 2: no true reversal and >= threshold of history is High/Low.
    weight 3: at least one true High<->Low reversal in the history.
    """
    if not states:
        raise ValueError("states must be non-empty")
    if not 0.0 <= extreme_threshold <= 1.0:
        raise ValueError("extreme_threshold must be in [0,1]")

    extreme_count = sum(s in ("high", "low") for s in states)
    extreme_coverage = extreme_count / len(states)
    reversal = has_true_reversal(states)
    if reversal:
        weight = 3
    elif extreme_coverage >= extreme_threshold:
        weight = 2
    else:
        weight = 1
    return weight, extreme_coverage, reversal


def build_weight_table(classified: pd.DataFrame, history: int = HISTORY) -> pd.DataFrame:
    x = classified.sort_values("start_index").reset_index(drop=True)
    by_start = {int(r.start_index): r for r in x.itertuples(index=False)}
    rows: list[dict[str, object]] = []

    for r in x.itertuples(index=False):
        end = int(r.start_index)
        start = end - history + 1
        if start < 0:
            continue
        hist_rows = [by_start.get(i) for i in range(start, end + 1)]
        if any(v is None for v in hist_rows):
            continue
        states = [str(v.state) for v in hist_rows if v is not None]
        weight, extreme_coverage, reversal = assign_weight(states)
        n_high = sum(s == "high" for s in states)
        n_neutral = sum(s == "neutral" for s in states)
        n_low = sum(s == "low" for s in states)
        rows.append({
            "sample_start": start,
            "sample_end": end,
            "weight": weight,
            "extreme_coverage": extreme_coverage,
            "has_reversal": reversal,
            "n_high": n_high,
            "n_neutral": n_neutral,
            "n_low": n_low,
            "current_state": str(r.state),
            "current_C": float(r.past_C),
            "current_Q": float(r.past_Q),
            "current_entries": int(r.past_entries),
        })
    return pd.DataFrame(rows)


def _q(values: pd.Series, q: float) -> float:
    return float(values.quantile(q)) if len(values) else float("nan")


def main() -> None:
    if W not in (15, 30, 60):
        raise ValueError("weight audit supports W in {15,30,60}")
    if HISTORY != 90:
        raise ValueError("initial simple weighting audit is locked to 90-session sample history")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(df, paths, window=W, stride=1, random_samples=20, random_seed=SEED)
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)
    classified = _classify(wq).sort_values("start_index").reset_index(drop=True)
    out = build_weight_table(classified, history=HISTORY)
    out.to_csv(OUTPUT, index=False)

    print(
        f"S1 L1WEIGHT START ticker={TICKER} rows={audit.rows} W={W} history={HISTORY} "
        f"classified={len(classified)} samples={len(out)} threshold={EXTREME_THRESHOLD:.3f}"
    )
    if out.empty:
        print("S1 L1WEIGHT COMPLETE")
        return

    print(
        f"S1 L1WEIGHT OVERALL reversal_rate={out.has_reversal.mean():.6f} "
        f"extreme_coverage_mean={out.extreme_coverage.mean():.6f} "
        f"extreme_coverage_median={out.extreme_coverage.median():.6f}"
    )

    for weight in (1, 2, 3):
        g = out.loc[out.weight == weight]
        if g.empty:
            print(f"S1 L1WEIGHT GROUP weight={weight} n=0")
            continue
        print(
            f"S1 L1WEIGHT GROUP weight={weight} n={len(g)} share={len(g)/len(out):.6f} "
            f"reversal_rate={g.has_reversal.mean():.6f} "
            f"extreme_mean={g.extreme_coverage.mean():.6f} extreme_median={g.extreme_coverage.median():.6f} "
            f"C_mean={g.current_C.mean():.6f} C_median={g.current_C.median():.6f} "
            f"Q_mean={g.current_Q.mean():.6f} Q_median={g.current_Q.median():.6f} "
            f"entries_mean={g.current_entries.mean():.3f}"
        )
        print(
            f"S1 L1WEIGHT STATE weight={weight} "
            f"high={(g.current_state=='high').mean():.6f} "
            f"neutral={(g.current_state=='neutral').mean():.6f} "
            f"low={(g.current_state=='low').mean():.6f}"
        )

    print(
        f"S1 L1WEIGHT DIST extreme_p10={_q(out.extreme_coverage,0.10):.6f} "
        f"p25={_q(out.extreme_coverage,0.25):.6f} median={_q(out.extreme_coverage,0.50):.6f} "
        f"p75={_q(out.extreme_coverage,0.75):.6f} p90={_q(out.extreme_coverage,0.90):.6f}"
    )
    print(f"S1 L1WEIGHT OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 L1WEIGHT COMPLETE")


if __name__ == "__main__":
    main()

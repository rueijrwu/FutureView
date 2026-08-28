from __future__ import annotations

import os
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table
from .strategy1_cq_90d_rank_audit import build_window_q

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
SHORT_REF = int(os.environ.get("FUTUREVIEW_SHORT_REF", "90"))
LONG_REF = int(os.environ.get("FUTUREVIEW_LONG_REF", "756"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))


def classify_entry_gates(df: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    """Entry-centric Layer-1 gate while preserving the original Layer-1 reference contract.

    For each legal Entry t:
      current C/Q := W30 window [s, t], where s=t-W+1
      90D/3Y references := prior W30 windows with end_index < s

    This is exactly the original gate time contract, merely sampled at Entry-anchored
    current windows instead of every evaluable rolling W30 window.
    """
    windows = build_representation_a_table(
        df, paths, window=W, stride=1, random_samples=20, random_seed=SEED
    )
    wq = build_window_q(windows, paths).sort_values("end_index").reset_index(drop=True)
    by_end = wq.set_index("end_index")

    rows: list[dict[str, float | int]] = []
    for t in paths["entry_index"].astype(int).to_numpy():
        s = t - W + 1
        if t not in by_end.index:
            continue
        cur = by_end.loc[t]
        if isinstance(cur, pd.DataFrame):
            cur = cur.iloc[-1]

        # Original Layer-1 contract: references must be completed before the
        # current W30 window begins. No overlapping current/reference windows.
        prior = wq.loc[wq["end_index"].astype(int) < s]
        short = prior.loc[prior["end_index"].astype(int) >= s - SHORT_REF]
        long = prior.loc[prior["end_index"].astype(int) >= s - LONG_REF]
        if s < LONG_REF or len(short) < 20 or len(long) < 100:
            continue

        c40, c60 = (float(short["C"].quantile(q)) for q in (0.40, 0.60))
        q40, q60 = (float(short["Q"].quantile(q)) for q in (0.40, 0.60))
        c50 = float(long["C"].median())
        q50 = float(long["Q"].median())
        c = float(cur.C)
        q = float(cur.Q)

        high = c >= c60 and q <= q60 and c > c50 and q < q50
        low = c <= c40 and q >= q40 and c < c50 and q > q50
        gate = 1 if high else (-1 if low else 0)
        rows.append(
            {
                "entry_index": int(t),
                "window_start": int(s),
                "window_end": int(t),
                "C_hist": c,
                "Q_hist": q,
                "C90_40": c40,
                "C90_60": c60,
                "Q90_40": q40,
                "Q90_60": q60,
                "C3Y_50": c50,
                "Q3Y_50": q50,
                "short_reference_count": int(len(short)),
                "long_reference_count": int(len(long)),
                "gate": gate,
            }
        )
    return pd.DataFrame(rows).sort_values("entry_index").reset_index(drop=True)


def main() -> None:
    if W != 30 or SHORT_REF != 90 or LONG_REF != 756:
        raise ValueError("audit locked to W=30, rolling90, rolling3Y")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    gates = classify_entry_gates(df, paths)

    gates["centered_2W_available"] = [
        t - W + 1 >= 0 and t + W < len(df) for t in gates["entry_index"].astype(int)
    ]

    high = gates.loc[gates.gate == 1]
    neutral = gates.loc[gates.gate == 0]
    low = gates.loc[gates.gate == -1]
    passed = gates.loc[gates.gate != 0]
    pass_target = passed.loc[passed.centered_2W_available]

    print(
        f"S1 ENTRYGATE START ticker={TICKER} rows={audit.rows} legal_entries={len(paths)} "
        f"classified_entries={len(gates)} W={W} short_ref={SHORT_REF} long_ref={LONG_REF} "
        "reference_contract=end_before_current_window_start"
    )
    print(
        f"S1 ENTRYGATE TOTAL high={len(high)} neutral={len(neutral)} low={len(low)} "
        f"pass={len(passed)} pass_with_centered_2W={len(pass_target)}"
    )
    if len(gates):
        print(
            f"S1 ENTRYGATE RATE high={len(high)/len(gates):.6f} neutral={len(neutral)/len(gates):.6f} "
            f"low={len(low)/len(gates):.6f} pass={len(passed)/len(gates):.6f}"
        )
    for name, part in (("high", high), ("neutral", neutral), ("low", low)):
        if len(part):
            print(
                f"S1 ENTRYGATE FACT state={name} n={len(part)} "
                f"C_mean={part.C_hist.mean():.6f} C_median={part.C_hist.median():.6f} "
                f"Q_mean={part.Q_hist.mean():.6f} Q_median={part.Q_hist.median():.6f}"
            )
    gates.to_csv("strategy1-entry-gate-audit.csv", index=False)
    print("S1 ENTRYGATE COMPLETE")


if __name__ == "__main__":
    main()

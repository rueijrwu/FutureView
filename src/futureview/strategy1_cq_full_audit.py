from __future__ import annotations

import os

import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table
from .strategy1_layer1_state import build_samples

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
WINDOW = int(os.environ.get("FUTUREVIEW_LAYER1_WINDOW", "30"))
RANDOM_SAMPLES = int(os.environ.get("FUTUREVIEW_A_RANDOM_SAMPLES", "20"))
RANDOM_SEED = int(os.environ.get("FUTUREVIEW_A_RANDOM_SEED", "20260827"))
EPS = 1e-12


def pct(v: pd.Series, q: float) -> float:
    return float(v.quantile(q))


def main() -> None:
    if WINDOW != 30:
        raise ValueError("full C/Q audit is currently locked to W=30")

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

    input_meta, _ = build_samples(df, windows)
    valid_starts = set(input_meta["start_index"].astype(int).tolist())
    path_by_entry = paths.set_index("entry_index")["campaign_return"]

    rows: list[dict[str, float | int | str]] = []
    window_rows: list[dict[str, float | int | str]] = []

    for w in windows.sort_values("start_index").itertuples(index=False):
        start = int(w.start_index)
        if start not in valid_starts:
            continue
        end = int(w.end_index)
        entries = paths.loc[
            (paths["entry_index"].astype(int) >= start)
            & (paths["entry_index"].astype(int) <= end),
            "entry_index",
        ].astype(int).to_numpy()
        if len(entries) == 0:
            continue

        u = float(w.U)
        c = float(w.U - w.B_periodic)
        window_rows.append({
            "start_index": start,
            "end_index": end,
            "start_date": w.start_date,
            "end_date": w.end_date,
            "U": u,
            "B_periodic": float(w.B_periodic),
            "C": c,
            "entry_count": int(len(entries)),
        })

        for entry in entries:
            pe = float(path_by_entry.loc[int(entry)])
            q = u - pe
            if q < -EPS:
                raise RuntimeError(f"Q invariant violated: U={u} P_E={pe} Q={q}")
            if abs(q) <= EPS:
                q = 0.0
            rows.append({
                "start_index": start,
                "entry_index": int(entry),
                "C": c,
                "U": u,
                "P_E": pe,
                "Q": float(q),
            })

    wf = pd.DataFrame(window_rows)
    pf = pd.DataFrame(rows)
    if wf.empty or pf.empty:
        raise RuntimeError("no ungated C/Q observations")

    c = wf["C"]
    q = pf["Q"]
    print(
        f"S1 CQ FULL START ticker={TICKER} rows={audit.rows} first={audit.start} last={audit.end} W={WINDOW}"
    )
    print(
        f"S1 CQ FULL SUPPORT windows={len(wf)} pairs={len(pf)} entries_per_window_mean={len(pf)/len(wf):.3f} "
        f"entries_per_window_median={wf['entry_count'].median():.1f}"
    )
    print(
        f"S1 CQ FULL C mean={c.mean():.6f} min={c.min():.6f} "
        f"p01={pct(c,0.01):.6f} p05={pct(c,0.05):.6f} p10={pct(c,0.10):.6f} "
        f"p25={pct(c,0.25):.6f} median={pct(c,0.50):.6f} p75={pct(c,0.75):.6f} "
        f"p90={pct(c,0.90):.6f} p95={pct(c,0.95):.6f} p99={pct(c,0.99):.6f} max={c.max():.6f}"
    )
    print(
        f"S1 CQ FULL Q mean={q.mean():.6f} min={q.min():.6f} "
        f"p01={pct(q,0.01):.6f} p05={pct(q,0.05):.6f} p10={pct(q,0.10):.6f} "
        f"p25={pct(q,0.25):.6f} median={pct(q,0.50):.6f} p75={pct(q,0.75):.6f} "
        f"p90={pct(q,0.90):.6f} p95={pct(q,0.95):.6f} p99={pct(q,0.99):.6f} max={q.max():.6f} "
        f"zero_rate={(q == 0.0).mean():.6f}"
    )
    print("S1 CQ FULL COMPLETE")


if __name__ == "__main__":
    main()

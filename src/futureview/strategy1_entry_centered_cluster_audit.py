from __future__ import annotations

import os
from collections import Counter

import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-entry-centered-cluster-audit.csv")
EPS = 1e-12


def _build() -> pd.DataFrame:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(df, paths, window=2 * W, stride=1, random_samples=20, random_seed=SEED)
    by_start = windows.set_index("start_index")
    ret_by_entry = paths.set_index("entry_index")["campaign_return"]
    rows = []
    for t in paths["entry_index"].astype(int):
        s, e = t - W + 1, t + W
        if s < 0 or e >= len(df) or s not in by_start.index:
            continue
        wr = by_start.loc[s]
        if isinstance(wr, pd.DataFrame):
            wr = wr.iloc[0]
        u = float(wr.U)
        q = u - float(ret_by_entry.loc[t])
        if q < -EPS:
            raise RuntimeError("Q invariant violated")
        if abs(q) <= EPS:
            q = 0.0
        rows.append({
            "entry_index": int(t),
            "entry_date": pd.Timestamp(df["date"].iloc[t]),
            "C": float(u - wr.B_periodic),
            "Q": float(q),
        })
    return pd.DataFrame(rows).sort_values("entry_index").reset_index(drop=True)


def _episodes(g: pd.DataFrame, max_gap: int) -> list[list[int]]:
    idx = g["entry_index"].astype(int).tolist()
    if not idx:
        return []
    eps = [[idx[0]]]
    for x in idx[1:]:
        if x - eps[-1][-1] <= max_gap:
            eps[-1].append(x)
        else:
            eps.append([x])
    return eps


def main() -> None:
    if W != 30:
        raise ValueError("cluster audit locked to W=30")
    out = _build()
    c, q = out.C, out.Q
    c40, c60 = float(c.quantile(.40)), float(c.quantile(.60))
    q40, q60 = float(q.quantile(.40)), float(q.quantile(.60))
    out["label"] = "neutral"
    out.loc[(c >= c60) & (q <= q40), "label"] = "good"
    out.loc[(c <= c40) & (q >= q60), "label"] = "bad"
    out["year"] = out.entry_date.dt.year
    out.to_csv(OUTPUT, index=False)

    print(f"S1 ECQCL START ticker={TICKER} usable={len(out)} W={W} good={(out.label=='good').sum()} bad={(out.label=='bad').sum()} neutral={(out.label=='neutral').sum()}")

    for lab in ("good", "bad"):
        g = out[out.label == lab]
        years = Counter(g.year.astype(int).tolist())
        year_str = ",".join(f"{y}:{years[y]}" for y in sorted(years))
        print(f"S1 ECQCL YEAR label={lab} {year_str}")
        for gap_name, gap in (("tight5", 5), ("W30", W), ("overlap59", 2*W-1)):
            eps = _episodes(g, gap)
            sizes = sorted((len(x) for x in eps), reverse=True)
            largest = sizes[0] if sizes else 0
            top3 = sum(sizes[:3])
            print(
                f"S1 ECQCL EPISODE label={lab} gap={gap_name} episodes={len(eps)} "
                f"largest={largest} largest_share={(largest/len(g) if len(g) else 0):.6f} "
                f"top3={top3} top3_share={(top3/len(g) if len(g) else 0):.6f} sizes={';'.join(map(str,sizes))}"
            )

    n = len(out)
    cuts = [0, n//3, 2*n//3, n]
    for i in range(3):
        g = out.iloc[cuts[i]:cuts[i+1]]
        print(
            f"S1 ECQCL THIRD part={i+1} n={len(g)} good={(g.label=='good').sum()} bad={(g.label=='bad').sum()} neutral={(g.label=='neutral').sum()} "
            f"first={g.entry_date.iloc[0].date()} last={g.entry_date.iloc[-1].date()}"
        )
    print(f"S1 ECQCL OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 ECQCL COMPLETE")


if __name__ == "__main__":
    main()

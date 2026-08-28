from __future__ import annotations

import os

import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-entry-centered-cq-audit.csv")
EPS = 1e-12


def pct(s: pd.Series, q: float) -> float:
    return float(s.quantile(q))


def main() -> None:
    if W != 30:
        raise ValueError("Entry-centered audit currently locked to W=30")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)

    windows = build_representation_a_table(
        df,
        paths,
        window=2 * W,
        stride=1,
        random_samples=20,
        random_seed=SEED,
    )
    by_start = windows.set_index("start_index")
    ret_by_entry = paths.set_index("entry_index")["campaign_return"]

    rows: list[dict[str, float | int | str]] = []
    for t in paths["entry_index"].astype(int).to_numpy():
        s = t - W + 1
        e = t + W
        if s < 0 or e >= len(df) or s not in by_start.index:
            continue
        w = by_start.loc[s]
        if isinstance(w, pd.DataFrame):
            w = w.iloc[0]
        u = float(w.U)
        pe = float(ret_by_entry.loc[t])
        q = u - pe
        if q < -EPS:
            raise RuntimeError(f"Q invariant violated entry={t} U={u} E={pe} Q={q}")
        if abs(q) <= EPS:
            q = 0.0
        entries = paths.loc[
            (paths["entry_index"].astype(int) >= s)
            & (paths["entry_index"].astype(int) <= e),
            "entry_index",
        ]
        rows.append({
            "entry_index": int(t),
            "entry_date": str(df.index[t].date()) if hasattr(df.index[t], "date") else str(df.index[t]),
            "start_index": int(s),
            "end_index": int(e),
            "U": u,
            "B_periodic": float(w.B_periodic),
            "E_entry": pe,
            "C": float(u - w.B_periodic),
            "Q": float(q),
            "entries_in_centered_2W": int(len(entries)),
        })

    out = pd.DataFrame(rows).sort_values("entry_index").reset_index(drop=True)
    if out.empty:
        raise RuntimeError("no Entry-centered C/Q observations")
    out.to_csv(OUTPUT, index=False)

    c, q = out["C"], out["Q"]
    c20, c25, c40, c50, c60, c75, c80 = [pct(c, x) for x in (0.20, 0.25, 0.40, 0.50, 0.60, 0.75, 0.80)]
    q20, q25, q40, q50, q60, q75, q80 = [pct(q, x) for x in (0.20, 0.25, 0.40, 0.50, 0.60, 0.75, 0.80)]

    print(
        f"S1 ECQ START ticker={TICKER} rows={audit.rows} first={audit.start} last={audit.end} "
        f"W={W} centered=2W legal_entries={len(paths)} usable_entries={len(out)}"
    )
    print(
        f"S1 ECQ C mean={c.mean():.6f} min={c.min():.6f} p01={pct(c,0.01):.6f} p05={pct(c,0.05):.6f} "
        f"p10={pct(c,0.10):.6f} p20={c20:.6f} p25={c25:.6f} p40={c40:.6f} median={c50:.6f} "
        f"p60={c60:.6f} p75={c75:.6f} p80={c80:.6f} p90={pct(c,0.90):.6f} p95={pct(c,0.95):.6f} "
        f"p99={pct(c,0.99):.6f} max={c.max():.6f}"
    )
    print(
        f"S1 ECQ Q mean={q.mean():.6f} min={q.min():.6f} p01={pct(q,0.01):.6f} p05={pct(q,0.05):.6f} "
        f"p10={pct(q,0.10):.6f} p20={q20:.6f} p25={q25:.6f} p40={q40:.6f} median={q50:.6f} "
        f"p60={q60:.6f} p75={q75:.6f} p80={q80:.6f} p90={pct(q,0.90):.6f} p95={pct(q,0.95):.6f} "
        f"p99={pct(q,0.99):.6f} max={q.max():.6f} zero_rate={(q == 0.0).mean():.6f}"
    )
    print(
        f"S1 ECQ REL corr_pearson={c.corr(q, method='pearson'):.6f} corr_spearman={c.corr(q, method='spearman'):.6f} "
        f"entries_mean={out.entries_in_centered_2W.mean():.3f} entries_median={out.entries_in_centered_2W.median():.1f}"
    )

    for label, cm, qm in (
        ("20pct", c >= c80, q <= q20),
        ("25pct", c >= c75, q <= q25),
        ("40pct", c >= c60, q <= q40),
    ):
        good = cm & qm
        bad = (c <= {"20pct": c20, "25pct": c25, "40pct": c40}[label]) & (q >= {"20pct": q80, "25pct": q75, "40pct": q60}[label])
        neutral = ~(good | bad)
        print(
            f"S1 ECQ JOINT band={label} good={int(good.sum())} good_rate={good.mean():.6f} "
            f"bad={int(bad.sum())} bad_rate={bad.mean():.6f} neutral={int(neutral.sum())} neutral_rate={neutral.mean():.6f}"
        )

    qbins = pd.qcut(c.rank(method="first"), 5, labels=False)
    for b in range(5):
        g = out.loc[qbins == b]
        print(
            f"S1 ECQ CBIN bin={b+1} n={len(g)} C_mean={g.C.mean():.6f} Q_mean={g.Q.mean():.6f} "
            f"Q_median={g.Q.median():.6f} zero_Q={(g.Q==0.0).mean():.6f}"
        )

    print(f"S1 ECQ OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 ECQ COMPLETE")


if __name__ == "__main__":
    main()

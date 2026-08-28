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
WINDOW = int(os.environ.get("FUTUREVIEW_WINDOW", "30"))
SHORT_REF = int(os.environ.get("FUTUREVIEW_SHORT_REF", "90"))
LONG_REF = int(os.environ.get("FUTUREVIEW_LONG_REF", "756"))
LOW_QTL = float(os.environ.get("FUTUREVIEW_LOW_QTL", "0.40"))
HIGH_QTL = float(os.environ.get("FUTUREVIEW_HIGH_QTL", "0.60"))
LONG_QTL = float(os.environ.get("FUTUREVIEW_LONG_QTL", "0.50"))
RANDOM_SAMPLES = int(os.environ.get("FUTUREVIEW_A_RANDOM_SAMPLES", "20"))
RANDOM_SEED = int(os.environ.get("FUTUREVIEW_A_RANDOM_SEED", "20260827"))
OUTPUT = os.environ.get("FUTUREVIEW_CQ_90D_OUTPUT", "strategy1-cq-90d-rank-audit.csv")


def build_window_q(windows: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    ret_by_entry = paths.set_index("entry_index")["campaign_return"]
    rows: list[dict[str, float | int | str]] = []
    for w in windows.sort_values("start_index").itertuples(index=False):
        s, e = int(w.start_index), int(w.end_index)
        entries = paths.loc[
            (paths["entry_index"].astype(int) >= s)
            & (paths["entry_index"].astype(int) <= e),
            "entry_index",
        ].astype(int).to_numpy()
        if len(entries) == 0:
            continue
        u = float(w.U)
        qs = np.array([u - float(ret_by_entry.loc[int(x)]) for x in entries], dtype=float)
        if np.any(qs < -1e-12):
            raise RuntimeError("Q=U-P_E invariant violated")
        qs[np.abs(qs) <= 1e-12] = 0.0
        rows.append(
            {
                "start_index": s,
                "end_index": e,
                "start_date": w.start_date,
                "end_date": w.end_date,
                "C": float(w.U - w.B_periodic),
                "Q": float(qs.mean()),
                "Q_median": float(np.median(qs)),
                "Q_min": float(qs.min()),
                "Q_max": float(qs.max()),
                "entry_count": int(len(entries)),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    if WINDOW != 30 or SHORT_REF != 90 or LONG_REF != 756:
        raise ValueError("audit is locked to W=30, rolling short reference=90, long reference=756 sessions")
    if not (
        np.isclose(LOW_QTL, 0.40)
        and np.isclose(HIGH_QTL, 0.60)
        and np.isclose(LONG_QTL, 0.50)
    ):
        raise ValueError("audit is locked to short 40/60 and long 50th percentile")

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
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)

    rows: list[dict[str, float | int | str]] = []
    for row in wq.itertuples(index=False):
        s = int(row.start_index)
        prior = wq.loc[wq["end_index"].astype(int) < s]
        short = prior.loc[prior["end_index"].astype(int) >= s - SHORT_REF]
        long = prior.loc[prior["end_index"].astype(int) >= s - LONG_REF]
        if s < LONG_REF or len(short) < 20 or len(long) < 100:
            continue
        c40 = float(short["C"].quantile(LOW_QTL))
        c60 = float(short["C"].quantile(HIGH_QTL))
        q40 = float(short["Q"].quantile(LOW_QTL))
        q60 = float(short["Q"].quantile(HIGH_QTL))
        c50_3y = float(long["C"].quantile(LONG_QTL))
        q50_3y = float(long["Q"].quantile(LONG_QTL))
        short_high = float(row.C) >= c60 and float(row.Q) <= q60
        short_low = float(row.C) <= c40 and float(row.Q) >= q40
        long_high = float(row.C) > c50_3y and float(row.Q) < q50_3y
        long_low = float(row.C) < c50_3y and float(row.Q) > q50_3y
        if short_high and long_high:
            state = "high"
        elif short_low and long_low:
            state = "low"
        else:
            state = "neutral"
        rows.append({
            "start_index": s, "end_index": int(row.end_index), "start_date": row.start_date,
            "end_date": row.end_date, "C": float(row.C), "Q": float(row.Q), "state": state,
            "short_C40": c40, "short_C60": c60, "short_Q40": q40, "short_Q60": q60,
            "long_C50": c50_3y, "long_Q50": q50_3y, "short_reference_count": int(len(short)),
            "long_reference_count": int(len(long)), "short_high": int(short_high),
            "short_low": int(short_low), "long_high": int(long_high), "long_low": int(long_low),
        })

    if not rows:
        raise RuntimeError("no rolling 90D + 3Y classifications produced")
    out = pd.DataFrame(rows)
    out.to_csv(OUTPUT, index=False)

    print(f"S1 CQROLL START ticker={TICKER} rows={audit.rows} first={audit.start} last={audit.end} W={WINDOW} short_ref={SHORT_REF} long_ref={LONG_REF} classified={len(out)}")
    print("S1 CQROLL DEFINITION short=rolling90_C40_C60_Q40_Q60 long=rolling3Y_C50_Q50 high=(C>=short_C60 and Q<=short_Q60 and C>long_C50 and Q<long_Q50) low=(C<=short_C40 and Q>=short_Q40 and C<long_C50 and Q>long_Q50)")
    counts = out["state"].value_counts().to_dict()
    short_high_n = int(out["short_high"].sum()); short_low_n = int(out["short_low"].sum())
    high_n = int(counts.get("high", 0)); low_n = int(counts.get("low", 0))
    print(f"S1 CQROLL TOTAL high={high_n} neutral={counts.get('neutral',0)} low={low_n} short_high={short_high_n} short_low={short_low_n} removed_false_high={short_high_n-high_n} removed_false_low={short_low_n-low_n}")
    for state in ("high", "neutral", "low"):
        g = out.loc[out["state"] == state]
        if g.empty: continue
        print(f"S1 CQROLL FACT state={state} n={len(g)} C_mean={g['C'].mean():.6f} C_median={g['C'].median():.6f} C_p10={g['C'].quantile(0.10):.6f} C_p90={g['C'].quantile(0.90):.6f} Q_mean={g['Q'].mean():.6f} Q_median={g['Q'].median():.6f} Q_p10={g['Q'].quantile(0.10):.6f} Q_p90={g['Q'].quantile(0.90):.6f}")
    bad_high = out.loc[(out["state"] == "high") & ~((out["C"] > out["long_C50"]) & (out["Q"] < out["long_Q50"]))]
    bad_low = out.loc[(out["state"] == "low") & ~((out["C"] < out["long_C50"]) & (out["Q"] > out["long_Q50"]))]
    print(f"S1 CQROLL VALIDATE bad_high={len(bad_high)} bad_low={len(bad_low)} contract_ok={len(bad_high)==0 and len(bad_low)==0}")
    latest = out.sort_values("end_index").iloc[-1]
    latest_wq = wq.loc[wq["end_index"].astype(int) == int(latest.end_index)].iloc[-1]
    print(f"S1 CQROLL LATEST start={latest.start_date} end={latest.end_date} C={latest.C:.6f} Q={latest.Q:.6f} Q_median={latest_wq.Q_median:.6f} Q_min={latest_wq.Q_min:.6f} Q_max={latest_wq.Q_max:.6f} entries={int(latest_wq.entry_count)} state={latest.state} short_C40={latest.short_C40:.6f} short_C60={latest.short_C60:.6f} short_Q40={latest.short_Q40:.6f} short_Q60={latest.short_Q60:.6f} long_C50={latest.long_C50:.6f} long_Q50={latest.long_Q50:.6f}")
    print(f"S1 CQROLL OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 CQROLL COMPLETE")


if __name__ == "__main__":
    main()

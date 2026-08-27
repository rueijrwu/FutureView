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
BLOCK = int(os.environ.get("FUTUREVIEW_BLOCK", "90"))
LOW_QTL = float(os.environ.get("FUTUREVIEW_LOW_QTL", "0.40"))
HIGH_QTL = float(os.environ.get("FUTUREVIEW_HIGH_QTL", "0.60"))
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
        rows.append({
            "start_index": s,
            "end_index": e,
            "start_date": w.start_date,
            "end_date": w.end_date,
            "C": float(w.U - w.B_periodic),
            "Q_mean": float(qs.mean()),
            "Q_median": float(np.median(qs)),
            "Q_min": float(qs.min()),
            "Q_max": float(qs.max()),
            "entry_count": int(len(entries)),
        })
    return pd.DataFrame(rows)


def main() -> None:
    if WINDOW != 30 or BLOCK != 90:
        raise ValueError("audit is currently defined for W=30 and non-overlapping 90-session blocks")
    if not (np.isclose(LOW_QTL, 0.40) and np.isclose(HIGH_QTL, 0.60)):
        raise ValueError("audit is currently defined for 40/60 percentiles")

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
    wq = build_window_q(windows, paths)

    out_parts: list[pd.DataFrame] = []
    block_id = 0
    for b0 in range(0, len(df), BLOCK):
        b1 = min(b0 + BLOCK - 1, len(df) - 1)
        # Only W30 windows fully contained inside this 90-session block.
        part = wq.loc[(wq["start_index"] >= b0) & (wq["end_index"] <= b1)].copy()
        if part.empty:
            continue
        block_id += 1
        c40 = float(part["C"].quantile(LOW_QTL))
        c60 = float(part["C"].quantile(HIGH_QTL))
        q40 = float(part["Q_mean"].quantile(LOW_QTL))
        q60 = float(part["Q_mean"].quantile(HIGH_QTL))

        part["C_percentile"] = part["C"].rank(method="average", pct=True)
        part["Q_percentile"] = part["Q_mean"].rank(method="average", pct=True)
        high = (part["C"] >= c60) & (part["Q_mean"] <= q60)
        low = (part["C"] <= c40) & (part["Q_mean"] >= q40)
        part["state"] = np.where(high, "high", np.where(low, "low", "neutral"))
        part["block_id"] = block_id
        part["block_start_index"] = b0
        part["block_end_index"] = b1
        part["block_start_date"] = str(pd.to_datetime(df.at[b0, "date"]).date())
        part["block_end_date"] = str(pd.to_datetime(df.at[b1, "date"]).date())
        part["C40"] = c40
        part["C60"] = c60
        part["Q40"] = q40
        part["Q60"] = q60
        out_parts.append(part)

        counts = part["state"].value_counts().to_dict()
        print(
            f"S1 CQ90 BLOCK id={block_id} start={part['block_start_date'].iloc[0]} end={part['block_end_date'].iloc[0]} "
            f"n={len(part)} C40={c40:.6f} C60={c60:.6f} Q40={q40:.6f} Q60={q60:.6f} "
            f"high={counts.get('high',0)} neutral={counts.get('neutral',0)} low={counts.get('low',0)}"
        )
        for state in ("high", "neutral", "low"):
            g = part.loc[part["state"] == state]
            if g.empty:
                continue
            print(
                f"S1 CQ90 FACT block={block_id} state={state} n={len(g)} "
                f"C_mean={g['C'].mean():.6f} C_median={g['C'].median():.6f} "
                f"Q_mean={g['Q_mean'].mean():.6f} Q_median={g['Q_mean'].median():.6f}"
            )

    if not out_parts:
        raise RuntimeError("no complete 90-session blocks with contained W30 windows")
    out = pd.concat(out_parts, ignore_index=True)
    out.to_csv(OUTPUT, index=False)
    print(
        f"S1 CQ90 START ticker={TICKER} rows={audit.rows} first={audit.start} last={audit.end} "
        f"W={WINDOW} block={BLOCK} blocks={out['block_id'].nunique()} windows={len(out)}"
    )
    total = out["state"].value_counts().to_dict()
    print(
        f"S1 CQ90 TOTAL high={total.get('high',0)} neutral={total.get('neutral',0)} low={total.get('low',0)} "
        f"high_rate={(out['state']=='high').mean():.6f} low_rate={(out['state']=='low').mean():.6f}"
    )
    print(f"S1 CQ90 OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 CQ90 COMPLETE")


if __name__ == "__main__":
    main()

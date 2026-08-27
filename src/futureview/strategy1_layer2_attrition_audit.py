from __future__ import annotations

import os
import numpy as np
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


def feature_series(df: pd.DataFrame) -> np.ndarray:
    p = df["close"].to_numpy(dtype=np.float64)
    v = df["volume"].to_numpy(dtype=np.float64)
    out = np.full((len(df), 8), np.nan, dtype=np.float64)
    for j, n in enumerate((5, 10, 20, 60)):
        ps = pd.Series(p).shift(1).rolling(n).sum().to_numpy()
        vs = pd.Series(v).shift(1).rolling(n).sum().to_numpy()
        out[:, j] = p / ps
        out[:, 4 + j] = v / vs
    return out


def centered_targets(df: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    windows = build_representation_a_table(
        df, paths, window=2 * W, stride=1, random_samples=20, random_seed=SEED
    )
    by_start = windows.set_index("start_index")
    ret_by_entry = paths.set_index("entry_index")["campaign_return"]
    rows = []
    for t in paths["entry_index"].astype(int).to_numpy():
        s = t - W + 1
        e = t + W
        if s < 0 or e >= len(df) or s not in by_start.index:
            continue
        w = by_start.loc[s]
        if isinstance(w, pd.DataFrame):
            w = w.iloc[0]
        u = float(w.U)
        rows.append({
            "decision_index": t,
            "target_start": s,
            "target_end": e,
            "C": float(u - w.B_periodic),
            "Q": max(0.0, u - float(ret_by_entry.loc[t])),
        })
    return pd.DataFrame(rows)


def build_gate(df, paths):
    windows = build_representation_a_table(
        df, paths, window=W, stride=1, random_samples=20, random_seed=SEED
    )
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)
    rows = []
    for r in wq.itertuples(index=False):
        s = int(r.start_index)
        prior = wq.loc[wq["end_index"].astype(int) < s]
        short = prior.loc[prior["end_index"].astype(int) >= s - SHORT_REF]
        long = prior.loc[prior["end_index"].astype(int) >= s - LONG_REF]
        if s < LONG_REF or len(short) < 20 or len(long) < 100:
            continue
        c40, c60 = (float(short["C"].quantile(q)) for q in (0.40, 0.60))
        q40, q60 = (float(short["Q"].quantile(q)) for q in (0.40, 0.60))
        c50, q50 = float(long["C"].median()), float(long["Q"].median())
        high = float(r.C) >= c60 and float(r.Q) <= q60 and float(r.C) > c50 and float(r.Q) < q50
        low = float(r.C) <= c40 and float(r.Q) >= q40 and float(r.C) < c50 and float(r.Q) > q50
        rows.append((s, int(r.end_index), 1 if high else (-1 if low else 0)))
    return rows


def main() -> None:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    path_entries = set(paths["entry_index"].astype(int).tolist())
    targets = centered_targets(df, paths)
    target_entries = set(targets["decision_index"].astype(int).tolist())
    gate_rows = build_gate(df, paths)
    pass_rows = [(s, e, g) for s, e, g in gate_rows if g != 0]
    pass_starts = {s for s, _, _ in pass_rows}
    pass_ends = {e for _, e, _ in pass_rows}

    pass_start_entries = pass_starts & path_entries
    pass_end_entries = pass_ends & path_entries
    pass_start_targets = pass_starts & target_entries
    pass_end_targets = pass_ends & target_entries

    inherited = []
    for t in sorted(target_entries):
        avail = [(s, e, g) for s, e, g in pass_rows if e < t]
        if avail:
            inherited.append((t, avail[-1][1], avail[-1][2]))

    feats = feature_series(df)
    inherited_finite = []
    for t, ge, g in inherited:
        s = t - W + 1
        x = feats[s:t+1].T
        if x.shape == (8, W) and np.isfinite(x).all():
            inherited_finite.append((t, ge, g))

    print(
        f"S1 L2 ATTR START ticker={TICKER} rows={audit.rows} legal_entries={len(path_entries)} "
        f"centered_targets={len(target_entries)} classified_windows={len(gate_rows)}"
    )
    print(
        f"S1 L2 ATTR GATE high={sum(g==1 for _,_,g in gate_rows)} "
        f"neutral={sum(g==0 for _,_,g in gate_rows)} low={sum(g==-1 for _,_,g in gate_rows)} pass={len(pass_rows)}"
    )
    print(
        f"S1 L2 ATTR EXACT pass_start_is_entry={len(pass_start_entries)} "
        f"pass_end_is_entry={len(pass_end_entries)} pass_start_has_centered_target={len(pass_start_targets)} "
        f"pass_end_has_centered_target={len(pass_end_targets)}"
    )
    print(
        f"S1 L2 ATTR CURRENT inherited_non_neutral_gate_targets={len(inherited)} "
        f"finite_features={len(inherited_finite)}"
    )
    if inherited:
        lags = np.asarray([t-ge for t,ge,_ in inherited], dtype=int)
        print(
            f"S1 L2 ATTR LAG gate_end_to_decision median={np.median(lags):.1f} "
            f"p90={np.quantile(lags,0.90):.1f} max={lags.max()} within30={int((lags<=W).sum())}"
        )
    print("S1 L2 ATTR COMPLETE")


if __name__ == "__main__":
    main()

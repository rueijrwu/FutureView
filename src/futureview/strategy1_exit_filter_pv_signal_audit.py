from __future__ import annotations

import os
import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1_layer2_forward_smoke import make_input_features
from .strategy1_exit_window_cq_audit import build_exit_window_cq, classify_exit_windows

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
LOOKBACK = int(os.environ.get("FUTUREVIEW_LOOKBACK", "60"))
HORIZON = int(os.environ.get("FUTUREVIEW_HORIZON", "3"))
K = int(os.environ.get("FUTUREVIEW_K", "7"))
MIN_PRIOR = int(os.environ.get("FUTUREVIEW_MIN_PRIOR", "50"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-exit-filter-pv-signal-audit.csv")


def _flatten_features(df: pd.DataFrame, end: int) -> np.ndarray:
    start = end - LOOKBACK + 1
    x = make_input_features(df, start, end)
    return x.reshape(-1).astype(np.float64)


def _score_group(rows: pd.DataFrame, df: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = rows.sort_values("end_index").reset_index(drop=True)
    feats: list[np.ndarray] = []
    y: list[float] = []
    valid_rows: list[pd.Series] = []
    close = df["close"].to_numpy(dtype=float)
    for _, r in rows.iterrows():
        e = int(r.end_index)
        if e - LOOKBACK + 1 < 0 or e + HORIZON >= len(df):
            continue
        feats.append(_flatten_features(df, e))
        y.append(float(np.log(close[e + HORIZON] / close[e])))
        valid_rows.append(r)
    if not feats:
        return pd.DataFrame()
    X = np.stack(feats)
    Y = np.asarray(y, dtype=float)
    recs: list[dict[str, object]] = []
    for i in range(len(X)):
        if i < MIN_PRIOR:
            continue
        d = np.mean((X[:i] - X[i]) ** 2, axis=1)
        nn = np.argsort(d)[: min(K, i)]
        score = float(np.mean(Y[nn]))
        r = valid_rows[i]
        recs.append({
            "group": label,
            "state": str(r.state),
            "end_index": int(r.end_index),
            "end_date": str(r.end_date),
            "actual_r3": float(Y[i]),
            "pv_score": score,
        })
    return pd.DataFrame(recs)


def _report(g: pd.DataFrame, label: str) -> None:
    if g.empty:
        print(f"S1 EXITPV GROUP label={label} n=0")
        return
    rho = float(g["actual_r3"].corr(g["pv_score"], method="spearman"))
    pear = float(g["actual_r3"].corr(g["pv_score"], method="pearson"))
    lo = float(g["pv_score"].quantile(0.20))
    hi = float(g["pv_score"].quantile(0.80))
    b = np.where(g["pv_score"] <= lo, "bottom20", np.where(g["pv_score"] >= hi, "top20", "middle60"))
    gg = g.copy(); gg["bucket"] = b
    print(f"S1 EXITPV GROUP label={label} n={len(g)} spearman={rho:.6f} pearson={pear:.6f}")
    for name in ("bottom20","middle60","top20"):
        x = gg.loc[gg.bucket == name, "actual_r3"].to_numpy(dtype=float)
        if len(x):
            print(f"S1 EXITPV BUCKET label={label} bucket={name} n={len(x)} mean={x.mean():.6f} median={np.median(x):.6f} p_up={(x>0).mean():.6f}")


def main() -> None:
    if LOOKBACK != 60 or HORIZON != 3:
        raise ValueError("audit locked to lookback=60 and horizon=3")
    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    wq = build_exit_window_cq(df)
    classified = classify_exit_windows(wq)
    all_g = _score_group(classified, df, "all")
    nn_g = _score_group(classified.loc[classified.state != "neutral"], df, "non_neutral")
    n_g = _score_group(classified.loc[classified.state == "neutral"], df, "neutral")
    out = pd.concat([all_g, nn_g, n_g], ignore_index=True)
    out.to_csv(OUTPUT, index=False)
    print(f"S1 EXITPV START ticker={TICKER} rows={audit.rows} classified={len(classified)} lookback={LOOKBACK} horizon={HORIZON} k={K} min_prior={MIN_PRIOR}")
    _report(all_g, "all")
    _report(nn_g, "non_neutral")
    _report(n_g, "neutral")
    print(f"S1 EXITPV OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 EXITPV COMPLETE")


if __name__ == "__main__":
    main()

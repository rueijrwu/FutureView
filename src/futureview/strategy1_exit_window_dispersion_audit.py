from __future__ import annotations

import os
import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_exit_window_cq_audit import final_exit_index
from .strategy1_representation_a import _periodic_baseline

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-exit-window-dispersion-audit.csv")


def build_table(df: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    close = df["close"].to_numpy(dtype=float)
    p = paths.copy()
    p["final_exit_index"] = final_exit_index(p)
    rows: list[dict[str, object]] = []
    for start in range(0, len(df) - W + 1):
        end = start + W - 1
        g = p.loc[(p.final_exit_index >= start) & (p.final_exit_index <= end)]
        if g.empty:
            continue
        r = g["campaign_return"].to_numpy(dtype=float)
        u = float(np.max(r))
        b = float(_periodic_baseline(close, start, end))
        d = u - r
        d[np.abs(d) <= 1e-12] = 0.0
        rows.append({
            "start_index": start,
            "end_index": end,
            "start_date": str(pd.Timestamp(df.at[start, "date"]).date()),
            "end_date": str(pd.Timestamp(df.at[end, "date"]).date()),
            "U": u,
            "B_periodic": b,
            "C": u - b,
            "D_mean": float(np.mean(d)),
            "D_std": float(np.std(d, ddof=0)),
            "D_median": float(np.median(d)),
            "D_p75": float(np.quantile(d, 0.75)),
            "D_max": float(np.max(d)),
            "path_return_mean": float(np.mean(r)),
            "path_return_std": float(np.std(r, ddof=0)),
            "path_count": int(len(r)),
        })
    return pd.DataFrame(rows)


def corr(frame: pd.DataFrame, a: str, b: str, method: str = "spearman") -> float:
    x = frame[[a,b]].dropna()
    if len(x) < 3 or x[a].nunique() < 2 or x[b].nunique() < 2:
        return float("nan")
    return float(x[a].corr(x[b], method=method))


def bucket_report(frame: pd.DataFrame, metric: str) -> None:
    lo = float(frame[metric].quantile(.2))
    hi = float(frame[metric].quantile(.8))
    bucket = np.where(frame[metric] <= lo, "bottom20", np.where(frame[metric] >= hi, "top20", "middle60"))
    f = frame.copy(); f["bucket"] = bucket
    for name in ("bottom20","middle60","top20"):
        g = f[f.bucket == name]
        print(f"S1 EXITDISP BUCKET metric={metric} bucket={name} n={len(g)} C_mean={g.C.mean():.6f} U_mean={g.U.mean():.6f} D_mean_mean={g.D_mean.mean():.6f} D_std_mean={g.D_std.mean():.6f} paths_mean={g.path_count.mean():.3f}")


def main() -> None:
    if W != 30:
        raise ValueError("audit locked to W30")
    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    out = build_table(df, paths)
    out.to_csv(OUTPUT, index=False)

    print(f"S1 EXITDISP START ticker={TICKER} rows={audit.rows} paths={len(paths)} windows={len(out)}")
    print("S1 EXITDISP DEFINITION membership=final_exit_in_W unfinished_paths=excluded D_i=U-P_i D_mean=mean(D_i) D_std=std_population(D_i)=std_population(P_i)")
    print(f"S1 EXITDISP COVERAGE total_possible={len(df)-W+1} usable={len(out)} zero_path={(len(df)-W+1)-len(out)} one_path={(out.path_count==1).sum()} multi_path={(out.path_count>=2).sum()}")
    for col in ("U","C","D_mean","D_std","D_median","D_p75","D_max","path_count"):
        v = out[col].astype(float)
        print(f"S1 EXITDISP DIST metric={col} mean={v.mean():.6f} median={v.median():.6f} p10={v.quantile(.1):.6f} p90={v.quantile(.9):.6f}")

    for a in ("C","U","D_mean","D_std","path_count"):
        for b in ("C","U","D_mean","D_std","path_count"):
            if a >= b:
                continue
            print(f"S1 EXITDISP CORR a={a} b={b} spearman={corr(out,a,b):.6f} pearson={corr(out,a,b,'pearson'):.6f}")

    multi = out[out.path_count >= 2].copy()
    print(f"S1 EXITDISP MULTI n={len(multi)}")
    if len(multi):
        for metric in ("D_mean","D_std"):
            bucket_report(multi, metric)

    # Forward non-overlapping W: inspect whether dispersion itself carries state information.
    ordered = out.sort_values("start_index").reset_index(drop=True)
    pairs: list[dict[str,float]] = []
    for _, r in ordered.iterrows():
        nxt = ordered[ordered.start_index.astype(int) > int(r.end_index)]
        if nxt.empty:
            continue
        n = nxt.iloc[0]
        pairs.append({
            "C": float(r.C), "U": float(r.U), "D_mean": float(r.D_mean), "D_std": float(r.D_std),
            "future_C": float(n.C), "future_U": float(n.U), "future_D_mean": float(n.D_mean), "future_D_std": float(n.D_std),
        })
    p = pd.DataFrame(pairs)
    print(f"S1 EXITDISP FORWARD n={len(p)}")
    if len(p):
        for a in ("C","U","D_mean","D_std"):
            for b in ("future_C","future_U","future_D_mean","future_D_std"):
                print(f"S1 EXITDISP FORWARD_CORR a={a} b={b} spearman={corr(p,a,b):.6f}")

    print(f"S1 EXITDISP OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 EXITDISP COMPLETE")

if __name__ == "__main__":
    main()

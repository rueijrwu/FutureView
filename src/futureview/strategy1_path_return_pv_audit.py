from __future__ import annotations

import os
import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
LOOKBACKS = tuple(int(x) for x in os.environ.get("FUTUREVIEW_LOOKBACKS", "30,60,90").split(","))
K = int(os.environ.get("FUTUREVIEW_K", "5"))
MIN_PRIOR = int(os.environ.get("FUTUREVIEW_MIN_PRIOR", "40"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260904"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-path-return-pv-audit.csv")


def norm_pv(df: pd.DataFrame, start: int, end: int) -> np.ndarray:
    close = df.iloc[start:end+1]["close"].to_numpy(dtype=np.float64)
    volume = df.iloc[start:end+1]["volume"].to_numpy(dtype=np.float64)
    lp = np.log(close)
    lv = np.log(volume)
    price = lp - lp[-1]
    sd = float(lv.std())
    volume_z = (lv - lv.mean()) / (sd if sd > 1e-8 else 1.0)
    x = np.stack([price, volume_z]).astype(np.float64)
    return x.reshape(-1)


def describe(a: np.ndarray) -> str:
    return (
        f"n={len(a)} mean={a.mean():.6f} median={np.median(a):.6f} "
        f"p10={np.quantile(a,0.10):.6f} p90={np.quantile(a,0.90):.6f} "
        f"p_pos={(a>0).mean():.6f}"
    )


def assign_buckets(score: np.ndarray) -> np.ndarray:
    lo = float(np.quantile(score, 0.20))
    hi = float(np.quantile(score, 0.80))
    return np.where(score <= lo, "bottom20", np.where(score >= hi, "top20", "middle60"))


def causal_knn(rows: pd.DataFrame, x: np.ndarray, y: np.ndarray, k: int, min_prior: int) -> pd.DataFrame:
    out = []
    for i in range(len(rows)):
        if i < min_prior:
            continue
        # Chronological only: each score uses earlier Entry samples only.
        prior_x = x[:i]
        d = np.sqrt(np.mean((prior_x - x[i]) ** 2, axis=1))
        kk = min(k, len(d))
        idx = np.argpartition(d, kk - 1)[:kk]
        score = float(y[idx].mean())
        out.append({
            "entry_index": int(rows.iloc[i].entry_index),
            "entry_date": str(rows.iloc[i].entry_date),
            "actual_return": float(y[i]),
            "neighbor_mean_return": score,
            "neighbor_mean_distance": float(d[idx].mean()),
        })
    return pd.DataFrame(out)


def perm_pvalue(actual: np.ndarray, score: np.ndarray, observed: float, n_perm: int = 1000) -> float:
    rng = np.random.default_rng(SEED)
    vals = []
    for _ in range(n_perm):
        p = rng.permutation(actual)
        vals.append(pd.Series(p).corr(pd.Series(score), method="spearman"))
    vals = np.asarray(vals, dtype=float)
    return float((np.sum(np.abs(vals) >= abs(observed)) + 1) / (len(vals) + 1))


def main() -> None:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events).sort_values("entry_index").reset_index(drop=True)
    paths["entry_date"] = [pd.Timestamp(df.at[int(i), "date"]).date().isoformat() for i in paths.entry_index]

    y_all = paths["campaign_return"].to_numpy(dtype=float)
    print(f"S1 PRPVA START ticker={TICKER} rows={audit.rows} paths={len(paths)}")
    print(f"S1 PRPVA TARGET {describe(y_all)}")
    for year, g in paths.assign(year=pd.to_datetime(paths.entry_date).dt.year).groupby("year"):
        print(f"S1 PRPVA YEAR year={int(year)} {describe(g.campaign_return.to_numpy(dtype=float))}")

    outputs = []
    for lookback in LOOKBACKS:
        keep = paths[paths.entry_index.astype(int) >= lookback - 1].copy().reset_index(drop=True)
        xs = []
        for r in keep.itertuples(index=False):
            e = int(r.entry_index)
            xs.append(norm_pv(df, e - lookback + 1, e))
        x = np.stack(xs)
        y = keep.campaign_return.to_numpy(dtype=float)
        diag = causal_knn(keep, x, y, K, MIN_PRIOR)
        if len(diag) < 20:
            print(f"S1 PRPVA KNN lookback={lookback} skipped=insufficient_oos n={len(diag)}")
            continue
        rho = float(diag.actual_return.corr(diag.neighbor_mean_return, method="spearman"))
        pear = float(diag.actual_return.corr(diag.neighbor_mean_return, method="pearson"))
        pval = perm_pvalue(diag.actual_return.to_numpy(dtype=float), diag.neighbor_mean_return.to_numpy(dtype=float), rho)
        diag["bucket"] = assign_buckets(diag.neighbor_mean_return.to_numpy(dtype=float))
        diag["lookback"] = lookback
        outputs.append(diag)
        print(
            f"S1 PRPVA KNN lookback={lookback} oos={len(diag)} k={K} min_prior={MIN_PRIOR} "
            f"pearson={pear:.6f} spearman={rho:.6f} permutation_p={pval:.6f}"
        )
        for bucket in ("bottom20", "middle60", "top20"):
            g = diag.loc[diag.bucket == bucket, "actual_return"].to_numpy(dtype=float)
            if len(g):
                print(f"S1 PRPVA BUCKET lookback={lookback} bucket={bucket} {describe(g)}")

    if outputs:
        out = pd.concat(outputs, ignore_index=True)
        out.to_csv(OUTPUT, index=False)
        print(f"S1 PRPVA OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 PRPVA COMPLETE")


if __name__ == "__main__":
    main()

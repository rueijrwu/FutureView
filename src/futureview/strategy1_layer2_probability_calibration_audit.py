from __future__ import annotations

import os
import numpy as np
import pandas as pd
import torch

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_entry_exit_cq_compare import build_cq
from .strategy1_exit_window_cq_audit import classify_causal
from .strategy1_layer2_price_distribution import EPOCHS, HORIZON, MODEL_HISTORY, SEED, W, _train, PriceDistributionData
from .strategy1_layer2_forward_smoke import make_input_features

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
MIN_TRAIN = int(os.environ.get("FUTUREVIEW_MIN_TRAIN", "100"))
MIN_VALID = int(os.environ.get("FUTUREVIEW_MIN_VALID", "20"))
ROLL_N = int(os.environ.get("FUTUREVIEW_CAL_ROLL_N", "100"))
ROLL_MIN = int(os.environ.get("FUTUREVIEW_CAL_ROLL_MIN", "60"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer2-probability-calibration-audit.csv")


def build_samples(df: pd.DataFrame, states: pd.DataFrame) -> PriceDistributionData:
    close = df["close"].to_numpy(dtype=np.float64)
    xs, ys, rows = [], [], []
    for r in states.itertuples(index=False):
        if str(r.state_entry) == "neutral" and str(r.state_exit) == "neutral":
            continue
        cutoff = int(r.end_index)
        future = cutoff + HORIZON
        start = cutoff - MODEL_HISTORY + 1
        if start < 0 or future >= len(df):
            continue
        xs.append(make_input_features(df, start, cutoff))
        ys.append(float(np.log(close[future] / close[cutoff])))
        rows.append({"cutoff_index": cutoff, "cutoff_date": pd.Timestamp(df.at[cutoff, "date"]).date().isoformat(), "actual_r3": ys[-1]})
    if not xs:
        raise RuntimeError("no dual-filter samples")
    return PriceDistributionData(x=torch.from_numpy(np.stack(xs)), y=torch.tensor(ys, dtype=torch.float32), rows=pd.DataFrame(rows))


def metrics(p: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    obs = (y > 0).astype(float)
    brier = float(np.mean((p - obs) ** 2))
    bias = float(np.mean(p) - np.mean(obs))
    return float(np.mean(p)), float(np.mean(obs)), brier, bias


def reliability(prefix: str, frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    q = min(5, max(1, len(frame) // 20))
    work = frame.copy()
    work["cal_bin"] = pd.qcut(work.pred_p_up.rank(method="first"), q=q, labels=False, duplicates="drop")
    ece_num = 0.0
    for b, g in work.groupby("cal_bin", sort=True):
        mp, op, br, bias = metrics(g.pred_p_up.to_numpy(float), g.actual_r3.to_numpy(float))
        gap = abs(mp - op)
        ece_num += len(g) * gap
        print(f"S1 CAL BIN scope={prefix} bin={int(b)} n={len(g)} pred_mean={mp:.6f} observed_up={op:.6f} gap={gap:.6f} brier={br:.6f}")
    mp, op, br, bias = metrics(work.pred_p_up.to_numpy(float), work.actual_r3.to_numpy(float))
    ece = ece_num / len(work)
    print(f"S1 CAL SUMMARY scope={prefix} n={len(work)} pred_mean={mp:.6f} observed_up={op:.6f} bias={bias:.6f} brier={br:.6f} ece_qbin={ece:.6f}")


def main() -> None:
    if W != 30 or MODEL_HISTORY != 90 or HORIZON != 3:
        raise ValueError("calibration audit locked to W30/L90/future3")
    torch.set_num_threads(2)
    np.random.seed(SEED); torch.manual_seed(SEED)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    entry = build_cq(df, paths, membership="entry")
    exit_ = build_cq(df, paths, membership="exit")
    ce = classify_causal(entry.rename(columns={"B": "B_periodic"}))
    cx = classify_causal(exit_.rename(columns={"B": "B_periodic"}))
    states = ce[["start_index", "end_index", "state"]].merge(cx[["start_index", "end_index", "state"]], on=["start_index", "end_index"], suffixes=("_entry", "_exit"), how="inner").sort_values("end_index")
    data = build_samples(df, states)
    rows = data.rows.copy().reset_index(drop=True)
    rows["year"] = pd.to_datetime(rows.cutoff_date).dt.year.astype(int)

    outputs = []
    for year in sorted(rows.year.unique()):
        train_mask = rows.year < year
        valid_mask = rows.year == year
        if int(train_mask.sum()) < MIN_TRAIN or int(valid_mask.sum()) < MIN_VALID:
            continue
        np.random.seed(SEED); torch.manual_seed(SEED)
        model = _train(data.x[torch.from_numpy(train_mask.to_numpy(copy=True))], data.y[torch.from_numpy(train_mask.to_numpy(copy=True))])
        model.eval()
        with torch.no_grad():
            _, logit = model(data.x[torch.from_numpy(valid_mask.to_numpy(copy=True))])
            p = torch.sigmoid(logit).numpy()
        f = rows.loc[valid_mask].copy().reset_index(drop=True)
        f["pred_p_up"] = p
        f["train_n"] = int(train_mask.sum())
        outputs.append(f)
        reliability(f"year{year}", f)

    if not outputs:
        raise RuntimeError("no eligible folds")
    out = pd.concat(outputs, ignore_index=True).sort_values("cutoff_index").reset_index(drop=True)
    reliability("pooled", out)

    # Pure causal rolling audit: each reported point summarizes only the immediately preceding OOS predictions.
    roll_rows = []
    for i in range(ROLL_MIN, len(out)):
        lo = max(0, i - ROLL_N)
        g = out.iloc[lo:i]
        mp, op, br, bias = metrics(g.pred_p_up.to_numpy(float), g.actual_r3.to_numpy(float))
        roll_rows.append({"cutoff_index": int(out.iloc[i].cutoff_index), "cutoff_date": out.iloc[i].cutoff_date, "window_n": len(g), "pred_mean": mp, "observed_up": op, "bias": bias, "brier": br})
    roll = pd.DataFrame(roll_rows)
    if len(roll):
        for r in roll.iloc[::max(1, len(roll)//8)].itertuples(index=False):
            print(f"S1 CAL ROLL date={r.cutoff_date} n={r.window_n} pred_mean={r.pred_mean:.6f} observed_up={r.observed_up:.6f} bias={r.bias:.6f} brier={r.brier:.6f}")
        last = roll.iloc[-1]
        print(f"S1 CAL ROLL_LAST date={last.cutoff_date} n={int(last.window_n)} pred_mean={last.pred_mean:.6f} observed_up={last.observed_up:.6f} bias={last.bias:.6f} brier={last.brier:.6f}")

    out.to_csv(OUTPUT, index=False)
    roll.to_csv(OUTPUT.replace('.csv', '-rolling.csv'), index=False)
    print(f"S1 CAL START ticker={TICKER} rows={audit.rows} oos={len(out)} roll_n={ROLL_N} roll_min={ROLL_MIN} epochs={EPOCHS}")
    print("S1 CAL COMPLETE")

if __name__ == "__main__":
    main()

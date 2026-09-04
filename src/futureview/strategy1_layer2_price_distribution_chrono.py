from __future__ import annotations

import os

import numpy as np
import pandas as pd
import torch

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table
from .strategy1_cq_90d_rank_audit import build_window_q
from .strategy1_layer1_forward_w_audit import _classify
from .strategy1_layer2_price_distribution import (
    EPOCHS,
    HORIZON,
    MODEL_HISTORY,
    SEED,
    W,
    _train,
    build_selected_samples,
)

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
MIN_TRAIN = int(os.environ.get("FUTUREVIEW_MIN_TRAIN", "100"))
MIN_VALID = int(os.environ.get("FUTUREVIEW_MIN_VALID", "20"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer2-price-distribution-chrono.csv")


def assign_fold_buckets(frame: pd.DataFrame, score_col: str) -> pd.Series:
    lo = float(frame[score_col].quantile(0.20))
    hi = float(frame[score_col].quantile(0.80))
    return pd.Series(
        np.where(frame[score_col] >= hi, "top20", np.where(frame[score_col] <= lo, "bottom20", "middle60")),
        index=frame.index,
        dtype="object",
    )


def describe(actual: np.ndarray) -> str:
    return (
        f"n={len(actual)} mean={actual.mean():.6f} median={np.median(actual):.6f} "
        f"p10={np.quantile(actual,0.10):.6f} p90={np.quantile(actual,0.90):.6f} "
        f"p_up={(actual > 0).mean():.6f}"
    )


def main() -> None:
    if W != 30 or MODEL_HISTORY != 90 or HORIZON != 3:
        raise ValueError("chronological Layer2 audit is locked to W30/L90/future3")

    torch.set_num_threads(2)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(df, paths, window=W, stride=1, random_samples=20, random_seed=SEED)
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)
    classified = _classify(wq).sort_values("end_index").reset_index(drop=True)
    data = build_selected_samples(df, classified)

    rows = data.rows.copy().reset_index(drop=True)
    rows["year"] = pd.to_datetime(rows["cutoff_date"]).dt.year.astype(int)

    outputs: list[pd.DataFrame] = []
    eligible_years: list[int] = []
    for year in sorted(rows["year"].unique()):
        train_mask = rows["year"] < year
        valid_mask = rows["year"] == year
        n_train = int(train_mask.sum())
        n_valid = int(valid_mask.sum())
        if n_train < MIN_TRAIN or n_valid < MIN_VALID:
            continue
        eligible_years.append(int(year))

        train_x = data.x[torch.from_numpy(train_mask.to_numpy(copy=True))]
        train_y = data.y[torch.from_numpy(train_mask.to_numpy(copy=True))]
        valid_x = data.x[torch.from_numpy(valid_mask.to_numpy(copy=True))]
        valid_y = data.y[torch.from_numpy(valid_mask.to_numpy(copy=True))]

        # Keep architecture, hyperparameters, and seed fixed across folds.
        np.random.seed(SEED)
        torch.manual_seed(SEED)
        model = _train(train_x, train_y)
        model.eval()
        with torch.no_grad():
            q, logit = model(valid_x)
            p_up = torch.sigmoid(logit)

        qn = q.numpy()
        pn = p_up.numpy()
        yn = valid_y.numpy()
        fold = rows.loc[valid_mask].copy().reset_index(drop=True)
        fold["train_n"] = n_train
        fold["pred_q10"] = qn[:, 0]
        fold["pred_q50"] = qn[:, 1]
        fold["pred_q90"] = qn[:, 2]
        fold["pred_p_up"] = pn
        fold["bucket_pred_p_up"] = assign_fold_buckets(fold, "pred_p_up")
        fold["bucket_pred_q50"] = assign_fold_buckets(fold, "pred_q50")
        outputs.append(fold)

        coverage80 = float(((yn >= qn[:, 0]) & (yn <= qn[:, 2])).mean())
        direction_acc = float(((pn >= 0.5) == (yn > 0)).mean())
        q50_s = float(pd.Series(yn).corr(pd.Series(qn[:, 1]), method="spearman"))
        p_s = float(pd.Series(yn).corr(pd.Series(pn), method="spearman"))
        print(
            f"S1 L2PDCH FOLD year={year} train={n_train} valid={n_valid} "
            f"coverage80={coverage80:.6f} direction_acc={direction_acc:.6f} "
            f"q50_spearman={q50_s:.6f} p_up_spearman={p_s:.6f}"
        )
        for score in ("pred_p_up", "pred_q50"):
            for bucket in ("bottom20", "middle60", "top20"):
                g = fold.loc[fold[f"bucket_{score}"] == bucket, "actual_r3"].to_numpy(dtype=float)
                if len(g):
                    print(f"S1 L2PDCH BUCKET year={year} score={score} bucket={bucket} {describe(g)}")

    if not outputs:
        raise RuntimeError("no eligible chronological folds")

    out = pd.concat(outputs, ignore_index=True)
    out.to_csv(OUTPUT, index=False)
    print(
        f"S1 L2PDCH START ticker={TICKER} rows={audit.rows} selected={len(rows)} "
        f"folds={len(eligible_years)} years={','.join(map(str, eligible_years))} epochs={EPOCHS}"
    )

    for score in ("pred_p_up", "pred_q50"):
        for bucket in ("bottom20", "middle60", "top20"):
            g = out.loc[out[f"bucket_{score}"] == bucket, "actual_r3"].to_numpy(dtype=float)
            if len(g):
                print(f"S1 L2PDCH POOLED score={score} bucket={bucket} {describe(g)}")

    year_summary = []
    for year in eligible_years:
        fold = out.loc[out["year"] == year]
        top = fold.loc[fold["bucket_pred_q50"] == "top20", "actual_r3"].to_numpy(dtype=float)
        bottom = fold.loc[fold["bucket_pred_q50"] == "bottom20", "actual_r3"].to_numpy(dtype=float)
        year_summary.append((year, float((top > 0).mean()), float((bottom > 0).mean()), float(top.mean()), float(bottom.mean())))
    for year, top_p, bottom_p, top_mean, bottom_mean in year_summary:
        print(
            f"S1 L2PDCH YEARSEP year={year} q50_top_p_up={top_p:.6f} q50_bottom_p_up={bottom_p:.6f} "
            f"q50_top_mean={top_mean:.6f} q50_bottom_mean={bottom_mean:.6f}"
        )

    print(f"S1 L2PDCH OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 L2PDCH COMPLETE")


if __name__ == "__main__":
    main()

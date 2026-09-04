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
from .strategy1_layer2_price_distribution import (
    EPOCHS,
    HORIZON,
    MODEL_HISTORY,
    SEED,
    W,
    _train,
    PriceDistributionData,
)
from .strategy1_layer2_forward_smoke import make_input_features
from .strategy1_layer2_price_distribution_chrono import assign_fold_buckets, describe

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
MIN_TRAIN = int(os.environ.get("FUTUREVIEW_MIN_TRAIN", "100"))
MIN_VALID = int(os.environ.get("FUTUREVIEW_MIN_VALID", "20"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer2-price-distribution-dual-filter.csv")
STATE_OUTPUT = os.environ.get("FUTUREVIEW_STATE_OUTPUT", "strategy1-layer1-dual-filter-state.csv")


def build_dual_filter_samples(df: pd.DataFrame, states: pd.DataFrame) -> PriceDistributionData:
    close = df["close"].to_numpy(dtype=np.float64)
    xs: list[np.ndarray] = []
    ys: list[float] = []
    rows: list[dict[str, object]] = []
    for r in states.itertuples(index=False):
        # Drop only the intersection of the two neutral views.
        if str(r.state_entry) == "neutral" and str(r.state_exit) == "neutral":
            continue
        cutoff = int(r.end_index)
        future = cutoff + HORIZON
        input_start = cutoff - MODEL_HISTORY + 1
        if input_start < 0 or future >= len(df):
            continue
        xs.append(make_input_features(df, input_start, cutoff))
        ys.append(float(np.log(close[future] / close[cutoff])))
        rows.append({
            "state_entry": str(r.state_entry),
            "state_exit": str(r.state_exit),
            "cutoff_index": cutoff,
            "future_index": future,
            "cutoff_date": pd.Timestamp(df.at[cutoff, "date"]).date().isoformat(),
            "future_date": pd.Timestamp(df.at[future, "date"]).date().isoformat(),
            "actual_r3": ys[-1],
        })
    if not xs:
        raise RuntimeError("no dual-filter samples")
    return PriceDistributionData(
        x=torch.from_numpy(np.stack(xs)),
        y=torch.tensor(ys, dtype=torch.float32),
        rows=pd.DataFrame(rows),
    )


def main() -> None:
    if W != 30 or MODEL_HISTORY != 90 or HORIZON != 3:
        raise ValueError("dual-filter Layer2 audit locked to W30/L90/future3")

    torch.set_num_threads(2)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)

    entry = build_cq(df, paths, membership="entry")
    exit_ = build_cq(df, paths, membership="exit")
    ce = classify_causal(entry.rename(columns={"B": "B_periodic"}))
    cx = classify_causal(exit_.rename(columns={"B": "B_periodic"}))
    states = ce[["start_index", "end_index", "state"]].merge(
        cx[["start_index", "end_index", "state"]],
        on=["start_index", "end_index"],
        suffixes=("_entry", "_exit"),
        how="inner",
    ).sort_values("end_index").reset_index(drop=True)
    states["drop_dual_neutral"] = (states.state_entry == "neutral") & (states.state_exit == "neutral")
    states.to_csv(STATE_OUTPUT, index=False)

    data = build_dual_filter_samples(df, states)
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

        np.random.seed(SEED)
        torch.manual_seed(SEED)
        model = _train(
            data.x[torch.from_numpy(train_mask.to_numpy(copy=True))],
            data.y[torch.from_numpy(train_mask.to_numpy(copy=True))],
        )
        model.eval()
        valid_x = data.x[torch.from_numpy(valid_mask.to_numpy(copy=True))]
        valid_y = data.y[torch.from_numpy(valid_mask.to_numpy(copy=True))]
        with torch.no_grad():
            q, logit = model(valid_x)
            p_up = torch.sigmoid(logit)

        qn = q.numpy(); pn = p_up.numpy(); yn = valid_y.numpy()
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
            f"S1 L2PDDUAL FOLD year={year} train={n_train} valid={n_valid} "
            f"coverage80={coverage80:.6f} direction_acc={direction_acc:.6f} "
            f"q50_spearman={q50_s:.6f} p_up_spearman={p_s:.6f}"
        )
        for score in ("pred_p_up", "pred_q50"):
            for bucket in ("bottom20", "middle60", "top20"):
                g = fold.loc[fold[f"bucket_{score}"] == bucket, "actual_r3"].to_numpy(dtype=float)
                if len(g):
                    print(f"S1 L2PDDUAL BUCKET year={year} score={score} bucket={bucket} {describe(g)}")

    if not outputs:
        raise RuntimeError("no eligible dual-filter chronological folds")

    out = pd.concat(outputs, ignore_index=True)
    out.to_csv(OUTPUT, index=False)
    cross = states.groupby(["state_entry", "state_exit"]).size().sort_values(ascending=False)
    print(
        f"S1 L2PDDUAL START ticker={TICKER} rows={audit.rows} paired_states={len(states)} "
        f"dual_neutral={int(states.drop_dual_neutral.sum())} kept={int((~states.drop_dual_neutral).sum())} "
        f"selected={len(rows)} folds={len(eligible_years)} years={','.join(map(str, eligible_years))} epochs={EPOCHS}"
    )
    print("S1 L2PDDUAL DEFINITION drop=(entry_neutral AND exit_neutral); keep=NOT(drop); common_Q=population_std(path_returns)")
    for (se, sx), n in cross.items():
        print(f"S1 L2PDDUAL CROSS entry={se} exit={sx} n={int(n)}")

    for score in ("pred_p_up", "pred_q50"):
        for bucket in ("bottom20", "middle60", "top20"):
            g = out.loc[out[f"bucket_{score}"] == bucket, "actual_r3"].to_numpy(dtype=float)
            if len(g):
                print(f"S1 L2PDDUAL POOLED score={score} bucket={bucket} {describe(g)}")

    for year in eligible_years:
        fold = out.loc[out.year == year]
        top = fold.loc[fold.bucket_pred_q50 == "top20", "actual_r3"].to_numpy(dtype=float)
        bottom = fold.loc[fold.bucket_pred_q50 == "bottom20", "actual_r3"].to_numpy(dtype=float)
        print(
            f"S1 L2PDDUAL YEARSEP year={year} q50_top_p_up={(top>0).mean():.6f} "
            f"q50_bottom_p_up={(bottom>0).mean():.6f} q50_top_mean={top.mean():.6f} q50_bottom_mean={bottom.mean():.6f}"
        )
    print(f"S1 L2PDDUAL OUTPUT file={OUTPUT} rows={len(out)} state_file={STATE_OUTPUT}")
    print("S1 L2PDDUAL COMPLETE")

if __name__ == "__main__":
    main()

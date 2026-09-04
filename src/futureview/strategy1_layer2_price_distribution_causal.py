from __future__ import annotations

import os

import numpy as np
import pandas as pd
import torch

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import (
    MERGE_GAP,
    build_extrema_sets,
    preprocess_legal_points,
)
from .strategy1_deterministic_paths_asof import simulate_deterministic_path_asof
from .strategy1_representation_a import _periodic_baseline
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
from .strategy1_layer2_price_distribution_chrono import assign_fold_buckets, describe

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
MIN_TRAIN = int(os.environ.get("FUTUREVIEW_MIN_TRAIN", "100"))
MIN_VALID = int(os.environ.get("FUTUREVIEW_MIN_VALID", "20"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer2-price-distribution-causal.csv")
LAYER1_OUTPUT = os.environ.get("FUTUREVIEW_LAYER1_OUTPUT", "strategy1-layer1-causal-state.csv")


def build_causal_paths_asof(events: pd.DataFrame, asof_index: int) -> pd.DataFrame:
    """Build Strategy paths using only rows <= asof_index.

    Unlike the cached rolling helper, this deliberately rebuilds extrema from the
    prefix so no local-extremum decision can see prices after the current day.
    Any path still open at the cutoff is force-closed at that day's close.
    """
    if asof_index < 0 or asof_index >= len(events):
        raise ValueError("asof_index must be inside events")
    prefix = events.iloc[: asof_index + 1].copy().reset_index(drop=True)
    prepared = preprocess_legal_points(prefix, gap=MERGE_GAP)
    local_mins, local_maxs = build_extrema_sets(prepared)
    entries = np.flatnonzero(prepared["entry_candidate"].to_numpy(dtype=bool))
    rows: list[dict[str, object]] = []
    for raw_entry in entries:
        path = simulate_deterministic_path_asof(
            prepared,
            int(raw_entry),
            local_mins,
            local_maxs,
            asof_index=asof_index,
        )
        if path is None:
            continue
        if path.exit10_index >= 0:
            exit_mode = "exit10"
        elif path.horizon_exit_index >= 0:
            exit_mode = "horizon"
        else:
            exit_mode = "forced_asof"
        rows.append(
            {
                "entry_index": path.entry_index,
                "campaign_return": path.campaign_return,
                "exit_mode": exit_mode,
                "forced_asof_exit_index": path.forced_asof_exit_index,
            }
        )
    return pd.DataFrame(rows)


def build_causal_layer1_wq(df: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    close = df["close"].to_numpy(dtype=float)
    rows: list[dict[str, object]] = []
    for end in range(W - 1, len(df)):
        start = end - W + 1
        paths = build_causal_paths_asof(events, end)
        if paths.empty:
            continue
        cohort = paths.loc[
            (paths["entry_index"].astype(int) >= start)
            & (paths["entry_index"].astype(int) <= end)
        ]
        if cohort.empty:
            continue
        returns = cohort["campaign_return"].to_numpy(dtype=float)
        u = float(np.max(returns))
        q = float(np.mean(u - returns))
        b = _periodic_baseline(close, start, end)
        rows.append(
            {
                "start_index": start,
                "end_index": end,
                "start_date": pd.Timestamp(df.at[start, "date"]).date().isoformat(),
                "end_date": pd.Timestamp(df.at[end, "date"]).date().isoformat(),
                "C": u - b,
                "Q": q,
                "entry_count": int(len(cohort)),
                "forced_entries": int((cohort["exit_mode"] == "forced_asof").sum()),
            }
        )
    if not rows:
        raise RuntimeError("no causal Layer1 W rows")
    return pd.DataFrame(rows).sort_values("start_index").reset_index(drop=True)


def main() -> None:
    if W != 30 or MODEL_HISTORY != 90 or HORIZON != 3:
        raise ValueError("causal pipeline audit is locked to W30/L90/future3")

    torch.set_num_threads(2)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    events = add_strategy1_events(df).reset_index(drop=True)

    wq = build_causal_layer1_wq(df, events)
    classified = _classify(wq).sort_values("end_index").reset_index(drop=True)
    classified.to_csv(LAYER1_OUTPUT, index=False)
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
            f"S1 L2PDCAUSAL FOLD year={year} train={n_train} valid={n_valid} "
            f"coverage80={coverage80:.6f} direction_acc={direction_acc:.6f} "
            f"q50_spearman={q50_s:.6f} p_up_spearman={p_s:.6f}"
        )
        for score in ("pred_p_up", "pred_q50"):
            for bucket in ("bottom20", "middle60", "top20"):
                g = fold.loc[fold[f"bucket_{score}"] == bucket, "actual_r3"].to_numpy(dtype=float)
                if len(g):
                    print(f"S1 L2PDCAUSAL BUCKET year={year} score={score} bucket={bucket} {describe(g)}")

    if not outputs:
        raise RuntimeError(
            f"no eligible causal chronological folds; selected={len(rows)} "
            f"min_train={MIN_TRAIN} min_valid={MIN_VALID}"
        )

    out = pd.concat(outputs, ignore_index=True)
    out.to_csv(OUTPUT, index=False)
    state_counts = classified["state"].value_counts().to_dict()
    print(
        f"S1 L2PDCAUSAL START ticker={TICKER} rows={audit.rows} wq={len(wq)} "
        f"classified={len(classified)} selected={len(rows)} folds={len(eligible_years)} "
        f"years={','.join(map(str, eligible_years))} epochs={EPOCHS} "
        f"high={state_counts.get('high',0)} neutral={state_counts.get('neutral',0)} low={state_counts.get('low',0)}"
    )

    for score in ("pred_p_up", "pred_q50"):
        for bucket in ("bottom20", "middle60", "top20"):
            g = out.loc[out[f"bucket_{score}"] == bucket, "actual_r3"].to_numpy(dtype=float)
            if len(g):
                print(f"S1 L2PDCAUSAL POOLED score={score} bucket={bucket} {describe(g)}")

    for year in eligible_years:
        fold = out.loc[out["year"] == year]
        top = fold.loc[fold["bucket_pred_q50"] == "top20", "actual_r3"].to_numpy(dtype=float)
        bottom = fold.loc[fold["bucket_pred_q50"] == "bottom20", "actual_r3"].to_numpy(dtype=float)
        print(
            f"S1 L2PDCAUSAL YEARSEP year={year} q50_top_p_up={(top>0).mean():.6f} "
            f"q50_bottom_p_up={(bottom>0).mean():.6f} q50_top_mean={top.mean():.6f} "
            f"q50_bottom_mean={bottom.mean():.6f}"
        )

    print(f"S1 L2PDCAUSAL OUTPUT file={OUTPUT} rows={len(out)} layer1_file={LAYER1_OUTPUT}")
    print("S1 L2PDCAUSAL COMPLETE")


if __name__ == "__main__":
    main()

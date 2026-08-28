from __future__ import annotations

import os

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_deterministic_paths_asof import build_deterministic_path_table_asof
from .strategy1_representation_a import _periodic_baseline
from .strategy1_layer1_forward_w_audit import _classify
from .strategy1_layer2_forward_dataset import build_forward_dataset
from .strategy1_layer2_forward_smoke import (
    ForwardCQStateNet,
    STATE_TO_ID,
    ID_TO_STATE,
    build_training_data,
    decode_cq,
    make_input_features,
    nonnegative_q,
    weighted_mean,
)

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
MODEL_HISTORY = int(os.environ.get("FUTUREVIEW_MODEL_HISTORY", "90"))
TRAIN_YEARS = int(os.environ.get("FUTUREVIEW_TRAIN_YEARS", "5"))
VALID_YEARS = int(os.environ.get("FUTUREVIEW_VALID_YEARS", "3"))
NEUTRAL_ALPHA = float(os.environ.get("FUTUREVIEW_NEUTRAL_ALPHA", "0.2"))
EPOCHS = int(os.environ.get("FUTUREVIEW_EPOCHS", "300"))
LR = float(os.environ.get("FUTUREVIEW_LR", "0.003"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
OUTPUT = os.environ.get("FUTUREVIEW_ROLLING_OUTPUT", "strategy1-layer2-rolling-8y.csv")


def _build_wq_from_paths(df: pd.DataFrame, paths: pd.DataFrame, cutoff: int) -> pd.DataFrame:
    close = df["close"].to_numpy(dtype=float)
    ret_by_entry = paths.set_index("entry_index")["campaign_return"]
    rows: list[dict[str, object]] = []
    for start in range(0, cutoff - W + 2):
        end = start + W - 1
        entries = paths.loc[
            (paths["entry_index"].astype(int) >= start)
            & (paths["entry_index"].astype(int) <= end),
            "entry_index",
        ].astype(int).to_numpy()
        if len(entries) == 0:
            continue
        returns = np.array([float(ret_by_entry.loc[int(e)]) for e in entries], dtype=float)
        u = float(returns.max())
        qs = u - returns
        qs[np.abs(qs) <= 1e-12] = 0.0
        if np.any(qs < -1e-12):
            raise RuntimeError("Q=U-R invariant violated")
        b = _periodic_baseline(close, start, end)
        rows.append({
            "start_index": start,
            "end_index": end,
            "start_date": str(pd.Timestamp(df.at[start, "date"]).date()),
            "end_date": str(pd.Timestamp(df.at[end, "date"]).date()),
            "C": u - b,
            "Q": float(qs.mean()),
            "entry_count": int(len(entries)),
        })
    if not rows:
        raise RuntimeError("no rolling W rows")
    return pd.DataFrame(rows).sort_values("start_index").reset_index(drop=True)


def _train_and_predict(df: pd.DataFrame, train_rows: pd.DataFrame, pred_start: int, pred_end: int, seed: int) -> tuple[float, float, np.ndarray]:
    np.random.seed(seed)
    torch.manual_seed(seed)
    train = build_training_data(df, train_rows)
    c_mu = train.y_cq[:, 0:1].mean(dim=0, keepdim=True)
    c_sd = train.y_cq[:, 0:1].std(dim=0, keepdim=True, unbiased=False)
    c_sd = torch.where(c_sd < 1e-6, torch.ones_like(c_sd), c_sd)
    q_scale = train.y_cq[:, 1:2].std(dim=0, keepdim=True, unbiased=False)
    q_scale = torch.where(q_scale < 1e-6, torch.ones_like(q_scale), q_scale)
    target_c_z = (train.y_cq[:, 0:1] - c_mu) / c_sd
    target_q_scaled = train.y_cq[:, 1:2] / q_scale

    model = ForwardCQStateNet()
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    reg_fn = nn.SmoothL1Loss(reduction="none")
    cls_fn = nn.CrossEntropyLoss(reduction="none")
    for _ in range(EPOCHS):
        raw, logits = model(train.x)
        reg_c = reg_fn(raw[:, 0:1], target_c_z).squeeze(1)
        reg_q = reg_fn(nonnegative_q(raw[:, 1:2]), target_q_scaled).squeeze(1)
        cls = cls_fn(logits, train.y_state)
        loss = weighted_mean(0.5 * (reg_c + reg_q) + cls, train.weight)
        opt.zero_grad()
        loss.backward()
        opt.step()

    x = torch.from_numpy(make_input_features(df, pred_start, pred_end)[None, ...])
    model.eval()
    with torch.no_grad():
        raw, logits = model(x)
        cq = decode_cq(raw, c_mu, c_sd, q_scale).numpy()[0]
        p = torch.softmax(logits, dim=1).numpy()[0]
    return float(cq[0]), float(cq[1]), p


def _stats(prefix: str, g: pd.DataFrame, actual_col: str, pred_col: str) -> None:
    x = g[[actual_col, pred_col]].dropna()
    if x.empty:
        return
    a = x[actual_col].to_numpy(dtype=float)
    p = x[pred_col].to_numpy(dtype=float)
    d = p - a
    ae = np.abs(d)
    pearson = float(pd.Series(a).corr(pd.Series(p), method="pearson")) if len(x) >= 3 and np.std(a) > 0 and np.std(p) > 0 else float("nan")
    spearman = float(pd.Series(a).corr(pd.Series(p), method="spearman")) if len(x) >= 3 and np.std(a) > 0 and np.std(p) > 0 else float("nan")
    print(f"{prefix} n={len(x)} actual_mean={a.mean():.6f} pred_mean={p.mean():.6f} bias={d.mean():.6f} mae={ae.mean():.6f} medae={np.median(ae):.6f} pearson={pearson:.6f} spearman={spearman:.6f}")


def _full_actual_forward(df: pd.DataFrame) -> pd.DataFrame:
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    wq = _build_wq_from_paths(df, paths, len(df) - 1)
    classified = _classify(wq).sort_values("start_index").reset_index(drop=True)
    return build_forward_dataset(classified, len(df), MODEL_HISTORY)


def main() -> None:
    if DATA_PERIOD != "8y" or W != 30 or MODEL_HISTORY != 90 or TRAIN_YEARS != 5 or VALID_YEARS != 3:
        raise ValueError("rolling audit locked to 8y raw, prior-5y Entry training, final-3y validation, W30/L90")
    if abs(NEUTRAL_ALPHA - 0.2) > 1e-12:
        raise ValueError("rolling audit locked to neutral alpha=0.2")

    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    dates = pd.to_datetime(df["date"]).reset_index(drop=True)
    events = add_strategy1_events(df).reset_index(drop=True)
    actual_forward = _full_actual_forward(df)
    actual_by_start = actual_forward.set_index("target_start")

    final_date = pd.Timestamp(dates.iloc[-1]).normalize()
    valid_cut = final_date - pd.DateOffset(years=VALID_YEARS)
    valid_indices = [i for i in range(MODEL_HISTORY, len(df) - W + 1) if pd.Timestamp(dates.iloc[i]) >= valid_cut]

    out_rows: list[dict[str, object]] = []
    print(f"S1 L2ROLL START ticker={TICKER} rows={audit.rows} validation_days={len(valid_indices)} raw_period={DATA_PERIOD} train_entry_years={TRAIN_YEARS} valid_years={VALID_YEARS} W={W} history={MODEL_HISTORY} alpha={NEUTRAL_ALPHA:.3f} epochs={EPOCHS}")

    for k, target_start in enumerate(valid_indices):
        cutoff = target_start - 1
        floor_date = pd.Timestamp(dates.iloc[cutoff]) - pd.DateOffset(years=TRAIN_YEARS)

        # Only historical Entries in the previous five years are eligible.
        paths_asof = build_deterministic_path_table_asof(events, asof_index=cutoff)
        entry_dates = pd.to_datetime(df.iloc[paths_asof.entry_index.astype(int)]["date"].to_numpy())
        paths_5y = paths_asof.loc[entry_dates >= floor_date].reset_index(drop=True)
        if paths_5y.empty:
            continue

        # Open Entries at the training cutoff are already force-closed by the as-of builder.
        forced_entries = int((paths_5y["exit_mode"] == "forced_asof").sum())
        wq = _build_wq_from_paths(df, paths_5y, cutoff)
        classified = _classify(wq).sort_values("start_index").reset_index(drop=True)
        train_rows = build_forward_dataset(classified, cutoff + 1, MODEL_HISTORY)
        if len(train_rows) < 100:
            continue

        pred_c, pred_q, p = _train_and_predict(df, train_rows, target_start - MODEL_HISTORY, target_start - 1, SEED + target_start)

        actual_c = float("nan")
        actual_q = float("nan")
        actual_state = "unlabeled"
        if target_start in actual_by_start.index:
            r = actual_by_start.loc[target_start]
            if isinstance(r, pd.DataFrame):
                r = r.iloc[0]
            actual_c = float(r.C)
            actual_q = float(r.Q)
            actual_state = str(r.state)

        out_rows.append({
            "prediction_date": pd.Timestamp(dates.iloc[target_start]).date().isoformat(),
            "year": int(pd.Timestamp(dates.iloc[target_start]).year),
            "entry_floor_date": floor_date.date().isoformat(),
            "train_cutoff_date": pd.Timestamp(dates.iloc[cutoff]).date().isoformat(),
            "train_samples": int(len(train_rows)),
            "forced_entries_at_cutoff": forced_entries,
            "actual_C": actual_c,
            "pred_C": pred_c,
            "actual_Q": actual_q,
            "pred_Q": pred_q,
            "actual_state": actual_state,
            "P_H": float(p[STATE_TO_ID["high"]]),
            "P_N": float(p[STATE_TO_ID["neutral"]]),
            "P_L": float(p[STATE_TO_ID["low"]]),
            "pred_state": ID_TO_STATE[int(np.argmax(p))],
        })
        if (k + 1) % 100 == 0:
            print(f"S1 L2ROLL PROGRESS processed={k+1}/{len(valid_indices)} rows_out={len(out_rows)}")

    out = pd.DataFrame(out_rows)
    out.to_csv(OUTPUT, index=False)
    labeled = out.loc[out["actual_state"] != "unlabeled"].copy()
    print(f"S1 L2ROLL DATA predictions={len(out)} labeled={len(labeled)} forced_days={int((out['forced_entries_at_cutoff']>0).sum())} forced_entries_total={int(out['forced_entries_at_cutoff'].sum())}")

    _stats("S1 L2ROLL OVERALL metric=C", labeled, "actual_C", "pred_C")
    _stats("S1 L2ROLL OVERALL metric=Q", labeled, "actual_Q", "pred_Q")
    for state in ("high", "neutral", "low"):
        g = labeled.loc[labeled["actual_state"] == state]
        print(f"S1 L2ROLL STATECOUNT state={state} n={len(g)}")
        _stats(f"S1 L2ROLL STATE state={state} metric=C", g, "actual_C", "pred_C")
        _stats(f"S1 L2ROLL STATE state={state} metric=Q", g, "actual_Q", "pred_Q")

    for year, g in labeled.groupby("year", sort=True):
        print(f"S1 L2ROLL YEAR year={year} n={len(g)} high={int((g.actual_state=='high').sum())} neutral={int((g.actual_state=='neutral').sum())} low={int((g.actual_state=='low').sum())}")
        _stats(f"S1 L2ROLL YEARSTAT year={year} metric=C", g, "actual_C", "pred_C")
        _stats(f"S1 L2ROLL YEARSTAT year={year} metric=Q", g, "actual_Q", "pred_Q")
        for state in ("high", "neutral", "low"):
            gs = g.loc[g.actual_state == state]
            _stats(f"S1 L2ROLL YEARSTATE year={year} state={state} metric=C", gs, "actual_C", "pred_C")
            _stats(f"S1 L2ROLL YEARSTATE year={year} state={state} metric=Q", gs, "actual_Q", "pred_Q")

    print(f"S1 L2ROLL OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 L2ROLL COMPLETE")


if __name__ == "__main__":
    main()

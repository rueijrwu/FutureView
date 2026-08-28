from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table
from .strategy1_cq_90d_rank_audit import build_window_q
from .strategy1_layer1_forward_w_audit import _classify
from .strategy1_layer2_forward_dataset import build_forward_dataset
from .strategy1_layer2_forward_smoke import (
    ForwardCQStateNet,
    STATE_TO_ID,
    build_training_data,
    decode_cq,
    nonnegative_q,
    weighted_mean,
)

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
MODEL_HISTORY = int(os.environ.get("FUTUREVIEW_MODEL_HISTORY", "90"))
TRAIN_YEARS = int(os.environ.get("FUTUREVIEW_TRAIN_YEARS", "5"))
VALIDATION_YEARS = int(os.environ.get("FUTUREVIEW_VALIDATION_YEARS", "3"))
LABEL_LAG = int(os.environ.get("FUTUREVIEW_LABEL_LAG", "60"))
NEUTRAL_ALPHA = float(os.environ.get("FUTUREVIEW_NEUTRAL_ALPHA", "0.2"))
EPOCHS = int(os.environ.get("FUTUREVIEW_EPOCHS", "100"))
LR = float(os.environ.get("FUTUREVIEW_LR", "0.003"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260828"))
MAX_WORKERS = int(os.environ.get("FUTUREVIEW_MAX_WORKERS", "4"))
OUTPUT = os.environ.get("FUTUREVIEW_ROLLING_OUTPUT", "strategy1-layer2-8y-rolling5y-validation.csv")


def rolling_train_mask(
    target_start_dates: pd.DatetimeIndex,
    label_available_index: np.ndarray,
    current_target_index: int,
    current_date: pd.Timestamp,
    train_years: int,
) -> np.ndarray:
    lower = current_date - pd.DateOffset(years=train_years)
    return (
        (target_start_dates >= lower)
        & (target_start_dates < current_date)
        & (label_available_index < current_target_index)
    )


def _corr(actual: np.ndarray, pred: np.ndarray) -> tuple[float, float]:
    if len(actual) < 2 or np.std(actual) == 0 or np.std(pred) == 0:
        return float("nan"), float("nan")
    return (
        float(np.corrcoef(actual, pred)[0, 1]),
        float(pd.Series(actual).corr(pd.Series(pred), method="spearman")),
    )


def _stats(prefix: str, actual: np.ndarray, pred: np.ndarray) -> None:
    if len(actual) == 0:
        print(f"{prefix} n=0")
        return
    diff = pred - actual
    ae = np.abs(diff)
    pearson, spearman = _corr(actual, pred)
    print(
        f"{prefix} n={len(actual)} actual_mean={actual.mean():.6f} pred_mean={pred.mean():.6f} "
        f"bias={diff.mean():.6f} mae={ae.mean():.6f} medae={np.median(ae):.6f} "
        f"p75ae={np.quantile(ae,0.75):.6f} p90ae={np.quantile(ae,0.90):.6f} "
        f"pearson={pearson:.6f} spearman={spearman:.6f}"
    )


def train_one(
    all_data,
    train_mask: np.ndarray,
    test_i: int,
    base_state: dict[str, torch.Tensor],
) -> tuple[np.ndarray, np.ndarray]:
    idx = np.flatnonzero(train_mask)
    if len(idx) == 0:
        raise RuntimeError("empty rolling training set")

    x = all_data.x[idx]
    y_cq = all_data.y_cq[idx]
    y_state = all_data.y_state[idx]
    weight = all_data.weight[idx]

    c_mu = y_cq[:, 0:1].mean(dim=0, keepdim=True)
    c_sd = y_cq[:, 0:1].std(dim=0, keepdim=True, unbiased=False)
    c_sd = torch.where(c_sd < 1e-6, torch.ones_like(c_sd), c_sd)
    q_scale = y_cq[:, 1:2].std(dim=0, keepdim=True, unbiased=False)
    q_scale = torch.where(q_scale < 1e-6, torch.ones_like(q_scale), q_scale)
    target_c_z = (y_cq[:, 0:1] - c_mu) / c_sd
    target_q_scaled = y_cq[:, 1:2] / q_scale

    # Every day is a fresh model. All daily models start from the same locked
    # initialization so parallel execution does not share learned weights.
    model = ForwardCQStateNet()
    model.load_state_dict(base_state)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    reg_fn = nn.SmoothL1Loss(reduction="none")
    cls_fn = nn.CrossEntropyLoss(reduction="none")

    for _ in range(EPOCHS):
        raw, logits = model(x)
        reg_c = reg_fn(raw[:, 0:1], target_c_z).squeeze(1)
        reg_q = reg_fn(nonnegative_q(raw[:, 1:2]), target_q_scaled).squeeze(1)
        cls_each = cls_fn(logits, y_state)
        loss = weighted_mean(0.5 * (reg_c + reg_q) + cls_each, weight)
        opt.zero_grad()
        loss.backward()
        opt.step()

    model.eval()
    with torch.no_grad():
        raw, logits = model(all_data.x[test_i : test_i + 1])
        pred_cq = decode_cq(raw, c_mu, c_sd, q_scale)[0].numpy()
        probs = torch.softmax(logits, dim=1)[0].numpy()
    return pred_cq, probs


def main() -> None:
    if DATA_PERIOD != "8y" or W != 30 or MODEL_HISTORY != 90:
        raise ValueError("rolling validation locked to 8y data, W=30, model_history=90")
    if TRAIN_YEARS != 5 or VALIDATION_YEARS != 3 or LABEL_LAG != 60:
        raise ValueError("rolling validation locked to train=5y, validation=3y, label_lag=60")
    if abs(NEUTRAL_ALPHA - 0.2) > 1e-12:
        raise ValueError("rolling validation locked to neutral alpha=0.2")
    if MAX_WORKERS < 1:
        raise ValueError("max_workers must be >= 1")

    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.set_num_threads(1)

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1800)
    df = df.reset_index(drop=True)
    dates = pd.to_datetime(df["date"]).dt.normalize()
    final_date = pd.Timestamp(dates.iloc[-1])
    validation_start = final_date - pd.DateOffset(years=VALIDATION_YEARS)

    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(df, paths, window=W, stride=1, random_samples=20, random_seed=SEED)
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)
    classified = _classify(wq).sort_values("start_index").reset_index(drop=True)
    forward = build_forward_dataset(classified, len(df), MODEL_HISTORY).reset_index(drop=True)
    all_data = build_training_data(df, forward)

    start_idx = forward.target_start.to_numpy(dtype=int)
    end_idx = forward.target_end.to_numpy(dtype=int)
    start_dates = pd.DatetimeIndex(pd.to_datetime(df.iloc[start_idx]["date"].to_numpy()).normalize())
    label_available = end_idx + LABEL_LAG

    # Validation labels themselves must also be fully realizable in the downloaded data.
    validation_mask = (start_dates >= validation_start) & (label_available < len(df))
    validation_indices = np.flatnonzero(validation_mask)
    if len(validation_indices) == 0:
        raise RuntimeError("no validation samples")

    tasks: list[tuple[int, pd.Timestamp, int, np.ndarray, int]] = []
    skipped_empty = 0
    train_sizes: list[int] = []
    for i in validation_indices:
        current_date = pd.Timestamp(start_dates[i])
        current_target_index = int(start_idx[i])
        train_mask = rolling_train_mask(
            start_dates,
            label_available,
            current_target_index,
            current_date,
            TRAIN_YEARS,
        )
        n_train = int(train_mask.sum())
        if n_train == 0:
            skipped_empty += 1
            continue
        train_sizes.append(n_train)
        tasks.append((int(i), current_date, current_target_index, train_mask, n_train))

    if not tasks:
        raise RuntimeError("all rolling validation samples skipped")

    torch.manual_seed(SEED)
    base_model = ForwardCQStateNet()
    base_state = {k: v.detach().clone() for k, v in base_model.state_dict().items()}

    def run_task(task):
        i, current_date, current_target_index, train_mask, n_train = task
        pred, probs = train_one(all_data, train_mask, i, base_state)
        return i, current_date, current_target_index, n_train, pred, probs

    rows_out: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for done, result in enumerate(executor.map(run_task, tasks), start=1):
            i, current_date, current_target_index, n_train, pred, probs = result
            actual_c = float(all_data.y_cq[i, 0])
            actual_q = float(all_data.y_cq[i, 1])
            state = str(forward.iloc[i].state)
            rows_out.append({
                "target_start_date": current_date.date().isoformat(),
                "target_end_date": pd.Timestamp(df.iloc[int(end_idx[i])]["date"]).date().isoformat(),
                "calendar_year": int(current_date.year),
                "rolling_train_start": (current_date - pd.DateOffset(years=TRAIN_YEARS)).date().isoformat(),
                "rolling_train_end": pd.Timestamp(df.iloc[current_target_index - 1]["date"]).date().isoformat(),
                "rolling_train_samples": n_train,
                "actual_state": state,
                "sample_weight": 1.0 if state in ("high", "low") else NEUTRAL_ALPHA,
                "actual_C": actual_c,
                "pred_C": float(pred[0]),
                "diff_C": float(pred[0] - actual_c),
                "abs_error_C": float(abs(pred[0] - actual_c)),
                "actual_Q": actual_q,
                "pred_Q": float(pred[1]),
                "diff_Q": float(pred[1] - actual_q),
                "abs_error_Q": float(abs(pred[1] - actual_q)),
                "P_H": float(probs[STATE_TO_ID["high"]]),
                "P_N": float(probs[STATE_TO_ID["neutral"]]),
                "P_L": float(probs[STATE_TO_ID["low"]]),
            })
            if done % 50 == 0:
                print(f"S1 L2ROLL PROGRESS done={done} total={len(tasks)}")

    out = pd.DataFrame(rows_out).sort_values("target_start_date").reset_index(drop=True)
    out.to_csv(OUTPUT, index=False)

    print(
        f"S1 L2ROLL START ticker={TICKER} rows={audit.rows} W={W} history={MODEL_HISTORY} "
        f"train_years={TRAIN_YEARS} validation_years={VALIDATION_YEARS} label_lag={LABEL_LAG} "
        f"classified={len(classified)} forward={len(forward)} validation_candidates={len(validation_indices)} "
        f"validation_used={len(out)} skipped_empty={skipped_empty} alpha={NEUTRAL_ALPHA:.3f} "
        f"epochs={EPOCHS} workers={MAX_WORKERS}"
    )
    print(
        f"S1 L2ROLL RANGE final_date={final_date.date().isoformat()} validation_start={validation_start.date().isoformat()} "
        f"validation_actual={out.target_start_date.iloc[0]}..{out.target_end_date.iloc[-1]} "
        f"train_samples_min={min(train_sizes)} train_samples_median={int(np.median(train_sizes))} train_samples_max={max(train_sizes)}"
    )

    actual_c = out.actual_C.to_numpy(float)
    pred_c = out.pred_C.to_numpy(float)
    actual_q = out.actual_Q.to_numpy(float)
    pred_q = out.pred_Q.to_numpy(float)
    _stats("S1 L2ROLL OVERALL metric=C", actual_c, pred_c)
    _stats("S1 L2ROLL OVERALL metric=Q", actual_q, pred_q)

    for state in ("high", "neutral", "low"):
        g = out.loc[out.actual_state == state]
        print(f"S1 L2ROLL STATECOUNT state={state} n={len(g)}")
        _stats(f"S1 L2ROLL STATE state={state} metric=C", g.actual_C.to_numpy(float), g.pred_C.to_numpy(float))
        _stats(f"S1 L2ROLL STATE state={state} metric=Q", g.actual_Q.to_numpy(float), g.pred_Q.to_numpy(float))

    for year, gy in out.groupby("calendar_year", sort=True):
        print(f"S1 L2ROLL YEARCOUNT year={year} n={len(gy)} high={int((gy.actual_state=='high').sum())} neutral={int((gy.actual_state=='neutral').sum())} low={int((gy.actual_state=='low').sum())}")
        _stats(f"S1 L2ROLL YEAR year={year} metric=C", gy.actual_C.to_numpy(float), gy.pred_C.to_numpy(float))
        _stats(f"S1 L2ROLL YEAR year={year} metric=Q", gy.actual_Q.to_numpy(float), gy.pred_Q.to_numpy(float))
        for state in ("high", "neutral", "low"):
            gs = gy.loc[gy.actual_state == state]
            if len(gs) == 0:
                continue
            _stats(f"S1 L2ROLL YEARSTATE year={year} state={state} metric=C", gs.actual_C.to_numpy(float), gs.pred_C.to_numpy(float))
            _stats(f"S1 L2ROLL YEARSTATE year={year} state={state} metric=Q", gs.actual_Q.to_numpy(float), gs.pred_Q.to_numpy(float))

    print(
        f"S1 L2ROLL QSANITY actual_zero={int(np.isclose(actual_q,0.0,atol=1e-8).sum())} "
        f"pred_zero={int(np.isclose(pred_q,0.0,atol=1e-8).sum())} pred_negative={int((pred_q<0).sum())} pred_min={pred_q.min():.8f}"
    )
    print(f"S1 L2ROLL OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 L2ROLL COMPLETE")


if __name__ == "__main__":
    main()

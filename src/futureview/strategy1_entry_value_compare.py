from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_spy_daily
from .models import TrendCNNJoint, TrendCNNDual, count_parameters
from .strategy1_entry_targets import EntryEventDataset, make_entry_event_dataset
from .strategy1_summary_baseline import _fit_ridge, _summary_features
from .strategy1_summary_fusion import TrendCNNJointSummary20, _standardize_summary

DATA_PERIOD = "15y"
LOOKBACK = 50
TARGET_HORIZON = 30
SEEDS = (20260821, 20260822, 20260823, 20260824, 20260825)
EPOCHS = 20
LEARNING_RATE = 3e-3
HUBER_DELTA = 0.01
TOP_FRACTION = 0.20
PURGE_RAW_SESSIONS = 60
MIN_TRAIN_EVENTS = 40
SLIDING_TRAIN_EVENTS = 40
TEST_EVENTS = 10
MAX_FOLDS = 4


@dataclass(frozen=True)
class EventFold:
    train: np.ndarray
    test: np.ndarray


def _event_folds(raw_indices: np.ndarray) -> tuple[EventFold, ...]:
    """Purged chronological event folds using raw-session distance, never random splits."""
    raw_indices = np.asarray(raw_indices, dtype=int)
    candidates: list[EventFold] = []
    for test_start in range(MIN_TRAIN_EVENTS, len(raw_indices), TEST_EVENTS):
        test = np.arange(test_start, min(test_start + TEST_EVENTS, len(raw_indices)), dtype=int)
        if len(test) != TEST_EVENTS:
            continue
        cutoff = int(raw_indices[test[0]]) - PURGE_RAW_SESSIONS - 1
        eligible = np.where(raw_indices[:test_start] <= cutoff)[0]
        if len(eligible) < SLIDING_TRAIN_EVENTS:
            continue
        train = eligible[-SLIDING_TRAIN_EVENTS:]
        candidates.append(EventFold(train=train, test=test))
    if not candidates:
        raise RuntimeError("no complete purged chronological entry-event folds")
    return tuple(candidates[-MAX_FOLDS:])


def _rankdata(values: np.ndarray) -> np.ndarray:
    return pd.Series(values).rank(method="average").to_numpy(dtype=float)


def _spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) < 2 or np.std(y_pred) < 1e-12:
        return float("nan")
    a = _rankdata(y_true)
    b = _rankdata(y_pred)
    if np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    overall = float(np.mean(y_true))
    mae = float(np.mean(np.abs(y_true - y_pred)))
    spearman = _spearman(y_true, y_pred)
    n_top = max(1, int(math.ceil(len(y_pred) * TOP_FRACTION)))
    order = np.argsort(y_pred, kind="stable")
    top = order[-n_top:]
    bottom = order[:n_top]
    return {
        "spearman": spearman,
        "mae": mae,
        "overall": overall,
        "top20": float(np.mean(y_true[top])),
        "top20_lift": float(np.mean(y_true[top]) - overall),
        "top_bottom": float(np.mean(y_true[top]) - np.mean(y_true[bottom])),
    }


def _benchmark_metrics(
    entry_return: np.ndarray,
    oracle: np.ndarray,
    prediction: np.ndarray,
) -> dict[str, float]:
    n_top = max(1, int(math.ceil(len(prediction) * TOP_FRACTION)))
    top = np.argsort(prediction, kind="stable")[-n_top:]
    e = entry_return[top]
    o = oracle[top]
    regret = o - e
    valid = o > 1e-12
    capture = e[valid] / o[valid] if np.any(valid) else np.asarray([], dtype=float)
    return {
        "top_entry_mean": float(np.mean(e)),
        "top_oracle_mean": float(np.mean(o)),
        "top_regret_mean": float(np.mean(regret)),
        "top_win_rate": float(np.mean(e > 0.0)),
        "top_capture_mean": float(np.mean(capture)) if len(capture) else float("nan"),
        "top_capture80_rate": float(np.mean(capture >= 0.80)) if len(capture) else float("nan"),
    }


def _fit_cnn_scalar(
    model_cls,
    x_train: torch.Tensor,
    y_train: np.ndarray,
    x_test: torch.Tensor,
    *,
    seed: int,
) -> np.ndarray:
    torch.manual_seed(seed)
    model = model_cls().cpu()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    loss_fn = nn.HuberLoss(delta=HUBER_DELTA)
    target = torch.from_numpy(np.asarray(y_train, dtype=np.float32))
    model.train()
    for _ in range(EPOCHS):
        optimizer.zero_grad(set_to_none=True)
        pred = model(x_train)[:, 1]
        loss = loss_fn(pred, target)
        loss.backward()
        optimizer.step()
    model.eval()
    with torch.no_grad():
        return model(x_test)[:, 1].cpu().numpy().astype(float)


def _fit_fusion_scalar(
    x_train: torch.Tensor,
    y_train: np.ndarray,
    summary_train_np: np.ndarray,
    x_test: torch.Tensor,
    summary_test_np: np.ndarray,
    *,
    seed: int,
) -> np.ndarray:
    z_train, z_test = _standardize_summary(summary_train_np, summary_test_np)
    torch.manual_seed(seed)
    model = TrendCNNJointSummary20().cpu()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    loss_fn = nn.HuberLoss(delta=HUBER_DELTA)
    target = torch.from_numpy(np.asarray(y_train, dtype=np.float32))
    model.train()
    for _ in range(EPOCHS):
        optimizer.zero_grad(set_to_none=True)
        pred = model(x_train, z_train)[:, 1]
        loss = loss_fn(pred, target)
        loss.backward()
        optimizer.step()
    model.eval()
    with torch.no_grad():
        return model(x_test, z_test)[:, 1].cpu().numpy().astype(float)


def _fmt(x: float) -> str:
    return "nan" if not np.isfinite(x) else f"{x:.6f}"


def _summarize(rows: list[dict[str, float]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in ("spearman", "mae", "top20_lift", "top_bottom"):
        vals = np.asarray([r[key] for r in rows], dtype=float)
        valid = vals[np.isfinite(vals)]
        out[f"{key}_mean"] = float(valid.mean()) if len(valid) else float("nan")
        out[f"{key}_std"] = float(valid.std(ddof=0)) if len(valid) else float("nan")
        out[f"{key}_positive"] = float(np.sum(valid > 0.0))
        out[f"{key}_valid"] = float(len(valid))
    return out


def _dataset_baseline(ds: EntryEventDataset) -> None:
    valid_capture = np.isfinite(ds.capture_ratio)
    print(
        f"S1 ENTRY_VALUE BASELINE samples={len(ds.entry_return)} "
        f"entry_mean={ds.entry_return.mean():.6f} entry_median={np.median(ds.entry_return):.6f} "
        f"entry_win_rate={np.mean(ds.entry_return > 0.0):.3f} "
        f"oracle_mean={ds.oracle_benchmark.mean():.6f} regret_mean={ds.regret.mean():.6f} "
        f"capture_valid={int(valid_capture.sum())}/{len(ds.entry_return)} "
        f"capture_mean={_fmt(float(np.mean(ds.capture_ratio[valid_capture])) if valid_capture.any() else float('nan'))} "
        f"capture80_rate={_fmt(float(np.mean(ds.capture_ratio[valid_capture] >= 0.80)) if valid_capture.any() else float('nan'))}"
    )


def main() -> None:
    torch.set_num_threads(2)
    df = download_spy_daily(period=DATA_PERIOD)
    ds = make_entry_event_dataset(df, lookback=LOOKBACK, horizon=TARGET_HORIZON)
    folds = _event_folds(ds.raw_indices)
    summary_x = _summary_features(ds.x)

    print(
        f"S1 ENTRY_VALUE DATA period={DATA_PERIOD} samples={len(ds.entry_return)} folds={len(folds)} "
        f"lookback={LOOKBACK} horizon={TARGET_HORIZON} train_events={SLIDING_TRAIN_EVENTS} "
        f"test_events={TEST_EVENTS} purge_raw_sessions={PURGE_RAW_SESSIONS} "
        f"first={ds.dates[0].date()} last={ds.dates[-1].date()} "
        f"seeds={','.join(map(str, SEEDS))} no_random_split=true"
    )
    print(
        "S1 ENTRY_VALUE RULE learning_target=this_entry_realized_return "
        "oracle_role=benchmark_only oracle_future_known_best_legal_solution=true "
        "sample_condition=legal_entry1_event input_ends_on_entry_close=true"
    )
    print(
        f"S1 ENTRY_VALUE MODEL name=CNN_A params={count_parameters(TrendCNNJoint())}"
    )
    print(
        f"S1 ENTRY_VALUE MODEL name=CNN_B params={count_parameters(TrendCNNDual())}"
    )
    print(
        f"S1 ENTRY_VALUE MODEL name=CNN_A_PLUS_SUMMARY20 params={count_parameters(TrendCNNJointSummary20())}"
    )
    _dataset_baseline(ds)

    model_rows: dict[str, dict[int, list[dict[str, float]]]] = {
        "CNN_A": {s: [] for s in SEEDS},
        "CNN_B": {s: [] for s in SEEDS},
        "CNN_A_PLUS_SUMMARY20": {s: [] for s in SEEDS},
    }
    ridge_rows: list[dict[str, float]] = []
    constant_rows: list[dict[str, float]] = []

    for fold_id, fold in enumerate(folds, start=1):
        train, test = fold.train, fold.test
        y_train = ds.entry_return[train]
        y_test = ds.entry_return[test]
        oracle_test = ds.oracle_benchmark[test]
        print(
            f"S1 ENTRY_VALUE FOLD id={fold_id} n_train={len(train)} n_test={len(test)} "
            f"train_first={ds.dates[train[0]].date()} train_last={ds.dates[train[-1]].date()} "
            f"test_first={ds.dates[test[0]].date()} test_last={ds.dates[test[-1]].date()} "
            f"raw_session_gap={int(ds.raw_indices[test[0]] - ds.raw_indices[train[-1]] - 1)}"
        )

        constant = np.full(len(test), float(np.mean(y_train)), dtype=float)
        cm = _metrics(y_test, constant)
        constant_rows.append(cm)
        print(
            f"S1 ENTRY_VALUE FOLD_METRIC id={fold_id} model=CONSTANT spearman={_fmt(cm['spearman'])} "
            f"mae={cm['mae']:.6f} top20_lift={cm['top20_lift']:.6f}"
        )

        ridge = _fit_ridge(summary_x[train], y_train, summary_x[test])
        rm = _metrics(y_test, ridge)
        rb = _benchmark_metrics(y_test, oracle_test, ridge)
        ridge_rows.append(rm)
        print(
            f"S1 ENTRY_VALUE FOLD_METRIC id={fold_id} model=SUMMARY_RIDGE "
            f"spearman={_fmt(rm['spearman'])} mae={rm['mae']:.6f} "
            f"top20_lift={rm['top20_lift']:.6f} top_regret={rb['top_regret_mean']:.6f} "
            f"top_capture={_fmt(rb['top_capture_mean'])} top_capture80_rate={_fmt(rb['top_capture80_rate'])}"
        )

        x_train = ds.x[train].cpu()
        x_test = ds.x[test].cpu()
        for seed in SEEDS:
            predictions = {
                "CNN_A": _fit_cnn_scalar(TrendCNNJoint, x_train, y_train, x_test, seed=seed),
                "CNN_B": _fit_cnn_scalar(TrendCNNDual, x_train, y_train, x_test, seed=seed),
                "CNN_A_PLUS_SUMMARY20": _fit_fusion_scalar(
                    x_train,
                    y_train,
                    summary_x[train],
                    x_test,
                    summary_x[test],
                    seed=seed,
                ),
            }
            for name, pred in predictions.items():
                m = _metrics(y_test, pred)
                b = _benchmark_metrics(y_test, oracle_test, pred)
                model_rows[name][seed].append(m)
                print(
                    f"S1 ENTRY_VALUE FOLD_METRIC id={fold_id} model={name} seed={seed} "
                    f"spearman={_fmt(m['spearman'])} mae={m['mae']:.6f} "
                    f"top20_lift={m['top20_lift']:.6f} top_bottom={m['top_bottom']:.6f} "
                    f"top_entry={b['top_entry_mean']:.6f} top_oracle={b['top_oracle_mean']:.6f} "
                    f"top_regret={b['top_regret_mean']:.6f} top_win_rate={b['top_win_rate']:.3f} "
                    f"top_capture={_fmt(b['top_capture_mean'])} top_capture80_rate={_fmt(b['top_capture80_rate'])}"
                )

    rs = _summarize(ridge_rows)
    cs = _summarize(constant_rows)
    print(
        f"S1 ENTRY_VALUE SUMMARY model=SUMMARY_RIDGE spearman={_fmt(rs['spearman_mean'])} "
        f"top20_lift={_fmt(rs['top20_lift_mean'])} mae={rs['mae_mean']:.6f}"
    )
    print(
        f"S1 ENTRY_VALUE SUMMARY model=CONSTANT mae={cs['mae_mean']:.6f}"
    )

    for name in model_rows:
        seed_summaries: list[dict[str, float]] = []
        for seed in SEEDS:
            s = _summarize(model_rows[name][seed])
            seed_summaries.append(s)
            print(
                f"S1 ENTRY_VALUE SEED_SUMMARY model={name} seed={seed} folds={len(folds)} "
                f"spearman={_fmt(s['spearman_mean'])} "
                f"spearman_positive={int(s['spearman_positive'])}/{int(s['spearman_valid'])} "
                f"top20_lift={_fmt(s['top20_lift_mean'])} mae={s['mae_mean']:.6f}"
            )
        for metric in ("spearman_mean", "top20_lift_mean", "mae_mean"):
            vals = np.asarray([s[metric] for s in seed_summaries], dtype=float)
            valid = vals[np.isfinite(vals)]
            print(
                f"S1 ENTRY_VALUE CROSS_SEED model={name} metric={metric.replace('_mean','')} "
                f"mean={_fmt(float(valid.mean()) if len(valid) else float('nan'))} "
                f"std={_fmt(float(valid.std(ddof=0)) if len(valid) else float('nan'))} "
                f"positive={int(np.sum(valid > 0.0))}/{len(valid)}"
            )

    print("S1 ENTRY_VALUE PASS")


if __name__ == "__main__":
    main()

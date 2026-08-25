from __future__ import annotations

import math

import numpy as np
import torch

from .data import download_spy_daily
from .models import TrendCNNJoint, TrendCNNDual
from .strategy1_entry_targets import make_entry_event_dataset
from .strategy1_entry_value_compare import (
    EPOCHS,
    HUBER_DELTA,
    LEARNING_RATE,
    LOOKBACK,
    SEEDS,
    TARGET_HORIZON,
    TOP_FRACTION,
    _event_folds,
    _fit_cnn_scalar,
    _fit_fusion_scalar,
    _fmt,
    _metrics,
    _spearman,
)
from .strategy1_summary_baseline import _fit_ridge, _summary_features

DATA_PERIOD = "5y"
MATCH_EPSILON = 1e-12


def _regret_metrics(entry_return: np.ndarray, oracle: np.ndarray, prediction: np.ndarray) -> dict[str, float]:
    entry_return = np.asarray(entry_return, dtype=float)
    oracle = np.asarray(oracle, dtype=float)
    prediction = np.asarray(prediction, dtype=float)
    regret = oracle - entry_return
    if (regret < -1e-10).any():
        raise RuntimeError("negative Oracle regret detected")

    n_top = max(1, int(math.ceil(len(prediction) * TOP_FRACTION)))
    top = np.argsort(prediction, kind="stable")[-n_top:]
    top_regret = regret[top]
    overall_regret = float(np.mean(regret))
    top_regret_mean = float(np.mean(top_regret))
    return {
        "overall_regret_mean": overall_regret,
        "top_regret_mean": top_regret_mean,
        "regret_reduction_vs_all": overall_regret - top_regret_mean,
        "top_oracle_match_rate": float(np.mean(top_regret <= MATCH_EPSILON)),
        "top_entry_mean": float(np.mean(entry_return[top])),
        "top_oracle_mean": float(np.mean(oracle[top])),
        "top_win_rate": float(np.mean(entry_return[top] > 0.0)),
        "regret_spearman": _spearman(regret, -prediction),
    }


def _mean_std(values: list[float]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if not len(arr):
        return float("nan"), float("nan")
    return float(arr.mean()), float(arr.std(ddof=0))


def main() -> None:
    torch.set_num_threads(2)
    df = download_spy_daily(period=DATA_PERIOD)
    ds = make_entry_event_dataset(df, lookback=LOOKBACK, horizon=TARGET_HORIZON)
    folds = _event_folds(ds.raw_indices)
    summary_x = _summary_features(ds.x)

    print(
        f"S1 ENTRY_REGRET DATA period={DATA_PERIOD} samples={len(ds.entry_return)} folds={len(folds)} "
        f"lookback={LOOKBACK} horizon={TARGET_HORIZON} seeds={','.join(map(str, SEEDS))} no_random_split=true"
    )
    print(
        "S1 ENTRY_REGRET RULE learning_target=this_entry_realized_return "
        "oracle_role=benchmark_only regret=oracle_value_minus_entry_return "
        "primary_benchmark=top_regret_mean,regret_reduction_vs_all,top_oracle_match_rate "
        "capture_ratio_not_primary=true"
    )

    names = ("SUMMARY_RIDGE", "CNN_A", "CNN_B", "CNN_A_PLUS_SUMMARY20")
    rows: dict[str, list[dict[str, float]]] = {name: [] for name in names}

    for fold_id, fold in enumerate(folds, start=1):
        train, test = fold.train, fold.test
        y_train = ds.entry_return[train]
        y_test = ds.entry_return[test]
        oracle_test = ds.oracle_benchmark[test]
        print(
            f"S1 ENTRY_REGRET FOLD id={fold_id} n_train={len(train)} n_test={len(test)} "
            f"train_first={ds.dates[train[0]].date()} train_last={ds.dates[train[-1]].date()} "
            f"test_first={ds.dates[test[0]].date()} test_last={ds.dates[test[-1]].date()} "
            f"raw_session_gap={int(ds.raw_indices[test[0]] - ds.raw_indices[train[-1]] - 1)}"
        )

        ridge_pred = _fit_ridge(summary_x[train], y_train, summary_x[test])
        ridge_entry = _metrics(y_test, ridge_pred)
        ridge_regret = _regret_metrics(y_test, oracle_test, ridge_pred)
        ridge_row = {**ridge_entry, **ridge_regret}
        rows["SUMMARY_RIDGE"].append(ridge_row)
        print(
            f"S1 ENTRY_REGRET FOLD_METRIC id={fold_id} model=SUMMARY_RIDGE "
            f"entry_spearman={_fmt(ridge_entry['spearman'])} top20_lift={ridge_entry['top20_lift']:.6f} "
            f"overall_regret={ridge_regret['overall_regret_mean']:.6f} "
            f"top_regret={ridge_regret['top_regret_mean']:.6f} "
            f"regret_reduction={ridge_regret['regret_reduction_vs_all']:.6f} "
            f"oracle_match_rate={ridge_regret['top_oracle_match_rate']:.3f} "
            f"top_entry={ridge_regret['top_entry_mean']:.6f} top_oracle={ridge_regret['top_oracle_mean']:.6f}"
        )

        x_train = ds.x[train].cpu()
        x_test = ds.x[test].cpu()
        seed_rows: dict[str, list[dict[str, float]]] = {
            "CNN_A": [], "CNN_B": [], "CNN_A_PLUS_SUMMARY20": []
        }
        for seed in SEEDS:
            preds = {
                "CNN_A": _fit_cnn_scalar(TrendCNNJoint, x_train, y_train, x_test, seed=seed),
                "CNN_B": _fit_cnn_scalar(TrendCNNDual, x_train, y_train, x_test, seed=seed),
                "CNN_A_PLUS_SUMMARY20": _fit_fusion_scalar(
                    x_train, y_train, summary_x[train], x_test, summary_x[test], seed=seed
                ),
            }
            for name, pred in preds.items():
                entry_m = _metrics(y_test, pred)
                regret_m = _regret_metrics(y_test, oracle_test, pred)
                row = {**entry_m, **regret_m}
                seed_rows[name].append(row)
                print(
                    f"S1 ENTRY_REGRET FOLD_METRIC id={fold_id} model={name} seed={seed} "
                    f"entry_spearman={_fmt(entry_m['spearman'])} top20_lift={entry_m['top20_lift']:.6f} "
                    f"overall_regret={regret_m['overall_regret_mean']:.6f} "
                    f"top_regret={regret_m['top_regret_mean']:.6f} "
                    f"regret_reduction={regret_m['regret_reduction_vs_all']:.6f} "
                    f"oracle_match_rate={regret_m['top_oracle_match_rate']:.3f} "
                    f"top_win_rate={regret_m['top_win_rate']:.3f}"
                )

        for name, per_seed in seed_rows.items():
            for row in per_seed:
                rows[name].append(row)

    for name in names:
        model_rows = rows[name]
        if name == "SUMMARY_RIDGE":
            fold_groups = [[row] for row in model_rows]
        else:
            fold_groups = [model_rows[i:i + len(SEEDS)] for i in range(0, len(model_rows), len(SEEDS))]

        fold_top_regret = [float(np.mean([r['top_regret_mean'] for r in g])) for g in fold_groups]
        fold_reduction = [float(np.mean([r['regret_reduction_vs_all'] for r in g])) for g in fold_groups]
        fold_match = [float(np.mean([r['top_oracle_match_rate'] for r in g])) for g in fold_groups]
        fold_lift = [float(np.mean([r['top20_lift'] for r in g])) for g in fold_groups]
        fold_spearman = [float(np.nanmean([r['spearman'] for r in g])) for g in fold_groups]

        tr_mean, tr_std = _mean_std(fold_top_regret)
        rr_mean, rr_std = _mean_std(fold_reduction)
        om_mean, om_std = _mean_std(fold_match)
        lift_mean, lift_std = _mean_std(fold_lift)
        sp_mean, sp_std = _mean_std(fold_spearman)
        print(
            f"S1 ENTRY_REGRET SUMMARY model={name} folds={len(fold_groups)} "
            f"entry_spearman_mean={_fmt(sp_mean)} entry_spearman_std={_fmt(sp_std)} "
            f"top20_lift_mean={_fmt(lift_mean)} top20_lift_std={_fmt(lift_std)} "
            f"top_regret_mean={_fmt(tr_mean)} top_regret_std={_fmt(tr_std)} "
            f"regret_reduction_mean={_fmt(rr_mean)} regret_reduction_std={_fmt(rr_std)} "
            f"oracle_match_rate_mean={_fmt(om_mean)} oracle_match_rate_std={_fmt(om_std)}"
        )

    print("S1 ENTRY_REGRET PASS")


if __name__ == "__main__":
    main()

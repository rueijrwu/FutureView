from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1_success_live_campaign_expanded_oos import _expanded_event_folds
from .strategy1_success_training import (
    DATA_PERIOD,
    HORIZON,
    LOOKBACK,
    PURGE_RAW_SESSIONS,
    REFERENCE_LOOKBACK,
    SEEDS,
    TICKER,
    _fit,
    _spearman,
    make_success_dataset,
)

N_BUCKETS = 5


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


def _rank_buckets(score: np.ndarray, n_buckets: int = N_BUCKETS) -> np.ndarray:
    score = np.asarray(score, dtype=float)
    order = np.argsort(score, kind="stable")
    buckets = np.empty(len(score), dtype=int)
    # Equal-count rank buckets. Diagnostic only; never used as a live gate.
    for rank, idx in enumerate(order):
        buckets[idx] = min(n_buckets - 1, (rank * n_buckets) // len(score))
    return buckets


def main() -> None:
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    ds = make_success_dataset(df)
    folds = _expanded_event_folds(ds.raw_indices)

    print(
        "S1 MODEL_DIAGNOSTICS DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"samples={len(ds.success_probability)} folds={len(folds)} lookback={LOOKBACK} horizon={HORIZON} "
        f"reference_lookback={REFERENCE_LOOKBACK} purge_raw_sessions={PURGE_RAW_SESSIONS} "
        f"seeds={','.join(map(str, SEEDS))} buckets={N_BUCKETS} no_random_split=true"
    )
    print(
        "S1 MODEL_DIAGNOSTICS RULE "
        "purpose=model_score_quality_not_trade_frequency threshold_used=false gate_used=false "
        "bucket_definition=within_fold_equal_count_rank_quintiles future_labels_not_features=true "
        "primary_target=entry_success_probability deterministic_return=evaluation_only"
    )

    pooled_bucket_rows: dict[int, list[tuple[float, float, float, float, float, float]]] = {
        b: [] for b in range(N_BUCKETS)
    }
    fold_spearman: list[float] = []
    fold_target_lift: list[float] = []
    fold_realized_lift: list[float] = []
    fold_net_lift: list[float] = []

    for fold_id, fold in enumerate(folds, start=1):
        y_train = ds.success_probability[fold.train]
        y_test = ds.success_probability[fold.test]
        net_test = ds.net_expected_return[fold.test]
        realized_test = ds.realized_return[fold.test]

        seed_pred = []
        for seed in SEEDS:
            seed_pred.append(_fit(ds.x[fold.train].cpu(), y_train, ds.x[fold.test].cpu(), seed=seed))
        pred_matrix = np.stack(seed_pred, axis=0)
        score = pred_matrix.mean(axis=0)
        disagreement = pred_matrix.std(axis=0)
        buckets = _rank_buckets(score)

        spearman = _spearman(y_test, score)
        fold_spearman.append(spearman)

        low = buckets == 0
        high = buckets == (N_BUCKETS - 1)
        target_lift = float(np.mean(y_test[high]) - np.mean(y_test[low]))
        realized_lift = float(np.mean(realized_test[high] > 0.0) - np.mean(realized_test[low] > 0.0))
        net_lift = float(np.mean(realized_test[high]) - np.mean(realized_test[low]))
        fold_target_lift.append(target_lift)
        fold_realized_lift.append(realized_lift)
        fold_net_lift.append(net_lift)

        print(
            f"S1 MODEL_DIAGNOSTICS FOLD id={fold_id} "
            f"test_first={pd.Timestamp(ds.dates[fold.test[0]]).date()} "
            f"test_last={pd.Timestamp(ds.dates[fold.test[-1]]).date()} test_n={len(fold.test)} "
            f"spearman={_fmt(spearman)} high_vs_low_target_lift={target_lift:.6f} "
            f"high_vs_low_realized_success_lift={realized_lift:.6f} "
            f"high_vs_low_realized_net_lift={net_lift:.6f}"
        )

        for bucket in range(N_BUCKETS):
            mask = buckets == bucket
            pred_mean = float(np.mean(score[mask]))
            target_mean = float(np.mean(y_test[mask]))
            realized_success = float(np.mean(realized_test[mask] > 0.0))
            target_net = float(np.mean(net_test[mask]))
            realized_net = float(np.mean(realized_test[mask]))
            disagreement_mean = float(np.mean(disagreement[mask]))
            pooled_bucket_rows[bucket].append(
                (pred_mean, target_mean, realized_success, target_net, realized_net, disagreement_mean)
            )
            print(
                f"S1 MODEL_DIAGNOSTICS BUCKET fold={fold_id} bucket={bucket + 1}/{N_BUCKETS} "
                f"n={int(np.sum(mask))} pred_mean={pred_mean:.6f} "
                f"target_success_mean={target_mean:.6f} realized_success={realized_success:.6f} "
                f"target_net_return={target_net:.6f} realized_net_return={realized_net:.6f} "
                f"seed_disagreement={disagreement_mean:.6f}"
            )

    pooled_target_by_bucket = []
    pooled_realized_success_by_bucket = []
    pooled_realized_net_by_bucket = []
    for bucket in range(N_BUCKETS):
        rows = np.asarray(pooled_bucket_rows[bucket], dtype=float)
        pred_mean = float(np.mean(rows[:, 0]))
        target_mean = float(np.mean(rows[:, 1]))
        realized_success = float(np.mean(rows[:, 2]))
        target_net = float(np.mean(rows[:, 3]))
        realized_net = float(np.mean(rows[:, 4]))
        disagreement = float(np.mean(rows[:, 5]))
        pooled_target_by_bucket.append(target_mean)
        pooled_realized_success_by_bucket.append(realized_success)
        pooled_realized_net_by_bucket.append(realized_net)
        print(
            f"S1 MODEL_DIAGNOSTICS POOLED_BUCKET bucket={bucket + 1}/{N_BUCKETS} "
            f"pred_mean={pred_mean:.6f} target_success_mean={target_mean:.6f} "
            f"realized_success={realized_success:.6f} target_net_return={target_net:.6f} "
            f"realized_net_return={realized_net:.6f} seed_disagreement={disagreement:.6f}"
        )

    target_monotone_steps = int(np.sum(np.diff(pooled_target_by_bucket) >= 0.0))
    realized_monotone_steps = int(np.sum(np.diff(pooled_realized_success_by_bucket) >= 0.0))
    net_monotone_steps = int(np.sum(np.diff(pooled_realized_net_by_bucket) >= 0.0))

    print(
        "S1 MODEL_DIAGNOSTICS SUMMARY "
        f"ticker={TICKER} folds={len(folds)} "
        f"spearman_mean={np.nanmean(fold_spearman):.6f} "
        f"spearman_positive={int(np.sum(np.asarray(fold_spearman) > 0.0))}/{len(fold_spearman)} "
        f"high_vs_low_target_lift_mean={np.mean(fold_target_lift):.6f} "
        f"high_vs_low_target_lift_positive={int(np.sum(np.asarray(fold_target_lift) > 0.0))}/{len(fold_target_lift)} "
        f"high_vs_low_realized_success_lift_mean={np.mean(fold_realized_lift):.6f} "
        f"high_vs_low_realized_success_lift_positive={int(np.sum(np.asarray(fold_realized_lift) > 0.0))}/{len(fold_realized_lift)} "
        f"high_vs_low_realized_net_lift_mean={np.mean(fold_net_lift):.6f} "
        f"high_vs_low_realized_net_lift_positive={int(np.sum(np.asarray(fold_net_lift) > 0.0))}/{len(fold_net_lift)} "
        f"pooled_target_monotone_steps={target_monotone_steps}/{N_BUCKETS - 1} "
        f"pooled_realized_success_monotone_steps={realized_monotone_steps}/{N_BUCKETS - 1} "
        f"pooled_realized_net_monotone_steps={net_monotone_steps}/{N_BUCKETS - 1}"
    )
    print("S1 MODEL_DIAGNOSTICS PASS")


if __name__ == "__main__":
    main()

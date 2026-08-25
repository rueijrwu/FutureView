from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd
import torch
from torch import nn

from . import strategy1_reference_distribution as base
from .data import download_ticker_daily, validate_daily_ohlcv
from .features import FEATURE_COLUMNS, make_causal_features
from .models import MultiScaleBlock, count_parameters
from .strategy1 import LOCAL_MAX_MIN_GAP, add_strategy1_events
from .strategy1_reference_distribution_fast import _simulate_path_fast

TICKER = "QQQ"
DATA_PERIOD = "5y"
LOOKBACK = 50
REFERENCE_LOOKBACK = 60
HORIZON = 60
ADDON2_SPACING_TOLERANCE = 0.20
SEEDS = (20260823, 20260824, 20260825)
EPOCHS = 30
LEARNING_RATE = 3e-3
PURGE_RAW_SESSIONS = 60
MIN_TRAIN_EVENTS = 160
TEST_EVENTS = 40
MAX_FOLDS = 4
TOP_FRACTION = 0.20


@dataclass(frozen=True)
class SuccessDataset:
    x: torch.Tensor
    success_probability: np.ndarray
    net_expected_return: np.ndarray
    entry_lower: np.ndarray
    entry_upper: np.ndarray
    path_count: np.ndarray
    realized_return: np.ndarray
    raw_indices: np.ndarray
    dates: np.ndarray


@dataclass(frozen=True)
class EventFold:
    train: np.ndarray
    test: np.ndarray


class EntrySuccessCNN(nn.Module):
    """Scalar probability model for one formal Entry candidate."""

    def __init__(self) -> None:
        super().__init__()
        self.multi = MultiScaleBlock(5, branch_channels=8)
        self.fusion = nn.Sequential(
            nn.Conv1d(self.multi.out_channels, 16, kernel_size=3, padding="same"),
            nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(16, 8),
            nn.GELU(),
            nn.Linear(8, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if x.ndim != 3 or x.shape[1] != 5:
            raise ValueError(f"expected [batch, 5, time], got {tuple(x.shape)}")
        return self.head(self.fusion(self.multi(x))).squeeze(1)


def _entry_target(entry: int, end: int) -> tuple[float, float, float, float, int]:
    history_start = max(0, entry - REFERENCE_LOOKBACK + 1)
    configs = base._addon_reference_sets(history_start, entry)
    by_path: dict[tuple[int, int, int, int, int, int], float] = {}
    for config in configs:
        level_indices = tuple(level[0] for level in config)
        ret, _, _, _, path = _simulate_path_fast(
            entry,
            end,
            level_indices,
            ADDON2_SPACING_TOLERANCE,
        )
        by_path.setdefault(path, float(ret))

    returns = np.asarray(list(by_path.values()), dtype=float)
    if len(returns) == 0:
        raise RuntimeError(f"entry {entry} produced no legal realized paths")
    return (
        float(np.mean(returns > 0.0)),
        float(np.mean(returns)),
        float(np.min(returns)),
        float(np.max(returns)),
        int(len(returns)),
    )


def _deterministic_addon_indices(entry: int) -> tuple[int, ...]:
    """Choose the actual Strategy 1 addon references using only information known at Entry."""
    history_start = max(0, entry - REFERENCE_LOOKBACK + 1)
    maxima = base._window_local_maxima(history_start, entry)
    if not maxima:
        return ()

    addon1 = int(maxima[-1])
    selected = [addon1]
    for candidate in reversed(maxima[:-1]):
        candidate = int(candidate)
        if addon1 - candidate > LOCAL_MAX_MIN_GAP:
            selected.append(candidate)
            break
    return tuple(selected)


def _actual_entry_return(entry: int, end: int) -> float:
    addon_indices = _deterministic_addon_indices(entry)
    ret, _, _, _, _ = _simulate_path_fast(
        entry,
        end,
        addon_indices,
        ADDON2_SPACING_TOLERANCE,
    )
    return float(ret)


def make_success_dataset(df: pd.DataFrame) -> SuccessDataset:
    events = add_strategy1_events(df).reset_index(drop=True)
    base._prepare_worker_state(events)
    _simulate_path_fast.cache_clear()

    features = make_causal_features(df).copy()
    features["date"] = pd.to_datetime(features["date"])
    features = features.set_index("date")
    event_dates = pd.to_datetime(events["date"])

    xs: list[np.ndarray] = []
    success: list[float] = []
    net_return: list[float] = []
    lowers: list[float] = []
    uppers: list[float] = []
    path_counts: list[int] = []
    realized_returns: list[float] = []
    raw_indices: list[int] = []
    dates: list[object] = []

    candidates = np.flatnonzero(events["entry_candidate"].to_numpy(dtype=bool))
    for raw_entry in candidates:
        entry = int(raw_entry)
        end = entry + HORIZON - 1
        if entry < LOOKBACK - 1 or end >= len(events):
            continue

        lookback_dates = event_dates.iloc[entry - LOOKBACK + 1 : entry + 1]
        window = features.reindex(lookback_dates)
        if window.loc[:, FEATURE_COLUMNS].isna().any().any():
            continue
        x = window.loc[:, FEATURE_COLUMNS].to_numpy(dtype=np.float32).T
        if x.shape != (len(FEATURE_COLUMNS), LOOKBACK):
            raise RuntimeError(f"unexpected feature shape {x.shape}")

        p, mean_ret, lower, upper, n_paths = _entry_target(entry, end)
        actual_ret = _actual_entry_return(entry, end)
        xs.append(x)
        success.append(p)
        net_return.append(mean_ret)
        lowers.append(lower)
        uppers.append(upper)
        path_counts.append(n_paths)
        realized_returns.append(actual_ret)
        raw_indices.append(entry)
        dates.append(event_dates.iloc[entry])

    if not xs:
        raise RuntimeError("no QQQ Entry candidates survived dataset construction")

    return SuccessDataset(
        x=torch.from_numpy(np.stack(xs)),
        success_probability=np.asarray(success, dtype=float),
        net_expected_return=np.asarray(net_return, dtype=float),
        entry_lower=np.asarray(lowers, dtype=float),
        entry_upper=np.asarray(uppers, dtype=float),
        path_count=np.asarray(path_counts, dtype=int),
        realized_return=np.asarray(realized_returns, dtype=float),
        raw_indices=np.asarray(raw_indices, dtype=int),
        dates=np.asarray(dates),
    )


def _event_folds(raw_indices: np.ndarray) -> tuple[EventFold, ...]:
    raw_indices = np.asarray(raw_indices, dtype=int)
    folds: list[EventFold] = []
    for test_start in range(MIN_TRAIN_EVENTS, len(raw_indices), TEST_EVENTS):
        test = np.arange(test_start, min(test_start + TEST_EVENTS, len(raw_indices)), dtype=int)
        if len(test) != TEST_EVENTS:
            continue
        cutoff = int(raw_indices[test[0]]) - PURGE_RAW_SESSIONS - 1
        train = np.where(raw_indices[:test_start] <= cutoff)[0]
        if len(train) < MIN_TRAIN_EVENTS:
            continue
        folds.append(EventFold(train=train, test=test))
    if not folds:
        raise RuntimeError("no complete purged chronological QQQ folds")
    return tuple(folds[-MAX_FOLDS:])


def _rankdata(values: np.ndarray) -> np.ndarray:
    return pd.Series(values).rank(method="average").to_numpy(dtype=float)


def _spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) < 2 or np.std(y_pred) < 1e-12 or np.std(y_true) < 1e-12:
        return float("nan")
    return float(np.corrcoef(_rankdata(y_true), _rankdata(y_pred))[0, 1])


def _top_indices(prediction: np.ndarray) -> np.ndarray:
    n_top = max(1, int(math.ceil(len(prediction) * TOP_FRACTION)))
    return np.argsort(prediction, kind="stable")[-n_top:]


def _metrics(
    y_true: np.ndarray,
    net_return: np.ndarray,
    realized_return: np.ndarray,
    prediction: np.ndarray,
) -> dict[str, float]:
    top = _top_indices(prediction)
    realized_all_success = float(np.mean(realized_return > 0.0))
    realized_top_success = float(np.mean(realized_return[top] > 0.0))
    return {
        "mae": float(np.mean(np.abs(y_true - prediction))),
        "brier": float(np.mean((y_true - prediction) ** 2)),
        "spearman": _spearman(y_true, prediction),
        "all_success": float(np.mean(y_true)),
        "top_success": float(np.mean(y_true[top])),
        "top_success_lift": float(np.mean(y_true[top]) - np.mean(y_true)),
        "all_net_return": float(np.mean(net_return)),
        "top_net_return": float(np.mean(net_return[top])),
        "realized_all_success": realized_all_success,
        "realized_top_success": realized_top_success,
        "realized_success_lift": realized_top_success - realized_all_success,
        "realized_all_net_return": float(np.mean(realized_return)),
        "realized_top_net_return": float(np.mean(realized_return[top])),
    }


def _fit(
    x_train: torch.Tensor,
    y_train: np.ndarray,
    x_test: torch.Tensor,
    *,
    seed: int,
) -> np.ndarray:
    torch.manual_seed(seed)
    model = EntrySuccessCNN().cpu()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    loss_fn = nn.BCELoss()
    target = torch.from_numpy(np.asarray(y_train, dtype=np.float32))

    model.train()
    for _ in range(EPOCHS):
        optimizer.zero_grad(set_to_none=True)
        pred = model(x_train)
        loss = loss_fn(pred, target)
        loss.backward()
        optimizer.step()

    model.eval()
    with torch.no_grad():
        return model(x_test).cpu().numpy().astype(float)


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


def main() -> None:
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    ds = make_success_dataset(df)
    folds = _event_folds(ds.raw_indices)

    print(
        "S1 SUCCESS_MODEL DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"samples={len(ds.success_probability)} folds={len(folds)} lookback={LOOKBACK} horizon={HORIZON} "
        f"reference_lookback={REFERENCE_LOOKBACK} purge_raw_sessions={PURGE_RAW_SESSIONS} "
        f"epochs={EPOCHS} seeds={','.join(map(str, SEEDS))} no_random_split=true"
    )
    print(
        "S1 SUCCESS_MODEL TARGET "
        "name=entry_success_probability definition=mean(unique_legal_path_return_gt_0) "
        "secondary=entry_net_expected_return lower=min_unique_legal_path_return "
        "upper=max_unique_legal_path_return future_labels_not_features=true"
    )
    print(
        "S1 SUCCESS_MODEL RULE "
        "research_version=formal_max2_spacing20 max_addons=2 addon2_spacing_tolerance=0.20 "
        "distribution_weighting=unique_realized_paths entry_set=all_entry_candidates"
    )
    print(
        "S1 SUCCESS_MODEL ACTUAL_EXECUTION "
        "selection=top20_predicted_entry_success_probability "
        "addon1=nearest_known_local_max_within_prior_60_sessions "
        "addon2=nearest_older_known_local_max_gap_gt_5 addon2_spacing_tolerance=0.20 "
        "exit=existing_strategy1_deterministic_execution horizon=60"
    )
    print(
        f"S1 SUCCESS_MODEL MODEL name=ENTRY_SUCCESS_CNN params={count_parameters(EntrySuccessCNN())} "
        "loss=binary_cross_entropy_soft_target output=sigmoid_probability"
    )
    print(
        "S1 SUCCESS_MODEL BASELINE "
        f"target_success_mean={ds.success_probability.mean():.6f} "
        f"target_success_median={np.median(ds.success_probability):.6f} "
        f"entry_net_return_mean={ds.net_expected_return.mean():.6f} "
        f"entry_lower_mean={ds.entry_lower.mean():.6f} entry_upper_mean={ds.entry_upper.mean():.6f} "
        f"paths_mean={ds.path_count.mean():.3f} "
        f"actual_success_rate={np.mean(ds.realized_return > 0.0):.6f} "
        f"actual_net_expected_return={ds.realized_return.mean():.6f}"
    )

    all_metrics: list[dict[str, float]] = []
    for fold_id, fold in enumerate(folds, start=1):
        train, test = fold.train, fold.test
        gap = int(ds.raw_indices[test[0]] - ds.raw_indices[train[-1]] - 1)
        print(
            f"S1 SUCCESS_MODEL FOLD id={fold_id} n_train={len(train)} n_test={len(test)} "
            f"train_first={pd.Timestamp(ds.dates[train[0]]).date()} "
            f"train_last={pd.Timestamp(ds.dates[train[-1]]).date()} "
            f"test_first={pd.Timestamp(ds.dates[test[0]]).date()} "
            f"test_last={pd.Timestamp(ds.dates[test[-1]]).date()} raw_session_gap={gap}"
        )

        y_train = ds.success_probability[train]
        y_test = ds.success_probability[test]
        net_test = ds.net_expected_return[test]
        realized_test = ds.realized_return[test]
        constant = np.full(len(test), float(np.mean(y_train)), dtype=float)
        cm = _metrics(y_test, net_test, realized_test, constant)
        print(
            f"S1 SUCCESS_MODEL FOLD_METRIC id={fold_id} model=CONSTANT "
            f"mae={cm['mae']:.6f} brier={cm['brier']:.6f} "
            f"all_success={cm['all_success']:.6f} top_success={cm['top_success']:.6f} "
            f"top_success_lift={cm['top_success_lift']:.6f} top_net_return={cm['top_net_return']:.6f} "
            f"realized_all_success={cm['realized_all_success']:.6f} "
            f"realized_top_success={cm['realized_top_success']:.6f} "
            f"realized_success_lift={cm['realized_success_lift']:.6f} "
            f"realized_all_net_return={cm['realized_all_net_return']:.6f} "
            f"realized_top_net_return={cm['realized_top_net_return']:.6f}"
        )

        for seed in SEEDS:
            pred = _fit(ds.x[train].cpu(), y_train, ds.x[test].cpu(), seed=seed)
            m = _metrics(y_test, net_test, realized_test, pred)
            all_metrics.append(m)
            print(
                f"S1 SUCCESS_MODEL FOLD_METRIC id={fold_id} model=ENTRY_SUCCESS_CNN seed={seed} "
                f"spearman={_fmt(m['spearman'])} mae={m['mae']:.6f} brier={m['brier']:.6f} "
                f"all_success={m['all_success']:.6f} top_success={m['top_success']:.6f} "
                f"top_success_lift={m['top_success_lift']:.6f} "
                f"all_net_return={m['all_net_return']:.6f} top_net_return={m['top_net_return']:.6f} "
                f"realized_all_success={m['realized_all_success']:.6f} "
                f"realized_top_success={m['realized_top_success']:.6f} "
                f"realized_success_lift={m['realized_success_lift']:.6f} "
                f"realized_all_net_return={m['realized_all_net_return']:.6f} "
                f"realized_top_net_return={m['realized_top_net_return']:.6f}"
            )

    spearman = np.asarray([m["spearman"] for m in all_metrics], dtype=float)
    valid = spearman[np.isfinite(spearman)]
    lift = np.asarray([m["top_success_lift"] for m in all_metrics], dtype=float)
    top_success = np.asarray([m["top_success"] for m in all_metrics], dtype=float)
    all_success = np.asarray([m["all_success"] for m in all_metrics], dtype=float)
    top_net = np.asarray([m["top_net_return"] for m in all_metrics], dtype=float)
    all_net = np.asarray([m["all_net_return"] for m in all_metrics], dtype=float)
    realized_lift = np.asarray([m["realized_success_lift"] for m in all_metrics], dtype=float)
    realized_top_success = np.asarray([m["realized_top_success"] for m in all_metrics], dtype=float)
    realized_all_success = np.asarray([m["realized_all_success"] for m in all_metrics], dtype=float)
    realized_top_net = np.asarray([m["realized_top_net_return"] for m in all_metrics], dtype=float)
    realized_all_net = np.asarray([m["realized_all_net_return"] for m in all_metrics], dtype=float)
    mae = np.asarray([m["mae"] for m in all_metrics], dtype=float)
    brier = np.asarray([m["brier"] for m in all_metrics], dtype=float)

    print(
        "S1 SUCCESS_MODEL SUMMARY "
        f"ticker={TICKER} runs={len(all_metrics)} "
        f"spearman_mean={_fmt(float(valid.mean()) if len(valid) else float('nan'))} "
        f"spearman_positive={int(np.sum(valid > 0.0))}/{len(valid)} "
        f"mae_mean={mae.mean():.6f} brier_mean={brier.mean():.6f} "
        f"all_success_mean={all_success.mean():.6f} top20_success_mean={top_success.mean():.6f} "
        f"top20_success_lift_mean={lift.mean():.6f} "
        f"top20_success_lift_positive={int(np.sum(lift > 0.0))}/{len(lift)} "
        f"all_net_return_mean={all_net.mean():.6f} top20_net_return_mean={top_net.mean():.6f} "
        f"realized_all_success_mean={realized_all_success.mean():.6f} "
        f"realized_top20_success_mean={realized_top_success.mean():.6f} "
        f"realized_top20_success_lift_mean={realized_lift.mean():.6f} "
        f"realized_top20_success_lift_positive={int(np.sum(realized_lift > 0.0))}/{len(realized_lift)} "
        f"realized_all_net_return_mean={realized_all_net.mean():.6f} "
        f"realized_top20_net_return_mean={realized_top_net.mean():.6f}"
    )
    print("S1 SUCCESS_MODEL PASS")


if __name__ == "__main__":
    main()

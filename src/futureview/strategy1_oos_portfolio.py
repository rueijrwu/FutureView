from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_spy_daily
from .datasets import build_windows
from .features import make_causal_features
from .models import TrendCNNJoint
from .strategy1 import add_strategy1_events, _simulate_from_start
from .strategy1_summary_baseline import _fit_ridge, _summary_features
from .strategy1_targets import STRATEGY1_TARGET_COLUMNS, make_strategy1_targets
from .walkforward import purged_expanding_walk_forward

HORIZONS = (15, 30, 45, 60)
TARGET_HORIZON = 30
TARGET_INDEX = HORIZONS.index(TARGET_HORIZON)
SEEDS = (20260821, 20260822, 20260823, 20260824, 20260825)
EPOCHS = 20
LEARNING_RATE = 3e-3
HUBER_DELTA = 0.01
PURGE = 60
TEST_SIZE = 60
MIN_EXPANDING_TRAIN = 320
SLIDING_TRAIN = 260
GATE_QUANTILE = 0.80


@dataclass(frozen=True)
class CampaignChoice:
    start: int
    end: int
    run: object


def _fit_cnn_predict(
    x_train: torch.Tensor,
    y_train: torch.Tensor,
    x_eval: torch.Tensor,
    *,
    seed: int,
) -> np.ndarray:
    torch.manual_seed(seed)
    model = TrendCNNJoint().cpu()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    loss_fn = nn.HuberLoss(delta=HUBER_DELTA)
    model.train()
    for _ in range(EPOCHS):
        optimizer.zero_grad(set_to_none=True)
        pred = model(x_train)
        loss = loss_fn(pred, y_train)
        loss.backward()
        optimizer.step()
    model.eval()
    with torch.no_grad():
        return model(x_eval).cpu().numpy().astype(float)[:, TARGET_INDEX]


def _campaign_end(run) -> int:
    if not run.actions:
        raise RuntimeError("traded campaign has no actions")
    return int(run.actions[-1].index)


def _build_gate_map(
    dates: pd.DatetimeIndex,
    events: pd.DataFrame,
    folds,
    windows,
    y: np.ndarray,
    summary_x: np.ndarray,
) -> tuple[dict[int, bool], dict[int, bool]]:
    event_index = {
        pd.Timestamp(d): i for i, d in enumerate(pd.to_datetime(events["date"]))
    }
    cnn_gate: dict[int, bool] = {}
    ridge_gate: dict[int, bool] = {}

    for fold_id, fold in enumerate(folds, start=1):
        expanding_idx = fold.train
        test_idx = fold.test
        train_end = int(expanding_idx[-1]) + 1
        train_idx = np.arange(train_end - SLIDING_TRAIN, train_end, dtype=int)
        if train_idx[0] < 0:
            raise RuntimeError("sliding train window begins before dataset")

        x_train = windows.x[train_idx].cpu()
        y_train_all = windows.y[train_idx].cpu()
        x_joined = torch.cat([windows.x[train_idx].cpu(), windows.x[test_idx].cpu()], dim=0)

        cnn_preds = []
        for seed in SEEDS:
            pred = _fit_cnn_predict(x_train, y_train_all, x_joined, seed=seed)
            cnn_preds.append(pred)
        cnn_ensemble = np.mean(np.vstack(cnn_preds), axis=0)
        cnn_train = cnn_ensemble[: len(train_idx)]
        cnn_test = cnn_ensemble[len(train_idx) :]
        cnn_threshold = float(np.quantile(cnn_train, GATE_QUANTILE))

        ridge_train = _fit_ridge(summary_x[train_idx], y[train_idx], summary_x[train_idx])
        ridge_test = _fit_ridge(summary_x[train_idx], y[train_idx], summary_x[test_idx])
        ridge_threshold = float(np.quantile(ridge_train, GATE_QUANTILE))

        cnn_high = cnn_test >= cnn_threshold
        ridge_high = ridge_test >= ridge_threshold
        print(
            f"S1 OOS_PORTFOLIO FOLD id={fold_id} "
            f"train_first={dates[train_idx[0]].date()} train_last={dates[train_idx[-1]].date()} "
            f"test_first={dates[test_idx[0]].date()} test_last={dates[test_idx[-1]].date()} "
            f"cnn_threshold={cnn_threshold:.6f} cnn_signal_rate={cnn_high.mean():.3f} "
            f"ridge_threshold={ridge_threshold:.6f} ridge_signal_rate={ridge_high.mean():.3f}"
        )

        for local, window_idx in enumerate(test_idx):
            pred_date = pd.Timestamp(dates[window_idx])
            if pred_date not in event_index:
                raise RuntimeError(f"prediction date missing from event frame: {pred_date}")
            entry_idx = event_index[pred_date] + 1
            if entry_idx >= len(events):
                continue
            cnn_gate[entry_idx] = bool(cnn_high[local])
            ridge_gate[entry_idx] = bool(ridge_high[local])

    return cnn_gate, ridge_gate


def _select_sequential(
    events: pd.DataFrame,
    first_entry: int,
    last_entry: int,
    gate: dict[int, bool] | None,
) -> list[CampaignChoice]:
    chosen: list[CampaignChoice] = []
    busy_until = -1
    for i in range(first_entry, last_entry + 1):
        if i <= busy_until:
            continue
        if not bool(events.at[i, "entry1_event"]):
            continue
        if gate is not None and not gate.get(i, False):
            continue
        horizon_end = i + TARGET_HORIZON - 1
        if horizon_end >= len(events):
            break
        run = _simulate_from_start(events, i, horizon_end)
        end = _campaign_end(run)
        chosen.append(CampaignChoice(i, end, run))
        busy_until = end
    return chosen


def _hindsight_upper(
    events: pd.DataFrame,
    first_entry: int,
    last_entry: int,
) -> list[CampaignChoice]:
    candidates: list[CampaignChoice] = []
    for i in range(first_entry, last_entry + 1):
        if not bool(events.at[i, "entry1_event"]):
            continue
        horizon_end = i + TARGET_HORIZON - 1
        if horizon_end >= len(events):
            break
        run = _simulate_from_start(events, i, horizon_end)
        candidates.append(CampaignChoice(i, _campaign_end(run), run))

    candidates.sort(key=lambda c: (c.end, c.start))
    ends = [c.end for c in candidates]
    prev = [bisect_left(ends, c.start) - 1 for c in candidates]
    dp = np.zeros(len(candidates) + 1, dtype=float)
    take = np.zeros(len(candidates), dtype=bool)

    for j, c in enumerate(candidates):
        ret = float(c.run.final_return)
        weight = math.log1p(ret) if ret > -1.0 else -float("inf")
        take_value = dp[prev[j] + 1] + weight
        skip_value = dp[j]
        if take_value > skip_value and weight > 0.0:
            dp[j + 1] = take_value
            take[j] = True
        else:
            dp[j + 1] = skip_value

    chosen: list[CampaignChoice] = []
    j = len(candidates) - 1
    while j >= 0:
        c = candidates[j]
        ret = float(c.run.final_return)
        weight = math.log1p(ret) if ret > -1.0 else -float("inf")
        take_value = dp[prev[j] + 1] + weight
        if take[j] and abs(dp[j + 1] - take_value) < 1e-12:
            chosen.append(c)
            j = prev[j]
        else:
            j -= 1
    chosen.reverse()
    return chosen


def _relative_campaign_curve(events: pd.DataFrame, choice: CampaignChoice) -> tuple[np.ndarray, np.ndarray]:
    run = choice.run
    action_map: dict[int, list] = {}
    for action in run.actions:
        action_map.setdefault(int(action.index), []).append(action)

    cash = 1.0
    shares = 0.0
    indices = np.arange(choice.start, choice.end + 1, dtype=int)
    equity = np.empty(len(indices), dtype=float)

    for k, i in enumerate(indices):
        price = float(events.at[i, "close"])
        for action in action_map.get(i, []):
            if action.action in {"entry1", "addon1", "addon2"}:
                amount = float(action.fraction)
                shares += amount / price
                cash -= amount
            elif action.action == "exit5_half":
                sold = 0.5 * shares
                cash += sold * price
                shares -= sold
            elif action.action in {"exit10_full", "horizon_exit"}:
                cash += shares * price
                shares = 0.0
            else:
                raise RuntimeError(f"unknown Strategy 1 action: {action.action}")
        equity[k] = cash + shares * price

    expected = 1.0 + float(run.final_return)
    if not np.isclose(equity[-1], expected, atol=1e-10, rtol=1e-10):
        raise RuntimeError(
            f"campaign equity mismatch: reconstructed={equity[-1]:.12f} expected={expected:.12f}"
        )
    return indices, equity


def _portfolio_metrics(
    events: pd.DataFrame,
    campaigns: list[CampaignChoice],
    evaluation_start: int,
    evaluation_end: int,
) -> dict[str, float]:
    n = evaluation_end - evaluation_start + 1
    curve = np.ones(n, dtype=float)
    current_equity = 1.0
    cursor = evaluation_start

    for choice in campaigns:
        if choice.start < cursor:
            raise RuntimeError("campaigns overlap or are out of order")
        if cursor <= choice.start:
            curve[cursor - evaluation_start : choice.start - evaluation_start + 1] = current_equity
        idx, rel = _relative_campaign_curve(events, choice)
        curve[idx - evaluation_start] = current_equity * rel
        current_equity *= float(rel[-1])
        cursor = choice.end + 1

    if cursor <= evaluation_end:
        curve[cursor - evaluation_start :] = current_equity

    running_max = np.maximum.accumulate(curve)
    max_drawdown = float(np.max(1.0 - curve / running_max))
    total_return = float(curve[-1] - 1.0)
    intervals = max(1, evaluation_end - evaluation_start)
    annualized = float(curve[-1] ** (252.0 / intervals) - 1.0) if curve[-1] > 0 else -1.0
    returns = np.asarray([float(c.run.final_return) for c in campaigns], dtype=float)
    exposure_days = float(sum(float(c.run.exposure_days) for c in campaigns))
    holding_days = float(sum(int(c.run.holding_days) for c in campaigns))

    return {
        "total_return": total_return,
        "annualized_return": annualized,
        "max_drawdown": max_drawdown,
        "campaigns": float(len(campaigns)),
        "win_rate": float(np.mean(returns > 0.0)) if len(returns) else float("nan"),
        "avg_campaign_return": float(returns.mean()) if len(returns) else float("nan"),
        "exposure_days": exposure_days,
        "holding_days": holding_days,
        "exposure_ratio": exposure_days / intervals,
        "return_per_exposure_day": total_return / exposure_days if exposure_days > 0.0 else float("nan"),
    }


def _fmt(value: float) -> str:
    return "nan" if not np.isfinite(value) else f"{value:.6f}"


def main() -> None:
    torch.set_num_threads(2)
    df = download_spy_daily(period="3y")
    events = add_strategy1_events(df).reset_index(drop=True)
    features = make_causal_features(df)
    targets = make_strategy1_targets(df)
    windows = build_windows(features, targets, lookback=50, target_columns=STRATEGY1_TARGET_COLUMNS)
    dates = pd.DatetimeIndex(pd.to_datetime(windows.dates))
    y = windows.y.numpy().astype(float)[:, TARGET_INDEX]
    summary_x = _summary_features(windows.x)

    all_folds = purged_expanding_walk_forward(
        len(y), min_train=MIN_EXPANDING_TRAIN, test_size=TEST_SIZE, purge=PURGE, step=TEST_SIZE
    )
    folds = tuple(f for f in all_folds if len(f.test) == TEST_SIZE)
    if not folds:
        raise RuntimeError("no complete common OOS folds")

    print(
        f"S1 OOS_PORTFOLIO DATA windows={len(y)} folds={len(folds)} horizon={TARGET_HORIZON} "
        f"train=SLIDING_{SLIDING_TRAIN} gate_quantile={GATE_QUANTILE:.2f} "
        f"first={dates[0].date()} last={dates[-1].date()} seeds={','.join(map(str, SEEDS))}"
    )
    print(
        "S1 OOS_PORTFOLIO RULE prediction_at_close_t_gates_entry1_at_t_plus_1 "
        "campaign_horizon=30_sessions flat_only=true overlapping_capital=false"
    )

    cnn_gate, ridge_gate = _build_gate_map(dates, events, folds, windows, y, summary_x)

    event_index = {
        pd.Timestamp(d): i for i, d in enumerate(pd.to_datetime(events["date"]))
    }
    first_test_window = int(folds[0].test[0])
    last_test_window = int(folds[-1].test[-1])
    first_pred_event = event_index[pd.Timestamp(dates[first_test_window])]
    last_pred_event = event_index[pd.Timestamp(dates[last_test_window])]
    first_entry = first_pred_event + 1
    last_entry = last_pred_event + 1
    evaluation_start = first_pred_event
    evaluation_end = min(last_entry + TARGET_HORIZON - 1, len(events) - 1)

    strategies = {
        "ALWAYS_ON": _select_sequential(events, first_entry, last_entry, gate=None),
        "SUMMARY_RIDGE_FILTERED": _select_sequential(events, first_entry, last_entry, gate=ridge_gate),
        "CNN_ENSEMBLE_FILTERED": _select_sequential(events, first_entry, last_entry, gate=cnn_gate),
        "HINDSIGHT_ENTRY_UPPER": _hindsight_upper(events, first_entry, last_entry),
    }

    print(
        f"S1 OOS_PORTFOLIO PERIOD signal_first={events.at[evaluation_start, 'date'].date()} "
        f"signal_last={events.at[last_pred_event, 'date'].date()} "
        f"entry_first={events.at[first_entry, 'date'].date()} entry_last={events.at[last_entry, 'date'].date()} "
        f"evaluation_end={events.at[evaluation_end, 'date'].date()}"
    )

    for name, campaigns in strategies.items():
        m = _portfolio_metrics(events, campaigns, evaluation_start, evaluation_end)
        print(
            f"S1 OOS_PORTFOLIO RESULT model={name} campaigns={int(m['campaigns'])} "
            f"total_return={m['total_return']:.6f} annualized_return={m['annualized_return']:.6f} "
            f"max_drawdown={m['max_drawdown']:.6f} win_rate={_fmt(m['win_rate'])} "
            f"avg_campaign_return={_fmt(m['avg_campaign_return'])} "
            f"exposure_days={m['exposure_days']:.6f} holding_days={m['holding_days']:.0f} "
            f"exposure_ratio={m['exposure_ratio']:.6f} "
            f"return_per_exposure_day={_fmt(m['return_per_exposure_day'])}"
        )
        for k, c in enumerate(campaigns, start=1):
            print(
                f"S1 OOS_PORTFOLIO CAMPAIGN model={name} id={k} "
                f"start={events.at[c.start, 'date'].date()} end={events.at[c.end, 'date'].date()} "
                f"return={c.run.final_return:.6f} exposure_days={c.run.exposure_days:.6f} "
                f"entries={c.run.entries_used} partial_exit={int(c.run.partial_exit_used)} "
                f"full_exit={int(c.run.full_exit_used)} horizon_exit={int(c.run.horizon_exit_used)}"
            )

    print("S1 OOS_PORTFOLIO PASS")


if __name__ == "__main__":
    main()

from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd
import torch
import yfinance as yf
from torch import nn

from .data import canonicalize_ohlcv, download_spy_daily
from .datasets import build_windows
from .features import FEATURE_COLUMNS, make_causal_features
from .strategy1_targets import STRATEGY1_TARGET_COLUMNS, make_strategy1_targets
from .walkforward import purged_expanding_walk_forward

HORIZONS = (15, 30, 45, 60)
TARGET_HORIZON = 30
TARGET_INDEX = HORIZONS.index(TARGET_HORIZON)
SEEDS = (20260821, 20260822, 20260823, 20260824, 20260825)
EPOCHS = 20
LEARNING_RATE = 3e-3
HUBER_DELTA = 0.01
TOP_FRACTION = 0.20
PURGE = 60
TEST_SIZE = 60
SLIDING_TRAIN = 260
DAILY_LOOKBACK = 50
INTRADAY_BARS_PER_DAY = 2
INTRADAY_LOOKBACK = DAILY_LOOKBACK * INTRADAY_BARS_PER_DAY


class MatchedScaleJointCNN(nn.Module):
    """Model-A-style CNN with fixed parameter count and configurable dilation.

    Daily uses dilation=1. Two-bars-per-session intraday uses dilation=2 so the
    5/10/20-kernel branches span approximately the same calendar durations while
    seeing twice as many observations over the same ~50-session lookback.
    """

    def __init__(self, dilation: int) -> None:
        super().__init__()
        self.branches = nn.ModuleList(
            [
                nn.Sequential(
                    nn.Conv1d(5, 8, kernel_size=k, dilation=dilation, padding="same"),
                    nn.GELU(),
                )
                for k in (5, 10, 20)
            ]
        )
        self.fusion = nn.Sequential(
            nn.Conv1d(24, 16, kernel_size=3, dilation=dilation, padding="same"),
            nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(16, 8),
            nn.GELU(),
            nn.Linear(8, len(HORIZONS)),
            nn.Tanh(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = torch.cat([branch(x) for branch in self.branches], dim=1)
        return self.head(self.fusion(z))


def _download_spy_1h(period: str = "730d", attempts: int = 3) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            frame = yf.download(
                "SPY",
                period=period,
                interval="1h",
                auto_adjust=False,
                actions=False,
                prepost=False,
                progress=False,
                threads=False,
                timeout=30,
            )
            if frame is not None and not frame.empty:
                if isinstance(frame.columns, pd.MultiIndex):
                    frame = frame.copy()
                    frame.columns = frame.columns.get_level_values(0)
                required = ["Open", "High", "Low", "Close", "Volume"]
                missing = [c for c in required if c not in frame.columns]
                if missing:
                    raise ValueError(f"missing hourly OHLCV columns: {missing}")
                out = frame[required].copy().reset_index()
                stamp = out.columns[0]
                dt = pd.to_datetime(out[stamp], utc=True)
                out["timestamp"] = dt.dt.tz_convert("America/New_York")
                out = out.rename(columns={
                    "Open": "open", "High": "high", "Low": "low",
                    "Close": "close", "Volume": "volume",
                })
                return out[["timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
            last_error = RuntimeError("Yahoo Finance returned an empty SPY 1h frame")
        except Exception as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(float(attempt))
    raise RuntimeError("failed to download SPY 1h data") from last_error


def _aggregate_two_bars_per_session(hourly: pd.DataFrame) -> pd.DataFrame:
    """Aggregate regular-session 1h bars into two session-aware intraday bars.

    Yahoo regular-session 1h SPY data normally has seven bars per US session.
    Bars 0..3 become the first ~4h bar; remaining bars become the second bar.
    The second bar is shorter because the regular cash session is 6.5 hours.
    """
    work = hourly.copy()
    work["session"] = work["timestamp"].dt.tz_localize(None).dt.normalize()
    rows: list[dict[str, object]] = []
    for session, group in work.groupby("session", sort=True):
        g = group.sort_values("timestamp").reset_index(drop=True)
        if len(g) < 6:
            continue
        split = min(4, len(g) - 1)
        for slot, part in enumerate((g.iloc[:split], g.iloc[split:]), start=1):
            if part.empty:
                continue
            rows.append({
                "timestamp": part["timestamp"].iloc[-1],
                "date": pd.Timestamp(session),
                "slot": slot,
                "open": float(part["open"].iloc[0]),
                "high": float(part["high"].max()),
                "low": float(part["low"].min()),
                "close": float(part["close"].iloc[-1]),
                "volume": float(part["volume"].sum()),
            })
    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError("no intraday bars after session aggregation")
    counts = out.groupby("date").size()
    complete = counts[counts == INTRADAY_BARS_PER_DAY].index
    return out[out["date"].isin(complete)].sort_values(["date", "slot"]).reset_index(drop=True)


def _make_intraday_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Causal OHLCV features on intraday bars with calendar-matched volume z window."""
    out = bars.copy()
    prev_close = out["close"].shift(1)
    out["open_rel"] = out["open"] / prev_close - 1.0
    out["high_rel"] = out["high"] / prev_close - 1.0
    out["low_rel"] = out["low"] / prev_close - 1.0
    out["close_rel"] = out["close"] / prev_close - 1.0
    log_volume = np.log(out["volume"].clip(lower=1).astype(float))
    volume_window = 20 * INTRADAY_BARS_PER_DAY
    mean = log_volume.rolling(volume_window, min_periods=volume_window).mean()
    std = log_volume.rolling(volume_window, min_periods=volume_window).std(ddof=0)
    out["volume_z"] = (log_volume - mean) / std.replace(0.0, np.nan)
    return out[["date", "slot", *FEATURE_COLUMNS]].replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)


def _build_intraday_windows(features: pd.DataFrame, targets: pd.DataFrame) -> tuple[torch.Tensor, torch.Tensor, pd.DatetimeIndex]:
    target_map = targets.copy()
    target_map["date"] = pd.to_datetime(target_map["date"]).dt.normalize()
    target_map = target_map.set_index("date")
    values: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    dates: list[pd.Timestamp] = []
    arr = features.loc[:, list(FEATURE_COLUMNS)].to_numpy(dtype=np.float32)
    for i in range(INTRADAY_LOOKBACK - 1, len(features)):
        if int(features.at[i, "slot"]) != INTRADAY_BARS_PER_DAY:
            continue
        date = pd.Timestamp(features.at[i, "date"]).normalize()
        if date not in target_map.index:
            continue
        start = i - INTRADAY_LOOKBACK + 1
        chunk = arr[start:i + 1]
        if len(chunk) != INTRADAY_LOOKBACK:
            continue
        y = target_map.loc[date, list(STRATEGY1_TARGET_COLUMNS)].to_numpy(dtype=np.float32)
        values.append(chunk.T)
        labels.append(y)
        dates.append(date)
    if not values:
        raise RuntimeError("no aligned intraday windows")
    return torch.tensor(np.stack(values)), torch.tensor(np.stack(labels)), pd.DatetimeIndex(dates)


def _spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if len(y_true) < 2 or np.std(y_pred) < 1e-12:
        return float("nan")
    a = pd.Series(y_true).rank(method="average").to_numpy(dtype=float)
    b = pd.Series(y_pred).rank(method="average").to_numpy(dtype=float)
    if np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    mae = float(np.mean(np.abs(y_true - y_pred)))
    sp = _spearman(y_true, y_pred)
    n_top = max(1, int(math.ceil(len(y_pred) * TOP_FRACTION)))
    order = np.argsort(y_pred, kind="stable")
    top = float(np.mean(y_true[order[-n_top:]]))
    bottom = float(np.mean(y_true[order[:n_top]]))
    overall = float(np.mean(y_true))
    return {"spearman": sp, "mae": mae, "lift": top - overall, "top_bottom": top - bottom}


def _fit_model(model: nn.Module, x_train: torch.Tensor, y_train: torch.Tensor, x_test: torch.Tensor, seed: int) -> np.ndarray:
    torch.manual_seed(seed)
    model = model.cpu()
    opt = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    loss_fn = nn.HuberLoss(delta=HUBER_DELTA)
    model.train()
    for _ in range(EPOCHS):
        opt.zero_grad(set_to_none=True)
        pred = model(x_train)
        loss = loss_fn(pred, y_train)
        loss.backward()
        opt.step()
    model.eval()
    with torch.no_grad():
        return model(x_test).cpu().numpy().astype(float)[:, TARGET_INDEX]


def _fmt(v: float) -> str:
    return "nan" if not np.isfinite(v) else f"{v:.6f}"


def main() -> None:
    torch.set_num_threads(2)
    daily = download_spy_daily(period="3y")
    targets = make_strategy1_targets(daily)
    daily_features = make_causal_features(daily)
    daily_windows = build_windows(daily_features, targets, lookback=DAILY_LOOKBACK, target_columns=STRATEGY1_TARGET_COLUMNS)

    hourly = _download_spy_1h()
    intraday_bars = _aggregate_two_bars_per_session(hourly)
    intraday_features = _make_intraday_features(intraday_bars)
    x4, y4, d4 = _build_intraday_windows(intraday_features, targets)

    dd = pd.DatetimeIndex(pd.to_datetime(daily_windows.dates)).normalize()
    common = dd.intersection(d4)
    if len(common) < SLIDING_TRAIN + PURGE + TEST_SIZE:
        raise RuntimeError(
            f"insufficient common daily/intraday dates: {len(common)}; need at least "
            f"{SLIDING_TRAIN + PURGE + TEST_SIZE}. Yahoo hourly history is provider-limited."
        )
    daily_pos = pd.Series(np.arange(len(dd)), index=dd)
    intra_pos = pd.Series(np.arange(len(d4)), index=d4)
    di = daily_pos.loc[common].to_numpy(dtype=int)
    ii = intra_pos.loc[common].to_numpy(dtype=int)
    xd = daily_windows.x[di].cpu()
    yd = daily_windows.y[di].cpu()
    x4 = x4[ii].cpu()
    y4 = y4[ii].cpu()
    if not torch.allclose(yd, y4, atol=1e-7, rtol=0.0):
        raise RuntimeError("daily and intraday target labels are not identical on common dates")

    folds_all = purged_expanding_walk_forward(
        len(common), min_train=SLIDING_TRAIN, test_size=TEST_SIZE, purge=PURGE, step=TEST_SIZE
    )
    folds = tuple(f for f in folds_all if len(f.test) == TEST_SIZE)
    if not folds:
        raise RuntimeError("no complete common OOS fold within available hourly history")

    print(
        f"S1 FREQUENCY_COMPARE DATA common_windows={len(common)} folds={len(folds)} "
        f"first={common[0].date()} last={common[-1].date()} horizon={TARGET_HORIZON} "
        f"train=SLIDING_{SLIDING_TRAIN} purge={PURGE} test_size={TEST_SIZE} seeds={','.join(map(str, SEEDS))}"
    )
    print(
        f"S1 FREQUENCY_COMPARE DESIGN daily_bars={DAILY_LOOKBACK} intraday_bars={INTRADAY_LOOKBACK} "
        f"bars_per_session={INTRADAY_BARS_PER_DAY} matched_calendar_sessions~={DAILY_LOOKBACK} "
        "daily_dilation=1 intraday_dilation=2 same_parameter_count=true target_identical=true"
    )
    print(
        f"S1 FREQUENCY_COMPARE COVERAGE hourly_first={hourly['timestamp'].iloc[0]} hourly_last={hourly['timestamp'].iloc[-1]} "
        f"intraday_sessions={intraday_bars['date'].nunique()}"
    )

    results: dict[str, dict[int, list[dict[str, float]]]] = {
        "DAILY_50": {s: [] for s in SEEDS}, "INTRADAY_100": {s: [] for s in SEEDS}
    }
    for fold_id, fold in enumerate(folds, start=1):
        train_end = int(fold.train[-1]) + 1
        train_idx = np.arange(train_end - SLIDING_TRAIN, train_end, dtype=int)
        test_idx = fold.test
        print(
            f"S1 FREQUENCY_COMPARE FOLD id={fold_id} train_first={common[train_idx[0]].date()} "
            f"train_last={common[train_idx[-1]].date()} test_first={common[test_idx[0]].date()} "
            f"test_last={common[test_idx[-1]].date()} purge={test_idx[0] - fold.train[-1] - 1}"
        )
        y_test = yd[test_idx, TARGET_INDEX].numpy().astype(float)
        for seed in SEEDS:
            pdaily = _fit_model(MatchedScaleJointCNN(dilation=1), xd[train_idx], yd[train_idx], xd[test_idx], seed)
            p4 = _fit_model(MatchedScaleJointCNN(dilation=2), x4[train_idx], y4[train_idx], x4[test_idx], seed)
            for name, pred in (("DAILY_50", pdaily), ("INTRADAY_100", p4)):
                m = _metrics(y_test, pred)
                results[name][seed].append(m)
                print(
                    f"S1 FREQUENCY_COMPARE FOLD_METRIC id={fold_id} model={name} seed={seed} "
                    f"spearman={_fmt(m['spearman'])} mae={m['mae']:.6f} "
                    f"top20_lift={_fmt(m['lift'])} top_bottom={_fmt(m['top_bottom'])}"
                )

    for name in ("DAILY_50", "INTRADAY_100"):
        seed_sp: list[float] = []
        seed_lift: list[float] = []
        for seed in SEEDS:
            rows = results[name][seed]
            sp = float(np.nanmean([r["spearman"] for r in rows]))
            lift = float(np.nanmean([r["lift"] for r in rows]))
            seed_sp.append(sp)
            seed_lift.append(lift)
            print(
                f"S1 FREQUENCY_COMPARE SEED_SUMMARY model={name} seed={seed} folds={len(rows)} "
                f"spearman_mean={_fmt(sp)} top20_lift_mean={_fmt(lift)}"
            )
        print(
            f"S1 FREQUENCY_COMPARE CROSS_SEED model={name} "
            f"spearman_mean={_fmt(float(np.mean(seed_sp)))} spearman_std={_fmt(float(np.std(seed_sp)))} "
            f"spearman_positive={sum(v > 0 for v in seed_sp)}/{len(SEEDS)} "
            f"top20_lift_mean={_fmt(float(np.mean(seed_lift)))} top20_lift_std={_fmt(float(np.std(seed_lift)))} "
            f"top20_lift_positive={sum(v > 0 for v in seed_lift)}/{len(SEEDS)}"
        )

    for fold_id in range(1, len(folds) + 1):
        for name in ("DAILY_50", "INTRADAY_100"):
            sp = [results[name][s][fold_id - 1]["spearman"] for s in SEEDS]
            lift = [results[name][s][fold_id - 1]["lift"] for s in SEEDS]
            print(
                f"S1 FREQUENCY_COMPARE FOLD_SEED fold={fold_id} model={name} "
                f"spearman_mean={_fmt(float(np.nanmean(sp)))} spearman_std={_fmt(float(np.nanstd(sp)))} "
                f"spearman_positive={sum(v > 0 for v in sp if np.isfinite(v))}/{sum(np.isfinite(v) for v in sp)} "
                f"top20_lift_mean={_fmt(float(np.nanmean(lift)))} top20_lift_positive={sum(v > 0 for v in lift if np.isfinite(v))}/{sum(np.isfinite(v) for v in lift)}"
            )

    print("S1 FREQUENCY_COMPARE PASS")


if __name__ == "__main__":
    main()

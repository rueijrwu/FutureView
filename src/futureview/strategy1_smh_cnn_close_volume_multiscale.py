from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1_success_training import DATA_PERIOD, HORIZON, make_success_dataset
from .strategy1_smh_ridge_lmu import _make_folds

TICKER = "SMH"
LOOKBACK = 60
SCALES = (5, 10, 20, 60)
SEEDS = (20260823, 20260824, 20260825)
EPOCHS = 100
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4


def make_close_volume_multiscale_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.loc[:, ["date", "close", "volume"]].copy()
    close = out["close"].astype(float)
    volume = out["volume"].astype(float)
    for n in SCALES:
        close_sum = close.rolling(n, min_periods=n).sum()
        volume_sum = volume.rolling(n, min_periods=n).sum()
        out[f"close_sum{n}_ratio"] = close / close_sum
        out[f"volume_sum{n}_ratio"] = volume / volume_sum
    cols = [
        "date",
        *[f"close_sum{n}_ratio" for n in SCALES],
        *[f"volume_sum{n}_ratio" for n in SCALES],
    ]
    return out.loc[:, cols].replace([np.inf, -np.inf], np.nan)


class PreferenceCNN(nn.Module):
    def __init__(self, in_channels: int) -> None:
        super().__init__()
        self.branches = nn.ModuleList([
            nn.Sequential(nn.Conv1d(in_channels, 8, kernel_size=k, padding="same"), nn.GELU())
            for k in (5, 10, 20)
        ])
        self.fusion = nn.Sequential(
            nn.Conv1d(24, 16, kernel_size=3, padding="same"),
            nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Sequential(nn.Flatten(), nn.Linear(16, 8), nn.GELU(), nn.Linear(8, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = torch.cat([branch(x) for branch in self.branches], dim=1)
        return self.head(self.fusion(z)).squeeze(1)


def _make_preference_pairs(C: np.ndarray, Q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    better: list[int] = []
    worse: list[int] = []
    for i, j in itertools.combinations(range(len(C)), 2):
        if C[i] > C[j] and Q[i] < Q[j]:
            better.append(i)
            worse.append(j)
        elif C[j] > C[i] and Q[j] < Q[i]:
            better.append(j)
            worse.append(i)
    return np.asarray(better, dtype=int), np.asarray(worse, dtype=int)


def _fit_ranker(x_train: torch.Tensor, C_train: np.ndarray, Q_train: np.ndarray, seed: int) -> PreferenceCNN:
    torch.manual_seed(seed)
    np.random.seed(seed)
    better, worse = _make_preference_pairs(C_train, Q_train)
    if len(better) == 0:
        raise RuntimeError("no Pareto-dominant preference pairs in training fold")

    model = PreferenceCNN(x_train.shape[1]).cpu()
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    loss_fn = nn.Softplus()

    xb = x_train[better]
    xw = x_train[worse]
    model.train()
    for _ in range(EPOCHS):
        optimizer.zero_grad(set_to_none=True)
        sb = model(xb)
        sw = model(xw)
        loss = loss_fn(-(sb - sw)).mean()
        loss.backward()
        optimizer.step()
    return model


def _pair_accuracy(scores: np.ndarray, C: np.ndarray, Q: np.ndarray) -> tuple[int, int, float]:
    better, worse = _make_preference_pairs(C, Q)
    if len(better) == 0:
        return 0, 0, float("nan")
    correct = int(np.sum(scores[better] > scores[worse]))
    return correct, len(better), correct / len(better)


def main() -> None:
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    ds = make_success_dataset(df)

    feats = make_close_volume_multiscale_features(df).copy()
    feats["date"] = pd.to_datetime(feats["date"])
    feats = feats.set_index("date")
    raw_dates = pd.to_datetime(df["date"]).reset_index(drop=True)
    event_dates = pd.to_datetime(np.asarray(ds.dates))

    live_end = raw_dates.iloc[-1]
    live_start = live_end - pd.DateOffset(months=3)
    holdout_positions = np.flatnonzero(raw_dates.to_numpy() >= np.datetime64(live_start))
    holdout_start = int(holdout_positions[0]) if len(holdout_positions) else len(raw_dates)
    target_end = np.asarray(ds.raw_indices, dtype=int) + HORIZON - 1
    base_history_idx = np.flatnonzero(target_end < holdout_start)

    channel_cols = [f"close_sum{n}_ratio" for n in SCALES] + [f"volume_sum{n}_ratio" for n in SCALES]
    xs: list[np.ndarray] = []
    kept_ds_idx: list[int] = []
    for ds_idx in base_history_idx:
        raw_idx = int(ds.raw_indices[ds_idx])
        if raw_idx < LOOKBACK - 1:
            continue
        dates = raw_dates.iloc[raw_idx - LOOKBACK + 1 : raw_idx + 1]
        window = feats.reindex(pd.to_datetime(dates))
        if window[channel_cols].isna().any().any():
            continue
        x = window[channel_cols].to_numpy(dtype=np.float32).T
        if x.shape != (len(channel_cols), LOOKBACK):
            continue
        xs.append(x)
        kept_ds_idx.append(int(ds_idx))

    if not xs:
        raise RuntimeError("no SMH history samples survived feature construction")

    kept = np.asarray(kept_ds_idx, dtype=int)
    x = torch.from_numpy(np.stack(xs))
    raw_indices = np.asarray(ds.raw_indices, dtype=int)[kept]
    dates = event_dates[kept]
    L = np.asarray(ds.entry_lower, dtype=float)[kept]
    mu = np.asarray(ds.net_expected_return, dtype=float)[kept]
    U = np.asarray(ds.entry_upper, dtype=float)[kept]
    C = U - L
    Q = np.divide(U - mu, C, out=np.full_like(C, np.nan), where=np.abs(C) > 1e-12)
    valid = np.isfinite(mu) & np.isfinite(C) & np.isfinite(Q) & (C > 1e-12)
    x = x[valid]
    raw_indices = raw_indices[valid]
    dates = dates[valid]
    mu = mu[valid]
    C = C[valid]
    Q = Q[valid]

    folds = _make_folds(raw_indices)

    print(
        "S1 SMH_CQ_RANK DATA "
        f"ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"history_entries={len(mu)} folds={len(folds)} lookback={LOOKBACK} horizon={HORIZON} "
        f"live_holdout_start={pd.Timestamp(live_start).date()} live_holdout_end={pd.Timestamp(live_end).date()}"
    )
    print(
        "S1 SMH_CQ_RANK INPUT source=close,volume only scales=5,10,20,60 "
        "normalization=current_value/rolling_sum_N channels=8 sequence_length=60 "
        "no_open=true no_high=true no_low=true no_ma_feature=true no_return=true no_rsi=true no_macd=true no_atr=true"
    )
    print(
        "S1 SMH_CQ_RANK TARGET stage1=mu_gate stage2=pairwise_preference "
        "preference_rule=C_higher_and_Q_lower no_scalar_composite=true no_L_mu_U_regression=true"
    )

    fold_accs: list[float] = []
    for fold_id, (train, test) in enumerate(folds, start=1):
        # Gate threshold is learned from training only: keep the upper half of training mu.
        # This is intentionally simple for the first experiment and avoids peeking at test/holdout.
        mu_gate = float(np.median(mu[train]))
        train_gate = train[mu[train] >= mu_gate]
        test_gate = test[mu[test] >= mu_gate]
        print(
            f"S1 SMH_CQ_RANK FOLD id={fold_id} n_train={len(train)} n_test={len(test)} "
            f"mu_gate={mu_gate:.6f} n_train_gate={len(train_gate)} n_test_gate={len(test_gate)}"
        )
        if len(train_gate) < 4 or len(test_gate) < 2:
            print(f"S1 SMH_CQ_RANK FOLD_RESULT id={fold_id} skipped=true reason=insufficient_gated_samples")
            continue

        seed_accs = []
        for seed in SEEDS:
            model = _fit_ranker(x[train_gate], C[train_gate], Q[train_gate], seed)
            model.eval()
            with torch.no_grad():
                scores = model(x[test_gate]).cpu().numpy().astype(float)
            correct, total, acc = _pair_accuracy(scores, C[test_gate], Q[test_gate])
            seed_accs.append(acc)
            print(
                f"S1 SMH_CQ_RANK FOLD_RESULT id={fold_id} seed={seed} "
                f"pairs={total} correct={correct} pair_accuracy={acc:.6f}"
            )
        valid_accs = [a for a in seed_accs if np.isfinite(a)]
        if valid_accs:
            fold_accs.append(float(np.mean(valid_accs)))

    if fold_accs:
        print(
            f"S1 SMH_CQ_RANK SUMMARY folds_scored={len(fold_accs)} "
            f"pair_accuracy_mean={np.mean(fold_accs):.6f} "
            f"pair_accuracy_median={np.median(fold_accs):.6f} "
            f"better_than_random_folds={sum(a > 0.5 for a in fold_accs)}/{len(fold_accs)}"
        )
    else:
        print("S1 SMH_CQ_RANK SUMMARY folds_scored=0")
    print("S1 SMH_CQ_RANK COMPLETE")


if __name__ == "__main__":
    main()

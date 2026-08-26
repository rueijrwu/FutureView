from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1_success_training import DATA_PERIOD, HORIZON, make_success_dataset

TICKER = "SMH"
LOOKBACK = 60
SCALES = (5, 10, 20, 60)
SEEDS = (20260823, 20260824, 20260825)
EPOCHS = 100
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
N_FOLDS = 4
PURGE_DAYS = HORIZON
MIN_TRAIN_SAMPLES = 40
MIN_TEST_SAMPLES = 10


def make_close_volume_multiscale_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.loc[:, ["date", "close", "volume"]].copy()
    close = out["close"].astype(float)
    volume = out["volume"].astype(float)
    for n in SCALES:
        close_sum = close.rolling(n, min_periods=n).sum()
        volume_sum = volume.rolling(n, min_periods=n).sum()
        out[f"close_sum{n}_ratio"] = close / close_sum
        out[f"volume_sum{n}_ratio"] = volume / volume_sum
    cols = ["date", *[f"close_sum{n}_ratio" for n in SCALES], *[f"volume_sum{n}_ratio" for n in SCALES]]
    return out.loc[:, cols].replace([np.inf, -np.inf], np.nan)


def _make_cq_folds(raw_indices: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding chronological OOS folds with an explicit horizon purge.

    This splitter belongs to the C/Q ranking experiment and intentionally has
    no dependency on the legacy Ridge experiment. Fold sizes are derived from
    the samples that actually survive the 60-day multiscale representation.
    """
    raw_indices = np.asarray(raw_indices, dtype=int)
    order = np.argsort(raw_indices)
    if len(order) < MIN_TRAIN_SAMPLES + MIN_TEST_SAMPLES:
        raise RuntimeError(
            f"insufficient C/Q samples for chronological folds: n={len(order)} "
            f"need>={MIN_TRAIN_SAMPLES + MIN_TEST_SAMPLES}"
        )

    remaining = len(order) - MIN_TRAIN_SAMPLES
    test_size = max(MIN_TEST_SAMPLES, remaining // N_FOLDS)
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    test_start = MIN_TRAIN_SAMPLES
    while test_start < len(order) and len(folds) < N_FOLDS:
        test_end = min(len(order), test_start + test_size)
        test = order[test_start:test_end]
        if len(test) < MIN_TEST_SAMPLES:
            break
        first_test_raw = int(raw_indices[test[0]])
        train_candidates = order[:test_start]
        train = train_candidates[raw_indices[train_candidates] + PURGE_DAYS < first_test_raw]
        if len(train) >= MIN_TRAIN_SAMPLES:
            folds.append((train, test))
        test_start = test_end

    if not folds:
        raise RuntimeError("no complete purged chronological C/Q ranking folds")
    return folds


class PreferenceCNN(nn.Module):
    def __init__(self, in_channels: int) -> None:
        super().__init__()
        self.branches = nn.ModuleList([
            nn.Sequential(nn.Conv1d(in_channels, 8, kernel_size=k, padding="same"), nn.GELU())
            for k in (5, 10, 20)
        ])
        self.fusion = nn.Sequential(nn.Conv1d(24, 16, kernel_size=3, padding="same"), nn.GELU(), nn.AdaptiveAvgPool1d(1))
        self.head = nn.Sequential(nn.Flatten(), nn.Linear(16, 8), nn.GELU(), nn.Linear(8, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = torch.cat([branch(x) for branch in self.branches], dim=1)
        return self.head(self.fusion(z)).squeeze(1)


def _make_preference_pairs(C: np.ndarray, Q: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    better: list[int] = []
    worse: list[int] = []
    for i, j in itertools.combinations(range(len(C)), 2):
        if C[i] > C[j] and Q[i] < Q[j]:
            better.append(i); worse.append(j)
        elif C[j] > C[i] and Q[j] < Q[i]:
            better.append(j); worse.append(i)
    return np.asarray(better, dtype=int), np.asarray(worse, dtype=int)


def _fit_ranker(x_train: torch.Tensor, C_train: np.ndarray, Q_train: np.ndarray, seed: int) -> PreferenceCNN:
    torch.manual_seed(seed); np.random.seed(seed)
    better, worse = _make_preference_pairs(C_train, Q_train)
    if len(better) == 0:
        raise RuntimeError("no Pareto-dominant preference pairs in training fold")
    model = PreferenceCNN(x_train.shape[1]).cpu()
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    loss_fn = nn.Softplus()
    xb, xw = x_train[better], x_train[worse]
    model.train()
    for _ in range(EPOCHS):
        optimizer.zero_grad(set_to_none=True)
        loss = loss_fn(-(model(xb) - model(xw))).mean()
        loss.backward(); optimizer.step()
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
    feats["date"] = pd.to_datetime(feats["date"]); feats = feats.set_index("date")
    raw_dates = pd.to_datetime(df["date"]).reset_index(drop=True)
    event_dates = pd.to_datetime(np.asarray(ds.dates))
    live_end = raw_dates.iloc[-1]; live_start = live_end - pd.DateOffset(months=3)
    holdout_positions = np.flatnonzero(raw_dates.to_numpy() >= np.datetime64(live_start))
    holdout_start = int(holdout_positions[0]) if len(holdout_positions) else len(raw_dates)
    target_end = np.asarray(ds.raw_indices, dtype=int) + HORIZON - 1
    base_history_idx = np.flatnonzero(target_end < holdout_start)
    channel_cols = [f"close_sum{n}_ratio" for n in SCALES] + [f"volume_sum{n}_ratio" for n in SCALES]
    xs, kept_ds_idx = [], []
    for ds_idx in base_history_idx:
        raw_idx = int(ds.raw_indices[ds_idx])
        if raw_idx < LOOKBACK - 1: continue
        dates0 = raw_dates.iloc[raw_idx - LOOKBACK + 1:raw_idx + 1]
        window = feats.reindex(pd.to_datetime(dates0))
        if window[channel_cols].isna().any().any(): continue
        xx = window[channel_cols].to_numpy(dtype=np.float32).T
        if xx.shape != (len(channel_cols), LOOKBACK): continue
        xs.append(xx); kept_ds_idx.append(int(ds_idx))
    if not xs: raise RuntimeError("no SMH history samples survived feature construction")
    kept = np.asarray(kept_ds_idx, dtype=int); x = torch.from_numpy(np.stack(xs))
    raw_indices = np.asarray(ds.raw_indices, dtype=int)[kept]; dates = event_dates[kept]
    L = np.asarray(ds.entry_lower, dtype=float)[kept]
    mu = np.asarray(ds.net_expected_return, dtype=float)[kept]
    U = np.asarray(ds.entry_upper, dtype=float)[kept]
    C = U - L
    Q = np.divide(U - mu, C, out=np.full_like(C, np.nan), where=np.abs(C) > 1e-12)
    valid = np.isfinite(mu) & np.isfinite(C) & np.isfinite(Q) & (C > 1e-12)
    x, raw_indices, dates, mu, C, Q = x[valid], raw_indices[valid], dates[valid], mu[valid], C[valid], Q[valid]

    folds = _make_cq_folds(raw_indices)
    print(f"S1 SMH_CQ_RANK DATA ticker={TICKER} period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} history_entries={len(mu)} folds={len(folds)} lookback={LOOKBACK} horizon={HORIZON} live_holdout_start={pd.Timestamp(live_start).date()} live_holdout_end={pd.Timestamp(live_end).date()}")
    print("S1 SMH_CQ_RANK INPUT source=close,volume only scales=5,10,20,60 normalization=current_value/rolling_sum_N channels=8 sequence_length=60 no_open=true no_high=true no_low=true no_ma_feature=true no_return=true no_rsi=true no_macd=true no_atr=true")
    print("S1 SMH_CQ_RANK TARGET stage1=mu_gate stage2=pairwise_preference preference_rule=C_higher_and_Q_lower no_scalar_composite=true no_L_mu_U_regression=true")
    print(f"S1 SMH_CQ_RANK SPLIT type=expanding_chronological_purged purge_days={PURGE_DAYS} min_train={MIN_TRAIN_SAMPLES} min_test={MIN_TEST_SAMPLES} ridge_dependency=false")

    fold_accs = []
    for fold_id, (train, test) in enumerate(folds, start=1):
        mu_gate = float(np.median(mu[train]))
        train_gate = train[mu[train] >= mu_gate]; test_gate = test[mu[test] >= mu_gate]
        print(f"S1 SMH_CQ_RANK FOLD id={fold_id} n_train={len(train)} n_test={len(test)} mu_gate={mu_gate:.6f} n_train_gate={len(train_gate)} n_test_gate={len(test_gate)}")
        if len(train_gate) < 4 or len(test_gate) < 2:
            print(f"S1 SMH_CQ_RANK FOLD_RESULT id={fold_id} skipped=true reason=insufficient_gated_samples"); continue
        seed_accs = []
        for seed in SEEDS:
            model = _fit_ranker(x[train_gate], C[train_gate], Q[train_gate], seed); model.eval()
            with torch.no_grad(): scores = model(x[test_gate]).cpu().numpy().astype(float)
            correct, total, acc = _pair_accuracy(scores, C[test_gate], Q[test_gate]); seed_accs.append(acc)
            print(f"S1 SMH_CQ_RANK FOLD_RESULT id={fold_id} seed={seed} pairs={total} correct={correct} pair_accuracy={acc:.6f}")
        valid_accs = [a for a in seed_accs if np.isfinite(a)]
        if valid_accs: fold_accs.append(float(np.mean(valid_accs)))
    if fold_accs:
        print(f"S1 SMH_CQ_RANK SUMMARY folds_scored={len(fold_accs)} pair_accuracy_mean={np.mean(fold_accs):.6f} pair_accuracy_median={np.median(fold_accs):.6f} better_than_random_folds={sum(a > 0.5 for a in fold_accs)}/{len(fold_accs)}")
    else: print("S1 SMH_CQ_RANK SUMMARY folds_scored=0")
    print("S1 SMH_CQ_RANK COMPLETE")


if __name__ == "__main__": main()

from __future__ import annotations

import gc
import os
import random

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_profitability_io import build_path_table, build_profitability_io

TICKER = os.environ.get("FUTUREVIEW_TICKER", "SMH")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
PILOT_WINDOWS = tuple(
    int(x.strip())
    for x in os.environ.get("FUTUREVIEW_AE_WINDOWS", "20,30,40").split(",")
    if x.strip()
)
SEED = int(os.environ.get("FUTUREVIEW_AE_SEED", "7"))
EPOCHS = int(os.environ.get("FUTUREVIEW_AE_EPOCHS", "30"))
LATENT_DIM = int(os.environ.get("FUTUREVIEW_AE_LATENT", "8"))
N_BINS = int(os.environ.get("FUTUREVIEW_AE_BINS", "41"))
BATCH_SIZE = int(os.environ.get("FUTUREVIEW_AE_BATCH", "16"))
LEARNING_RATE = float(os.environ.get("FUTUREVIEW_AE_LR", "0.001"))
OUTPUT = os.environ.get("FUTUREVIEW_AE_OUTPUT", "strategy1-profitability-autoencoder.csv")


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def _histogram(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    if len(values) == 0:
        return np.zeros(len(edges) - 1, dtype=np.float32)
    idx = np.searchsorted(edges, values, side="right") - 1
    idx = np.clip(idx, 0, len(edges) - 2)
    return np.bincount(idx, minlength=len(edges) - 1).astype(np.float32)


class WindowDataset(Dataset):
    def __init__(
        self,
        io,
        indices: np.ndarray,
        edges: np.ndarray,
        profit_mean: float,
        profit_std: float,
    ) -> None:
        self.io = io
        self.indices = np.asarray(indices, dtype=np.int64)
        self.edges = edges
        self.profit_mean = float(profit_mean)
        self.profit_std = float(max(profit_std, 1e-8))

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, item: int):
        i = int(self.indices[item])
        seq = self.io.sequence[i]  # [category, calendar, slot, campaign]
        profit = self.io.profit[i]
        mask = self.io.mask[i].astype(np.float32)

        # Stable channel organization: category x slot; spatial axes are
        # regime-calendar time x campaign-execution time.
        seq_ch = np.transpose(seq, (0, 2, 1, 3)).reshape(-1, seq.shape[1], seq.shape[3])
        mask_ch = np.transpose(mask, (0, 2, 1)).reshape(-1, mask.shape[1])
        profit_ch = np.transpose(profit, (0, 2, 1)).reshape(-1, profit.shape[1])
        profit_ch = ((profit_ch - self.profit_mean) / self.profit_std) * mask_ch

        campaign = seq.shape[3]
        profit_map = np.repeat(profit_ch[:, :, None], campaign, axis=2)
        mask_map = np.repeat(mask_ch[:, :, None], campaign, axis=2)
        x = np.concatenate([seq_ch, profit_map, mask_map], axis=0).astype(np.float32)

        valid_profit = profit[mask.astype(bool)]
        y = _histogram(valid_profit.astype(np.float64), self.edges)
        return torch.from_numpy(x), torch.from_numpy(y), i


class ProfitabilityAutoencoder(nn.Module):
    def __init__(self, in_channels: int, latent_dim: int, n_bins: int) -> None:
        super().__init__()
        self.encoder_conv = nn.Sequential(
            nn.Conv2d(in_channels, 32, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv2d(32, 32, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.Conv2d(32, 16, kernel_size=3, stride=2, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((1, 1)),
        )
        self.encoder_fc = nn.Linear(16, latent_dim)
        self.decoder = nn.Sequential(
            nn.Linear(latent_dim, 32),
            nn.ReLU(),
            nn.Linear(32, n_bins),
            nn.Softplus(),
        )

    def encode(self, x: torch.Tensor) -> torch.Tensor:
        h = self.encoder_conv(x).flatten(1)
        return self.encoder_fc(h)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        z = self.encode(x)
        return self.decoder(z), z


def _collect_latent(model: nn.Module, loader: DataLoader) -> tuple[np.ndarray, np.ndarray]:
    zs: list[np.ndarray] = []
    ids: list[np.ndarray] = []
    model.eval()
    with torch.no_grad():
        for x, _, idx in loader:
            z = model.encode(x)
            zs.append(z.cpu().numpy())
            ids.append(idx.cpu().numpy())
    return np.concatenate(zs), np.concatenate(ids)


def _auc(scores: np.ndarray, labels: np.ndarray) -> float:
    pos = scores[labels == 1]
    neg = scores[labels == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    cmp = pos[:, None] - neg[None, :]
    return float(np.mean((cmp > 0).astype(np.float64) + 0.5 * (cmp == 0)))


def _probe(
    z_train: np.ndarray,
    y_train: np.ndarray,
    z_test: np.ndarray,
    y_test: np.ndarray,
) -> tuple[float, str]:
    if len(np.unique(y_train)) < 2 or len(np.unique(y_test)) < 2:
        return float("nan"), "insufficient_classes"

    _seed_everything(SEED)
    probe = nn.Linear(z_train.shape[1], 1)
    opt = torch.optim.Adam(probe.parameters(), lr=0.02)
    loss_fn = nn.BCEWithLogitsLoss()
    xtr = torch.from_numpy(z_train.astype(np.float32))
    ytr = torch.from_numpy(y_train.astype(np.float32))[:, None]
    for _ in range(300):
        opt.zero_grad()
        logits = probe(xtr)
        loss = loss_fn(logits, ytr)
        loss.backward()
        opt.step()

    with torch.no_grad():
        scores = torch.sigmoid(probe(torch.from_numpy(z_test.astype(np.float32)))).squeeze(1).numpy()
    return _auc(scores, y_test), "ok"


def _anchor_labels(lower: np.ndarray, upper: np.ndarray, indices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    labels: list[int] = []
    keep: list[int] = []
    for i in indices:
        if np.isfinite(upper[i]) and upper[i] < 0:
            keep.append(int(i))
            labels.append(0)
        elif np.isfinite(lower[i]) and lower[i] > 0:
            keep.append(int(i))
            labels.append(1)
    return np.asarray(keep, dtype=np.int64), np.asarray(labels, dtype=np.int64)


def _fit_one(events, path_table, window: int) -> dict[str, object]:
    _seed_everything(SEED)
    io = build_profitability_io(events, path_table, window, stride=1)
    n = len(io.window_start)
    split = int(np.floor(0.70 * n))
    train_stop = max(1, split - window)  # purge shared calendar entries across the boundary
    train_idx = np.arange(0, train_stop, dtype=np.int64)
    test_idx = np.arange(split, n, dtype=np.int64)

    train_profit = io.profit[train_idx]
    train_mask = io.mask[train_idx].astype(bool)
    train_values = train_profit[train_mask].astype(np.float64)
    if len(train_values) == 0:
        raise RuntimeError(f"W={window}: no training profits")
    pmin = float(train_values.min())
    pmax = float(train_values.max())
    if not pmax > pmin:
        raise RuntimeError(f"W={window}: degenerate training profit range")
    edges = np.linspace(pmin, pmax, N_BINS + 1, dtype=np.float64)
    profit_mean = float(train_values.mean())
    profit_std = float(train_values.std(ddof=0))

    train_ds = WindowDataset(io, train_idx, edges, profit_mean, profit_std)
    test_ds = WindowDataset(io, test_idx, edges, profit_mean, profit_std)
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=0)
    train_eval_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)
    test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

    x0, _, _ = train_ds[0]
    model = ProfitabilityAutoencoder(x0.shape[0], LATENT_DIM, N_BINS)
    opt = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    loss_fn = nn.MSELoss()

    last_train_loss = float("nan")
    for _ in range(EPOCHS):
        model.train()
        total = 0.0
        count = 0
        for x, y, _ in train_loader:
            opt.zero_grad()
            pred, _ = model(x)
            loss = loss_fn(pred, y)
            loss.backward()
            opt.step()
            total += float(loss.detach()) * len(x)
            count += len(x)
        last_train_loss = total / max(count, 1)

    model.eval()
    total = 0.0
    count = 0
    with torch.no_grad():
        for x, y, _ in test_loader:
            pred, _ = model(x)
            loss = loss_fn(pred, y)
            total += float(loss) * len(x)
            count += len(x)
    test_loss = total / max(count, 1)

    z_train_all, id_train_all = _collect_latent(model, train_eval_loader)
    z_test_all, id_test_all = _collect_latent(model, test_loader)
    train_pos = {int(v): j for j, v in enumerate(id_train_all)}
    test_pos = {int(v): j for j, v in enumerate(id_test_all)}

    anchor_train_idx, anchor_train_y = _anchor_labels(io.lower, io.upper, train_idx)
    anchor_test_idx, anchor_test_y = _anchor_labels(io.lower, io.upper, test_idx)
    z_anchor_train = np.stack([z_train_all[train_pos[int(i)]] for i in anchor_train_idx]) if len(anchor_train_idx) else np.empty((0, LATENT_DIM))
    z_anchor_test = np.stack([z_test_all[test_pos[int(i)]] for i in anchor_test_idx]) if len(anchor_test_idx) else np.empty((0, LATENT_DIM))

    probe_auc, probe_status = _probe(z_anchor_train, anchor_train_y, z_anchor_test, anchor_test_y)

    result = {
        "window": window,
        "windows": n,
        "train_windows": len(train_idx),
        "test_windows": len(test_idx),
        "max_paths_per_cell": io.max_paths_per_cell,
        "train_loss": last_train_loss,
        "test_loss": test_loss,
        "train_anchor_bad": int(np.sum(anchor_train_y == 0)),
        "train_anchor_good": int(np.sum(anchor_train_y == 1)),
        "test_anchor_bad": int(np.sum(anchor_test_y == 0)),
        "test_anchor_good": int(np.sum(anchor_test_y == 1)),
        "probe_auc": probe_auc,
        "probe_status": probe_status,
        "profit_min_train": pmin,
        "profit_max_train": pmax,
        "profit_mean_train": profit_mean,
        "profit_std_train": profit_std,
    }

    del model, train_loader, test_loader, train_eval_loader, train_ds, test_ds, io
    gc.collect()
    return result


def main() -> None:
    print(
        "S1 PROFITABILITY_AE CONFIG "
        f"windows={PILOT_WINDOWS} epochs={EPOCHS} latent={LATENT_DIM} bins={N_BINS} "
        f"batch={BATCH_SIZE} lr={LEARNING_RATE} seed={SEED} research_frozen=false"
    )
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    path_table = build_path_table(events)
    print(
        f"S1 PROFITABILITY_AE DATA ticker={TICKER} rows={audit.rows} "
        f"paths={len(path_table)} entries={path_table['entry_index'].nunique()}"
    )

    results: list[dict[str, object]] = []
    for window in PILOT_WINDOWS:
        result = _fit_one(events, path_table, window)
        results.append(result)
        print(
            "S1 PROFITABILITY_AE RESULT "
            f"W={window} train_loss={result['train_loss']:.6f} test_loss={result['test_loss']:.6f} "
            f"train_bad={result['train_anchor_bad']} train_good={result['train_anchor_good']} "
            f"test_bad={result['test_anchor_bad']} test_good={result['test_anchor_good']} "
            f"probe_auc={result['probe_auc']} probe_status={result['probe_status']}"
        )

    pd.DataFrame(results).to_csv(OUTPUT, index=False)
    print(f"S1 PROFITABILITY_AE COMPLETE output={OUTPUT}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
import random
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_profitability_io import HORIZON, N_CATEGORIES, build_path_table

TICKER = os.environ.get("FUTUREVIEW_TICKER", "SMH")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
WINDOWS = tuple(
    int(x.strip())
    for x in os.environ.get("FUTUREVIEW_AE_WINDOWS", "20,30,60").split(",")
    if x.strip()
)
LATENT_DIM = int(os.environ.get("FUTUREVIEW_AE_LATENT", "1"))
HIST_BINS = int(os.environ.get("FUTUREVIEW_AE_BINS", "41"))
EPOCHS = int(os.environ.get("FUTUREVIEW_AE_EPOCHS", "5"))
BATCH_SIZE = int(os.environ.get("FUTUREVIEW_AE_BATCH", "16"))
SEED = int(os.environ.get("FUTUREVIEW_AE_SEED", "7"))


@dataclass(frozen=True)
class WindowSpec:
    start: int
    end: int
    path_count: int
    lower: float
    upper: float
    mean_return: float
    win_rate: float


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def _window_specs(path_table, window: int) -> list[WindowSpec]:
    returns_by_entry = {
        int(entry): group["campaign_return"].to_numpy(dtype=np.float64)
        for entry, group in path_table.groupby("entry_index", sort=False)
    }
    last_entry = int(path_table["entry_index"].max())
    specs: list[WindowSpec] = []
    for start in range(0, last_entry - window + 2):
        pieces = [returns_by_entry[i] for i in range(start, start + window) if i in returns_by_entry]
        if not pieces:
            continue
        r = np.concatenate(pieces)
        specs.append(WindowSpec(
            start=start,
            end=start + window - 1,
            path_count=int(len(r)),
            lower=float(r.min()),
            upper=float(r.max()),
            mean_return=float(r.mean()),
            win_rate=float(np.mean(r > 0.0)),
        ))
    return specs


class ProfitabilityWindowDataset(Dataset):
    def __init__(self, path_table, specs: list[WindowSpec], window: int, edges: np.ndarray):
        self.specs = specs
        self.window = int(window)
        self.edges = np.asarray(edges, dtype=np.float64)
        self.by_entry_category: dict[tuple[int, int], list[tuple[np.ndarray, float]]] = {}
        max_slot = 1
        for (entry, category), group in path_table.groupby(["entry_index", "category"], sort=False):
            rows: list[tuple[np.ndarray, float]] = []
            for row in group.itertuples(index=False):
                rows.append((np.asarray(row.sequence, dtype=np.float32), float(row.campaign_return)))
            self.by_entry_category[(int(entry), int(category))] = rows
            max_slot = max(max_slot, len(rows))
        self.max_slot = int(max_slot)

    def __len__(self) -> int:
        return len(self.specs)

    def __getitem__(self, idx: int):
        spec = self.specs[idx]
        seq = np.zeros((N_CATEGORIES, self.window, self.max_slot, HORIZON), dtype=np.float32)
        profit = np.zeros((N_CATEGORIES, self.window, self.max_slot), dtype=np.float32)
        mask = np.zeros((N_CATEGORIES, self.window, self.max_slot), dtype=np.float32)
        returns: list[float] = []
        for cal, entry in enumerate(range(spec.start, spec.end + 1)):
            for category in range(N_CATEGORIES):
                rows = self.by_entry_category.get((entry, category), ())
                for slot, (s, r) in enumerate(rows):
                    seq[category, cal, slot] = s
                    profit[category, cal, slot] = r
                    mask[category, cal, slot] = 1.0
                    returns.append(r)
        hist, _ = np.histogram(np.asarray(returns, dtype=np.float64), bins=self.edges)
        hist = hist.astype(np.float32)
        total = float(hist.sum())
        if total > 0.0:
            hist /= total
        return (
            torch.from_numpy(seq), torch.from_numpy(profit), torch.from_numpy(mask),
            torch.from_numpy(hist),
            torch.tensor(spec.lower, dtype=torch.float32),
            torch.tensor(spec.upper, dtype=torch.float32),
            torch.tensor(spec.path_count, dtype=torch.float32),
            torch.tensor(spec.mean_return, dtype=torch.float32),
            torch.tensor(spec.win_rate, dtype=torch.float32),
        )


class ProfitabilityAutoencoder(nn.Module):
    def __init__(self, latent_dim: int, hist_bins: int):
        super().__init__()
        self.path_cnn = nn.Sequential(
            nn.Conv1d(1, 8, kernel_size=5, padding=2), nn.ReLU(),
            nn.Conv1d(8, 8, kernel_size=5, padding=2), nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.calendar_cnn = nn.Sequential(
            nn.Conv1d(N_CATEGORIES * 9, 32, kernel_size=5, padding=2), nn.ReLU(),
            nn.Conv1d(32, 16, kernel_size=5, padding=2), nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.to_latent = nn.Linear(16, latent_dim)
        self.decoder = nn.Sequential(
            nn.Linear(latent_dim, 32), nn.ReLU(), nn.Linear(32, hist_bins), nn.Softplus()
        )

    def encode(self, sequence: torch.Tensor, profit: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        b, c, w, s, h = sequence.shape
        path = sequence.reshape(b * c * w * s, 1, h)
        emb = self.path_cnn(path).squeeze(-1).reshape(b, c, w, s, 8)
        m = mask.unsqueeze(-1)
        count = mask.sum(dim=3, keepdim=True)
        denom = count.clamp_min(1.0)
        emb_mean = (emb * m).sum(dim=3) / denom
        profit_mean = (profit * mask).sum(dim=3, keepdim=True) / denom
        cell = torch.cat([emb_mean, profit_mean], dim=-1)
        x = cell.permute(0, 1, 3, 2).reshape(b, c * 9, w)
        return self.to_latent(self.calendar_cnn(x).squeeze(-1))

    def forward(self, sequence: torch.Tensor, profit: torch.Tensor, mask: torch.Tensor):
        z = self.encode(sequence, profit, mask)
        return self.decoder(z), z


def _chronological_split(specs: list[WindowSpec], window: int):
    max_end = max(s.end for s in specs)
    cutoff = int(round(0.70 * max_end))
    train = [s for s in specs if s.end < cutoff]
    test = [s for s in specs if s.start >= cutoff]
    if len(train) < 20 or len(test) < 20:
        raise RuntimeError(f"insufficient split W={window} train={len(train)} test={len(test)}")
    return train, test, cutoff


def _centroid_distance(z: np.ndarray, values: np.ndarray) -> tuple[float, float, float, int, int]:
    p10, p90 = np.quantile(values, [0.10, 0.90])
    low, high = values <= p10, values >= p90
    return float(np.linalg.norm(z[low].mean(0) - z[high].mean(0))), float(p10), float(p90), int(low.sum()), int(high.sum())


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    if len(a) < 2 or np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def _latent_audit(window: int, z: np.ndarray, stats: dict[str, np.ndarray]) -> None:
    for name, values in stats.items():
        corrs = np.asarray([_corr(z[:, d], values) for d in range(z.shape[1])], dtype=np.float64)
        finite = np.isfinite(corrs)
        if not finite.any():
            print(f"S1 PROFITABILITY_AE INTERP W={window} stat={name} max_abs_corr=nan dim=-1 corr=nan")
            continue
        masked = np.where(finite, np.abs(corrs), -1.0)
        dim = int(np.argmax(masked))
        vector = ",".join(f"{x:.3f}" if np.isfinite(x) else "nan" for x in corrs)
        print(f"S1 PROFITABILITY_AE INTERP W={window} stat={name} max_abs_corr={abs(corrs[dim]):.6f} dim={dim} corr={corrs[dim]:.6f} vector={vector}")


def _run_window(path_table, window: int, device: torch.device) -> None:
    specs = _window_specs(path_table, window)
    train_specs, test_specs, cutoff = _chronological_split(specs, window)
    all_returns = path_table["campaign_return"].to_numpy(dtype=np.float64)
    pad = max(1e-6, 0.01 * float(all_returns.max() - all_returns.min()))
    edges = np.linspace(float(all_returns.min() - pad), float(all_returns.max() + pad), HIST_BINS + 1)
    train_ds = ProfitabilityWindowDataset(path_table, train_specs, window, edges)
    test_ds = ProfitabilityWindowDataset(path_table, test_specs, window, edges)
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=0)
    test_loader = DataLoader(test_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

    model = ProfitabilityAutoencoder(LATENT_DIM, HIST_BINS).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.SmoothL1Loss()
    first_loss = last_loss = None
    for _ in range(EPOCHS):
        model.train(); total = 0.0; n = 0
        for seq, profit, mask, target, *_ in train_loader:
            seq, profit, mask, target = seq.to(device), profit.to(device), mask.to(device), target.to(device)
            pred, _ = model(seq, profit, mask)
            loss = loss_fn(pred, target)
            opt.zero_grad(set_to_none=True); loss.backward(); opt.step()
            total += float(loss.detach()) * len(seq); n += len(seq)
        epoch_loss = total / max(n, 1)
        if first_loss is None:
            first_loss = epoch_loss
        last_loss = epoch_loss

    model.eval(); test_total = 0.0; test_n = 0
    z_all=[]; l_all=[]; u_all=[]; n_all=[]; mu_all=[]; wr_all=[]
    with torch.no_grad():
        for seq, profit, mask, target, lower, upper, path_count, mean_return, win_rate in test_loader:
            seq, profit, mask, target = seq.to(device), profit.to(device), mask.to(device), target.to(device)
            pred, z = model(seq, profit, mask)
            loss = loss_fn(pred, target)
            test_total += float(loss) * len(seq); test_n += len(seq)
            z_all.append(z.cpu().numpy()); l_all.append(lower.numpy()); u_all.append(upper.numpy())
            n_all.append(path_count.numpy()); mu_all.append(mean_return.numpy()); wr_all.append(win_rate.numpy())

    z=np.concatenate(z_all); lower=np.concatenate(l_all); upper=np.concatenate(u_all)
    path_count=np.concatenate(n_all); mean_return=np.concatenate(mu_all); win_rate=np.concatenate(wr_all)
    l_dist,l10,l90,l_low_n,l_high_n=_centroid_distance(z,lower)
    u_dist,u10,u90,u_low_n,u_high_n=_centroid_distance(z,upper)
    latent_scale=float(np.mean(np.std(z,axis=0)))

    print(f"S1 PROFITABILITY_AE DATA W={window} train={len(train_ds)} test={len(test_ds)} cutoff={cutoff} max_slot={train_ds.max_slot} bins={HIST_BINS} latent={LATENT_DIM} target_unit_mass=true explicit_count_input=false")
    print(f"S1 PROFITABILITY_AE TRAIN W={window} first_loss={first_loss:.6f} last_loss={last_loss:.6f} epochs={EPOCHS}")
    print(f"S1 PROFITABILITY_AE TEST W={window} loss={test_total/max(test_n,1):.6f} path_count_median={np.median(path_count):.1f} latent_scale={latent_scale:.6f}")
    print(f"S1 PROFITABILITY_AE POSTHOC_L W={window} p10={l10:.8f} p90={l90:.8f} centroid_distance={l_dist:.6f} low_n={l_low_n} high_n={l_high_n} labels_used_in_training=false")
    print(f"S1 PROFITABILITY_AE POSTHOC_U W={window} p10={u10:.8f} p90={u90:.8f} centroid_distance={u_dist:.6f} low_n={u_low_n} high_n={u_high_n} labels_used_in_training=false")
    _latent_audit(window, z, {"L":lower,"U":upper,"N":path_count,"mu":mean_return,"win_rate":win_rate})


def main() -> None:
    _seed_everything(SEED)
    device=torch.device("cuda" if torch.cuda.is_available() else "cpu")
    df=download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit=validate_daily_ohlcv(df, minimum_rows=1000)
    events=add_strategy1_events(df).reset_index(drop=True)
    path_table=build_path_table(events)
    print(f"S1 PROFITABILITY_AE START ticker={TICKER} rows={audit.rows} paths={len(path_table)} windows={','.join(map(str,WINDOWS))} device={device} pilot=true target_unit_mass=true explicit_count_input=false")
    for window in WINDOWS:
        _run_window(path_table, window, device)
    print("S1 PROFITABILITY_AE COMPLETE pilot=true research_hyperparameters_frozen=false")


if __name__ == "__main__":
    main()

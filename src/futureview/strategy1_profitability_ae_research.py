from __future__ import annotations

import os

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_cq_data import HORIZON
from .strategy1_profitability_io import build_path_table

TICKER = os.environ.get("FUTUREVIEW_TICKER", "SMH")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
WINDOW = int(os.environ.get("FUTUREVIEW_AE_WINDOW", "60"))
STRIDE = int(os.environ.get("FUTUREVIEW_AE_STRIDE", "5"))
EPOCHS = int(os.environ.get("FUTUREVIEW_AE_EPOCHS", "80"))
SEED = int(os.environ.get("FUTUREVIEW_AE_SEED", "7"))


class AE(nn.Module):
    def __init__(self, width: int, latent: int):
        super().__init__()
        hidden = max(8, width * 2)
        self.encoder = nn.Sequential(nn.Linear(width, hidden), nn.Tanh(), nn.Linear(hidden, latent))
        self.decoder = nn.Sequential(nn.Linear(latent, hidden), nn.Tanh(), nn.Linear(hidden, width))

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        z = self.encoder(x)
        return self.decoder(z), z


def _random_baseline(close: np.ndarray, start: int, end: int, rng: np.random.Generator) -> tuple[float, float, float, float]:
    valid = np.arange(start, min(end + 1, len(close) - HORIZON + 1), dtype=int)
    if len(valid) == 0:
        return (np.nan,) * 4
    draws = rng.choice(valid, size=256, replace=True)
    rets = close[draws + HORIZON - 1] / close[draws] - 1.0
    q10, q50, q90 = np.quantile(rets, [0.10, 0.50, 0.90])
    return float(np.mean(rets)), float(q10), float(q50), float(q90)


def build_descriptors(df: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    close = df["close"].to_numpy(dtype=float)
    max_entry = int(paths["entry_index"].max())
    rng = np.random.default_rng(SEED)
    rows: list[dict[str, float | int]] = []
    for start in range(0, max_entry - WINDOW + 2, STRIDE):
        end = start + WINDOW - 1
        r = paths.loc[paths["entry_index"].between(start, end), "campaign_return"].to_numpy(dtype=float)
        if len(r) < 8:
            continue
        L = float(np.min(r)); U = float(np.max(r)); C = U - L
        if not np.isfinite(C) or C <= 1e-12:
            continue
        q = (U - r) / C
        b_hold = float(close[end] / close[start] - 1.0) if close[start] > 0 else np.nan
        b_mean, b10, b50, b90 = _random_baseline(close, start, end, rng)
        if not np.isfinite([b_hold, b_mean, b10, b50, b90]).all():
            continue
        rows.append({
            "start": start, "end": end,
            "L": L, "U": U, "C": C,
            "B_hold": b_hold, "B_random_mean": b_mean,
            "B_random_q10": b10, "B_random_q50": b50, "B_random_q90": b90,
            "Q_q10": float(np.quantile(q, .10)), "Q_q25": float(np.quantile(q, .25)),
            "Q_q50": float(np.quantile(q, .50)), "Q_q75": float(np.quantile(q, .75)),
            "Q_q90": float(np.quantile(q, .90)),
            # Post-hoc only: excluded from AE input.
            "profit_mean": float(np.mean(r)), "profit_median": float(np.median(r)),
            "win_rate": float(np.mean(r > 0.0)), "path_count": int(len(r)),
        })
    out = pd.DataFrame(rows)
    if len(out) < 30:
        raise RuntimeError(f"too few valid historical windows: {len(out)}")
    return out


def _train_one(x: np.ndarray, latent: int, train_end: int, val_end: int) -> tuple[AE, float, float]:
    torch.manual_seed(SEED + latent)
    model = AE(x.shape[1], latent)
    opt = torch.optim.Adam(model.parameters(), lr=1e-2)
    loss_fn = nn.MSELoss()
    xt = torch.tensor(x, dtype=torch.float32)
    for _ in range(EPOCHS):
        model.train(); opt.zero_grad()
        rec, _ = model(xt[:train_end]); loss = loss_fn(rec, xt[:train_end])
        loss.backward(); opt.step()
    model.eval()
    with torch.no_grad():
        val = float(loss_fn(model(xt[train_end:val_end])[0], xt[train_end:val_end]).item())
        test = float(loss_fn(model(xt[val_end:])[0], xt[val_end:]).item())
    return model, val, test


def _audit_set(frame: pd.DataFrame, features: list[str], label: str) -> None:
    raw = frame[features].to_numpy(dtype=np.float64)
    n = len(raw); train_end = max(10, int(n * .70)); val_end = max(train_end + 5, int(n * .85))
    mu = raw[:train_end].mean(axis=0); sd = raw[:train_end].std(axis=0); sd[sd < 1e-8] = 1.0
    x = (raw - mu) / sd
    max_dim = min(6, len(features) - 1)
    trials = []
    for d in range(1, max_dim + 1):
        model, val, test = _train_one(x, d, train_end, val_end)
        trials.append((d, model, val, test))
        print(f"AE DIMSET={label} d={d} val_mse={val:.6f} test_mse={test:.6f}")
    best = min(t[2] for t in trials)
    chosen = next(t for t in trials if t[2] <= best * 1.10)
    d, model, val, test = chosen
    with torch.no_grad():
        z = model.encoder(torch.tensor(x, dtype=torch.float32)).numpy()
    print(f"AE CHOSEN DIMSET={label} d={d} best_val={best:.6f} chosen_val={val:.6f} test={test:.6f}")
    for j in range(d):
        for target in ("profit_mean", "profit_median", "win_rate"):
            y = frame[target].to_numpy(dtype=float)
            corr = float(np.corrcoef(z[:, j], y)[0, 1]) if np.std(z[:, j]) > 1e-12 and np.std(y) > 1e-12 else np.nan
            print(f"AE POSTHOC DIMSET={label} z={j} target={target} corr={corr:.6f}")


def main() -> None:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_path_table(events)
    frame = build_descriptors(df, paths)
    full = ["L", "U", "C", "B_hold", "B_random_mean", "B_random_q10", "B_random_q50", "B_random_q90", "Q_q10", "Q_q25", "Q_q50", "Q_q75", "Q_q90"]
    core = [x for x in full if x != "C"]
    print(f"AE DATA ticker={TICKER} rows={audit.rows} windows={len(frame)} paths={len(paths)} W={WINDOW} stride={STRIDE}")
    print("AE PRINCIPLE unsupervised_Z=true posthoc_profit_only=true")
    _audit_set(frame, full, "full")
    _audit_set(frame, core, "core")
    print("AE COMPLETE")


if __name__ == "__main__":
    main()

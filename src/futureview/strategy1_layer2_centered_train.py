from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
SHORT_REF = int(os.environ.get("FUTUREVIEW_SHORT_REF", "90"))
LONG_REF = int(os.environ.get("FUTUREVIEW_LONG_REF", "756"))
EPOCHS = int(os.environ.get("FUTUREVIEW_EPOCHS", "120"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
LR = float(os.environ.get("FUTUREVIEW_LR", "0.001"))
BATCH = int(os.environ.get("FUTUREVIEW_BATCH", "32"))


@dataclass
class Split:
    x: np.ndarray
    g: np.ndarray
    y: np.ndarray
    idx: np.ndarray


def _feature_series(df: pd.DataFrame) -> np.ndarray:
    p = df["close"].to_numpy(dtype=np.float64)
    v = df["volume"].to_numpy(dtype=np.float64)
    out = np.full((len(df), 8), np.nan, dtype=np.float64)
    for j, n in enumerate((5, 10, 20, 60)):
        ps = pd.Series(p).shift(1).rolling(n).sum().to_numpy()
        vs = pd.Series(v).shift(1).rolling(n).sum().to_numpy()
        out[:, j] = p / ps
        out[:, 4 + j] = v / vs
    return out


def _centered_targets(df: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    # A centered 2W target around decision t uses [t-W+1, t+W].
    windows = build_representation_a_table(df, paths, window=2 * W, stride=1, random_samples=20, random_seed=SEED)
    by_start = windows.set_index("start_index")
    ret_by_entry = paths.set_index("entry_index")["campaign_return"]
    rows = []
    for t in paths["entry_index"].astype(int).to_numpy():
        s = t - W + 1
        e = t + W
        if s < 0 or e >= len(df) or s not in by_start.index:
            continue
        w = by_start.loc[s]
        if isinstance(w, pd.DataFrame):
            w = w.iloc[0]
        u = float(w.U)
        pe = float(ret_by_entry.loc[t])
        q = u - pe
        if q < -1e-12:
            raise RuntimeError(f"Q invariant failed at entry {t}: {q}")
        q = max(0.0, q)
        rows.append({"decision_index": t, "target_start": s, "target_end": e, "C": float(u - w.B_periodic), "Q": q})
    return pd.DataFrame(rows).sort_values("decision_index").reset_index(drop=True)


def _classify_gate(targets: pd.DataFrame) -> pd.DataFrame:
    # Retrospective state labeling uses only prior completed centered-2W targets to build thresholds.
    rows = []
    for r in targets.itertuples(index=False):
        t = int(r.decision_index)
        prior = targets.loc[targets["target_end"].astype(int) < t]
        short = prior.loc[prior["target_end"].astype(int) >= t - SHORT_REF]
        long = prior.loc[prior["target_end"].astype(int) >= t - LONG_REF]
        if t < LONG_REF or len(short) < 20 or len(long) < 100:
            continue
        c40, c60 = (float(short["C"].quantile(q)) for q in (0.40, 0.60))
        q40, q60 = (float(short["Q"].quantile(q)) for q in (0.40, 0.60))
        c50, q50 = float(long["C"].median()), float(long["Q"].median())
        high = float(r.C) >= c60 and float(r.Q) <= q60 and float(r.C) > c50 and float(r.Q) < q50
        low = float(r.C) <= c40 and float(r.Q) >= q40 and float(r.C) < c50 and float(r.Q) > q50
        if not (high or low):
            continue
        rows.append({**r._asdict(), "gate": 1 if high else -1})
    return pd.DataFrame(rows)


def _build_samples(df: pd.DataFrame, gated: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    feats = _feature_series(df)
    xs, gs, ys, ids = [], [], [], []
    for r in gated.itertuples(index=False):
        t = int(r.decision_index)
        s = t - W + 1
        x = feats[s : t + 1].T
        if x.shape != (8, W) or not np.isfinite(x).all():
            continue
        xs.append(x.astype(np.float32))
        gs.append([float(r.gate)])
        ys.append([float(r.C), float(r.Q)])
        ids.append(t)
    if not xs:
        raise RuntimeError("no training samples")
    return np.stack(xs), np.asarray(gs, np.float32), np.asarray(ys, np.float32), np.asarray(ids, np.int64)


def _split(x: np.ndarray, g: np.ndarray, y: np.ndarray, idx: np.ndarray) -> tuple[Split, Split, Split]:
    order = np.argsort(idx)
    x, g, y, idx = x[order], g[order], y[order], idx[order]
    n = len(idx)
    a = int(n * 0.70)
    b = int(n * 0.85)
    # Purge one centered target width between chronological partitions.
    train_mask = np.arange(n) < a
    val_mask = (np.arange(n) >= a) & (np.arange(n) < b)
    test_mask = np.arange(n) >= b
    if a < n:
        train_mask &= idx <= idx[a] - 2 * W
    if b < n:
        val_mask &= idx <= idx[b] - 2 * W
    if a > 0:
        val_mask &= idx >= idx[a - 1] + 2 * W
    if b > 0:
        test_mask &= idx >= idx[b - 1] + 2 * W

    def pack(m: np.ndarray) -> Split:
        return Split(x[m], g[m], y[m], idx[m])
    return pack(train_mask), pack(val_mask), pack(test_mask)


class CenteredCQNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.branches = nn.ModuleList([
            nn.Sequential(nn.Conv1d(8, 12, k, padding="same"), nn.GELU()) for k in (5, 10, 20)
        ])
        self.fuse = nn.Sequential(nn.Conv1d(36, 24, 3, padding="same"), nn.GELU(), nn.AdaptiveAvgPool1d(1))
        self.head = nn.Sequential(nn.Linear(25, 16), nn.GELU(), nn.Linear(16, 2))

    def forward(self, x: torch.Tensor, g: torch.Tensor) -> torch.Tensor:
        z = torch.cat([b(x) for b in self.branches], dim=1)
        z = self.fuse(z).squeeze(-1)
        return self.head(torch.cat([z, g], dim=1))


def _loader(s: Split, shuffle: bool) -> DataLoader:
    ds = TensorDataset(torch.from_numpy(s.x), torch.from_numpy(s.g), torch.from_numpy(s.y))
    return DataLoader(ds, batch_size=min(BATCH, max(1, len(ds))), shuffle=shuffle)


def _metrics(model: nn.Module, s: Split, device: torch.device, y_mu: torch.Tensor, y_sd: torch.Tensor) -> dict[str, float]:
    model.eval()
    with torch.no_grad():
        p = model(torch.from_numpy(s.x).to(device), torch.from_numpy(s.g).to(device))
        p = p * y_sd + y_mu
        y = torch.from_numpy(s.y).to(device)
    err = p - y
    return {
        "C_mae": float(err[:, 0].abs().mean().cpu()),
        "Q_mae": float(err[:, 1].abs().mean().cpu()),
        "C_rmse": float(torch.sqrt((err[:, 0] ** 2).mean()).cpu()),
        "Q_rmse": float(torch.sqrt((err[:, 1] ** 2).mean()).cpu()),
        "C_corr": float(np.corrcoef(p[:, 0].cpu().numpy(), y[:, 0].cpu().numpy())[0, 1]) if len(s.y) > 2 else float("nan"),
        "Q_corr": float(np.corrcoef(p[:, 1].cpu().numpy(), y[:, 1].cpu().numpy())[0, 1]) if len(s.y) > 2 else float("nan"),
    }


def main() -> None:
    if W != 30 or SHORT_REF != 90 or LONG_REF != 756:
        raise ValueError("baseline locked to W=30, rolling90, rolling3Y")
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    targets = _centered_targets(df, paths)
    gated = _classify_gate(targets)
    x, g, y, idx = _build_samples(df, gated)
    train, val, test = _split(x, g, y, idx)
    if min(len(train.y), len(val.y), len(test.y)) < 5:
        raise RuntimeError(f"split too small train={len(train.y)} val={len(val.y)} test={len(test.y)}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = CenteredCQNet().to(device)
    y_mu = torch.from_numpy(train.y.mean(axis=0, keepdims=True)).float().to(device)
    y_sd_np = train.y.std(axis=0, keepdims=True)
    y_sd_np[y_sd_np < 1e-6] = 1.0
    y_sd = torch.from_numpy(y_sd_np).float().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    loss_fn = nn.SmoothL1Loss()
    best = None
    best_val = float("inf")

    for epoch in range(EPOCHS):
        model.train()
        for xb, gb, yb in _loader(train, True):
            xb, gb, yb = xb.to(device), gb.to(device), yb.to(device)
            target = (yb - y_mu) / y_sd
            pred = model(xb, gb)
            loss = loss_fn(pred, target)
            opt.zero_grad()
            loss.backward()
            opt.step()
        vm = _metrics(model, val, device, y_mu, y_sd)
        score = vm["C_mae"] + vm["Q_mae"]
        if score < best_val:
            best_val = score
            best = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

    if best is not None:
        model.load_state_dict(best)
    trm = _metrics(model, train, device, y_mu, y_sd)
    vam = _metrics(model, val, device, y_mu, y_sd)
    tem = _metrics(model, test, device, y_mu, y_sd)

    def counts(s: Split) -> tuple[int, int]:
        gg = s.g[:, 0]
        return int((gg > 0).sum()), int((gg < 0).sum())

    print(f"S1 L2 CENTER START ticker={TICKER} rows={audit.rows} W={W} centered_target=2W samples={len(y)} device={device}")
    print(f"S1 L2 CENTER SPLIT train={len(train.y)} val={len(val.y)} test={len(test.y)} purge={2*W}")
    for name, s in (("train", train), ("val", val), ("test", test)):
        hi, lo = counts(s)
        print(f"S1 L2 CENTER SUPPORT split={name} high={hi} low={lo}")
    for name, m in (("train", trm), ("val", vam), ("test", tem)):
        print("S1 L2 CENTER METRIC split=" + name + " " + " ".join(f"{k}={v:.6f}" for k, v in m.items()))
    print("S1 L2 CENTER COMPLETE")


if __name__ == "__main__":
    main()

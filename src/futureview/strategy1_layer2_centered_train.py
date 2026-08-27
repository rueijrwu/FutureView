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
from .strategy1_cq_90d_rank_audit import build_window_q

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
    # Historical target around decision t: [t-W+1, t+W].
    windows = build_representation_a_table(
        df, paths, window=2 * W, stride=1, random_samples=20, random_seed=SEED
    )
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
        q = max(0.0, u - pe)
        rows.append(
            {
                "decision_index": t,
                "target_start": s,
                "target_end": e,
                "C": float(u - w.B_periodic),
                "Q": q,
            }
        )
    return pd.DataFrame(rows).sort_values("decision_index").reset_index(drop=True)


def _historical_gate(df: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    # Gate is known at decision time and comes only from completed historical W30 outcomes.
    windows = build_representation_a_table(
        df, paths, window=W, stride=1, random_samples=20, random_seed=SEED
    )
    wq = build_window_q(windows, paths).sort_values("start_index").reset_index(drop=True)
    rows = []
    for r in wq.itertuples(index=False):
        s = int(r.start_index)
        prior = wq.loc[wq["end_index"].astype(int) < s]
        short = prior.loc[prior["end_index"].astype(int) >= s - SHORT_REF]
        long = prior.loc[prior["end_index"].astype(int) >= s - LONG_REF]
        if s < LONG_REF or len(short) < 20 or len(long) < 100:
            continue
        c40, c60 = (float(short["C"].quantile(q)) for q in (0.40, 0.60))
        q40, q60 = (float(short["Q"].quantile(q)) for q in (0.40, 0.60))
        c50, q50 = float(long["C"].median()), float(long["Q"].median())
        high = float(r.C) >= c60 and float(r.Q) <= q60 and float(r.C) > c50 and float(r.Q) < q50
        low = float(r.C) <= c40 and float(r.Q) >= q40 and float(r.C) < c50 and float(r.Q) > q50
        state = 1 if high else (-1 if low else 0)
        rows.append(
            {
                "start_index": s,
                "end_index": int(r.end_index),
                "gate": state,
                "C_hist": float(r.C),
                "Q_hist": float(r.Q),
            }
        )
    return pd.DataFrame(rows).sort_values("end_index").reset_index(drop=True)


def _attach_gate(targets: pd.DataFrame, gate: pd.DataFrame) -> pd.DataFrame:
    # For each decision t, use the most recently completed historical W30 state available at t.
    rows = []
    for r in targets.itertuples(index=False):
        t = int(r.decision_index)
        avail = gate.loc[(gate["end_index"].astype(int) < t) & (gate["gate"] != 0)]
        if avail.empty:
            continue
        g = avail.iloc[-1]
        rows.append({**r._asdict(), "gate": int(g.gate), "gate_end_index": int(g.end_index)})
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
    cut_a, cut_b = idx[a], idx[b]
    # Chronological split with W-session embargo around split boundaries.
    train_mask = idx < cut_a - W
    val_mask = (idx >= cut_a + W) & (idx < cut_b - W)
    test_mask = idx >= cut_b + W

    def pack(m: np.ndarray) -> Split:
        return Split(x[m], g[m], y[m], idx[m])
    return pack(train_mask), pack(val_mask), pack(test_mask)


class CenteredCQNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.branches = nn.ModuleList([
            nn.Sequential(nn.Conv1d(8, 12, k, padding="same"), nn.GELU()) for k in (5, 10, 20)
        ])
        self.fuse = nn.Sequential(
            nn.Conv1d(36, 24, 3, padding="same"), nn.GELU(), nn.AdaptiveAvgPool1d(1)
        )
        self.head = nn.Sequential(nn.Linear(25, 16), nn.GELU(), nn.Linear(16, 2))

    def forward(self, x: torch.Tensor, g: torch.Tensor) -> torch.Tensor:
        z = torch.cat([b(x) for b in self.branches], dim=1)
        z = self.fuse(z).squeeze(-1)
        return self.head(torch.cat([z, g], dim=1))


def _loader(s: Split, shuffle: bool) -> DataLoader:
    ds = TensorDataset(torch.from_numpy(s.x), torch.from_numpy(s.g), torch.from_numpy(s.y))
    return DataLoader(ds, batch_size=min(BATCH, max(1, len(ds))), shuffle=shuffle)


def _predict(model: nn.Module, s: Split, device: torch.device, y_mu: torch.Tensor, y_sd: torch.Tensor):
    model.eval()
    with torch.no_grad():
        p = model(torch.from_numpy(s.x).to(device), torch.from_numpy(s.g).to(device))
        p = p * y_sd + y_mu
    return p.cpu().numpy()


def _metrics(model: nn.Module, s: Split, device: torch.device, y_mu: torch.Tensor, y_sd: torch.Tensor) -> dict[str, float]:
    p = _predict(model, s, device, y_mu, y_sd)
    y = s.y
    err = p - y
    out = {
        "C_mae": float(np.abs(err[:, 0]).mean()),
        "Q_mae": float(np.abs(err[:, 1]).mean()),
        "C_corr": float(np.corrcoef(p[:, 0], y[:, 0])[0, 1]) if len(y) > 2 else float("nan"),
        "Q_corr": float(np.corrcoef(p[:, 1], y[:, 1])[0, 1]) if len(y) > 2 else float("nan"),
    }
    # Ranking audit: compare actual target means in top/bottom predicted thirds.
    n = len(y)
    k = max(1, n // 3)
    c_order = np.argsort(p[:, 0])
    q_order = np.argsort(p[:, 1])
    out["C_actual_pred_top"] = float(y[c_order[-k:], 0].mean())
    out["C_actual_pred_bottom"] = float(y[c_order[:k], 0].mean())
    out["Q_actual_pred_low"] = float(y[q_order[:k], 1].mean())
    out["Q_actual_pred_high"] = float(y[q_order[-k:], 1].mean())
    return out


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
    gate = _historical_gate(df, paths)
    gated = _attach_gate(targets, gate)
    x, g, y, idx = _build_samples(df, gated)
    train, val, test = _split(x, g, y, idx)
    if min(len(train.y), len(val.y), len(test.y)) < 5:
        raise RuntimeError(f"split too small train={len(train.y)} val={len(val.y)} test={len(test.y)} total={len(y)}")

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

    for _ in range(EPOCHS):
        model.train()
        for xb, gb, yb in _loader(train, True):
            xb, gb, yb = xb.to(device), gb.to(device), yb.to(device)
            pred = model(xb, gb)
            target = (yb - y_mu) / y_sd
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

    print(f"S1 L2 CENTER START ticker={TICKER} rows={audit.rows} W={W} centered_target=2W decisions={len(targets)} gated_samples={len(y)} device={device}")
    print(f"S1 L2 CENTER SPLIT train={len(train.y)} val={len(val.y)} test={len(test.y)} embargo={W}")
    for name, s in (("train", train), ("val", val), ("test", test)):
        hi = int((s.g[:, 0] > 0).sum())
        lo = int((s.g[:, 0] < 0).sum())
        print(f"S1 L2 CENTER SUPPORT split={name} high={hi} low={lo}")
        m = _metrics(model, s, device, y_mu, y_sd)
        print("S1 L2 CENTER METRIC split=" + name + " " + " ".join(f"{k}={v:.6f}" for k, v in m.items()))
    print("S1 L2 CENTER COMPLETE")


if __name__ == "__main__":
    main()

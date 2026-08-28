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
EPOCHS = int(os.environ.get("FUTUREVIEW_EPOCHS", "120"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
LR = float(os.environ.get("FUTUREVIEW_LR", "0.001"))
BATCH = int(os.environ.get("FUTUREVIEW_BATCH", "32"))
LAYER1_GATE_CSV = os.environ.get("FUTUREVIEW_LAYER1_GATE_CSV", "strategy1-layer1-gate.csv")


@dataclass
class Split:
    x: np.ndarray
    y: np.ndarray
    idx: np.ndarray
    state: np.ndarray


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
    windows = build_representation_a_table(
        df,
        paths,
        window=2 * W,
        stride=1,
        random_samples=20,
        random_seed=SEED,
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
        rows.append(
            {
                "decision_index": t,
                "target_start": s,
                "target_end": e,
                "C": float(u - w.B_periodic),
                "Q": max(0.0, u - pe),
            }
        )
    return pd.DataFrame(rows).sort_values("decision_index").reset_index(drop=True)


def _load_layer1_gate() -> pd.DataFrame:
    gate = pd.read_csv(LAYER1_GATE_CSV)
    required = {"end_index", "state"}
    missing = required.difference(gate.columns)
    if missing:
        raise RuntimeError(f"Layer 1 gate CSV missing columns: {sorted(missing)}")
    gate = gate[["end_index", "state"]].copy()
    gate["end_index"] = gate["end_index"].astype(int)
    gate["state"] = gate["state"].astype(str).str.lower()
    if gate["end_index"].duplicated().any():
        raise RuntimeError("Layer 1 gate CSV has duplicate end_index rows")
    bad = gate.loc[~gate["state"].isin(["high", "neutral", "low"])]
    if not bad.empty:
        raise RuntimeError("Layer 1 gate CSV contains invalid state values")
    return gate.sort_values("end_index").reset_index(drop=True)


def _select_layer2_entries(targets: pd.DataFrame, gate: pd.DataFrame) -> pd.DataFrame:
    # Exact same-session handoff only: a legal Entry at t uses the Layer 1 W30
    # state whose end_index is exactly t. No latest-state search and no inheritance.
    joined = targets.merge(
        gate,
        how="left",
        left_on="decision_index",
        right_on="end_index",
        validate="one_to_one",
    )
    return joined.loc[joined["state"].isin(["high", "low"])].reset_index(drop=True)


def _build_samples(
    df: pd.DataFrame, selected: pd.DataFrame
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    feats = _feature_series(df)
    xs, ys, ids, states = [], [], [], []
    for r in selected.itertuples(index=False):
        t = int(r.decision_index)
        s = t - W + 1
        x = feats[s : t + 1].T
        if x.shape != (8, W) or not np.isfinite(x).all():
            continue
        xs.append(x.astype(np.float32))
        ys.append([float(r.C), float(r.Q)])
        ids.append(t)
        states.append(str(r.state))
    if not xs:
        raise RuntimeError("no training samples")
    return (
        np.stack(xs),
        np.asarray(ys, np.float32),
        np.asarray(ids, np.int64),
        np.asarray(states, dtype="U7"),
    )


def _split(
    x: np.ndarray,
    y: np.ndarray,
    idx: np.ndarray,
    state: np.ndarray,
) -> tuple[Split, Split, Split]:
    order = np.argsort(idx)
    x, y, idx, state = x[order], y[order], idx[order], state[order]
    n = len(idx)
    a = int(n * 0.70)
    b = int(n * 0.85)
    cut_a, cut_b = idx[a], idx[b]
    train_mask = idx < cut_a - W
    val_mask = (idx >= cut_a + W) & (idx < cut_b - W)
    test_mask = idx >= cut_b + W

    def pack(m: np.ndarray) -> Split:
        return Split(x[m], y[m], idx[m], state[m])

    return pack(train_mask), pack(val_mask), pack(test_mask)


class CenteredCQNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.branches = nn.ModuleList(
            [
                nn.Sequential(nn.Conv1d(8, 12, k, padding="same"), nn.GELU())
                for k in (5, 10, 20)
            ]
        )
        self.fuse = nn.Sequential(
            nn.Conv1d(36, 24, 3, padding="same"),
            nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Sequential(nn.Linear(24, 16), nn.GELU(), nn.Linear(16, 2))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = torch.cat([b(x) for b in self.branches], dim=1)
        z = self.fuse(z).squeeze(-1)
        return self.head(z)


def _loader(s: Split, shuffle: bool) -> DataLoader:
    ds = TensorDataset(torch.from_numpy(s.x), torch.from_numpy(s.y))
    return DataLoader(ds, batch_size=min(BATCH, max(1, len(ds))), shuffle=shuffle)


def _predict(
    model: nn.Module,
    s: Split,
    device: torch.device,
    y_mu: torch.Tensor,
    y_sd: torch.Tensor,
):
    model.eval()
    with torch.no_grad():
        p = model(torch.from_numpy(s.x).to(device))
        p = p * y_sd + y_mu
    return p.cpu().numpy()


def _metrics(
    model: nn.Module,
    s: Split,
    device: torch.device,
    y_mu: torch.Tensor,
    y_sd: torch.Tensor,
) -> dict[str, float]:
    p = _predict(model, s, device, y_mu, y_sd)
    y = s.y
    err = p - y
    out = {
        "C_mae": float(np.abs(err[:, 0]).mean()),
        "Q_mae": float(np.abs(err[:, 1]).mean()),
        "C_corr": float(np.corrcoef(p[:, 0], y[:, 0])[0, 1]) if len(y) > 2 else float("nan"),
        "Q_corr": float(np.corrcoef(p[:, 1], y[:, 1])[0, 1]) if len(y) > 2 else float("nan"),
    }
    n = len(y)
    k = max(1, n // 3)
    c_order = np.argsort(p[:, 0])
    q_order = np.argsort(p[:, 1])
    out["C_actual_pred_top"] = float(y[c_order[-k:], 0].mean())
    out["C_actual_pred_bottom"] = float(y[c_order[:k], 0].mean())
    out["Q_actual_pred_low"] = float(y[q_order[:k], 1].mean())
    out["Q_actual_pred_high"] = float(y[q_order[-k:], 1].mean())
    return out


def _support(s: Split) -> tuple[int, int]:
    return int((s.state == "high").sum()), int((s.state == "low").sum())


def main() -> None:
    if W != 30:
        raise ValueError("baseline locked to W=30")
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    targets = _centered_targets(df, paths)
    gate = _load_layer1_gate()
    selected = _select_layer2_entries(targets, gate)
    x, y, idx, state = _build_samples(df, selected)
    train, val, test = _split(x, y, idx, state)

    high_n = int((state == "high").sum())
    low_n = int((state == "low").sum())
    exact_matches = int(targets["decision_index"].isin(gate["end_index"]).sum())
    print(
        f"S1 L2 CENTER COUNTS decisions={len(targets)} layer1_rows={len(gate)} "
        f"exact_gate_matches={exact_matches} pass_entries={len(selected)} "
        f"finite_samples={len(y)} gate_high={high_n} gate_low={low_n} "
        "gate_handoff=exact_end_index gate_as_model_input=false"
    )

    if min(len(train.y), len(val.y), len(test.y)) < 5:
        raise RuntimeError(
            f"split too small train={len(train.y)} val={len(val.y)} "
            f"test={len(test.y)} total={len(y)}"
        )

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
        for xb, yb in _loader(train, True):
            xb, yb = xb.to(device), yb.to(device)
            pred = model(xb)
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

    print(
        f"S1 L2 CENTER START ticker={TICKER} rows={audit.rows} W={W} "
        f"centered_target=2W decisions={len(targets)} gated_samples={len(y)} device={device}"
    )
    print(
        f"S1 L2 CENTER SPLIT train={len(train.y)} val={len(val.y)} "
        f"test={len(test.y)} embargo={W}"
    )
    for name, s in (("train", train), ("val", val), ("test", test)):
        high, low = _support(s)
        print(f"S1 L2 CENTER SUPPORT split={name} high={high} low={low}")
        m = _metrics(model, s, device, y_mu, y_sd)
        print(
            "S1 L2 CENTER METRIC split="
            + name
            + " "
            + " ".join(f"{k}={v:.6f}" for k, v in m.items())
        )
    print("S1 L2 CENTER COMPLETE")


if __name__ == "__main__":
    main()

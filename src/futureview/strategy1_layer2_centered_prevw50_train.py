from __future__ import annotations

import os
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
from .strategy1_prev_w_neutral_gate_audit import classify_layer1
from .strategy1_layer2_centered_train import _feature_series, _centered_targets, CenteredCQNet

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
W = int(os.environ.get("FUTUREVIEW_W", "30"))
EPOCHS = int(os.environ.get("FUTUREVIEW_EPOCHS", "120"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
LR = float(os.environ.get("FUTUREVIEW_LR", "0.001"))
BATCH = int(os.environ.get("FUTUREVIEW_BATCH", "16"))


def build_prev_w_gate(df: pd.DataFrame, paths: pd.DataFrame) -> pd.DataFrame:
    w30 = build_representation_a_table(df, paths, window=W, stride=1, random_samples=20, random_seed=SEED)
    wq = build_window_q(w30, paths).sort_values("start_index").reset_index(drop=True)
    return classify_layer1(wq)


def select_pass_entries(targets: pd.DataFrame, gate: pd.DataFrame) -> pd.DataFrame:
    # Entry t uses the immediately preceding complete W30 state ending at t-1.
    g = gate[["end_index", "state"]].copy()
    g["decision_index"] = g["end_index"].astype(int) + 1
    joined = targets.merge(g[["decision_index", "state"]], on="decision_index", how="left", validate="one_to_one")
    joined["decision"] = np.where(joined["state"].eq("neutral"), "block", np.where(joined["state"].isin(["high", "low"]), "pass", "missing"))
    return joined


def build_samples(df: pd.DataFrame, selected: pd.DataFrame):
    feats = _feature_series(df)
    xs, ys, ids = [], [], []
    for r in selected.loc[selected.decision.eq("pass")].itertuples(index=False):
        t = int(r.decision_index)
        s = t - W + 1
        x = feats[s:t+1].T
        if x.shape != (8, W) or not np.isfinite(x).all():
            continue
        xs.append(x.astype(np.float32))
        ys.append([float(r.C), float(r.Q)])
        ids.append(t)
    if not xs:
        raise RuntimeError("no finite PASS samples")
    return np.stack(xs), np.asarray(ys, np.float32), np.asarray(ids, np.int64)


def split_train_test(x, y, idx):
    order = np.argsort(idx)
    x, y, idx = x[order], y[order], idx[order]
    n = len(idx)
    cut_pos = max(1, min(n - 1, int(n * 0.70)))
    cut = int(idx[cut_pos])
    train_mask = idx < cut - W
    test_mask = idx >= cut + W
    return (x[train_mask], y[train_mask], idx[train_mask]), (x[test_mask], y[test_mask], idx[test_mask]), cut


def loader(x, y, shuffle):
    ds = TensorDataset(torch.from_numpy(x), torch.from_numpy(y))
    return DataLoader(ds, batch_size=min(BATCH, max(1, len(ds))), shuffle=shuffle)


def metrics(model, x, y, device, mu, sd):
    model.eval()
    with torch.no_grad():
        p = model(torch.from_numpy(x).to(device)) * sd + mu
    p = p.cpu().numpy()
    err = p - y
    out = {
        "C_mae": float(np.abs(err[:,0]).mean()),
        "Q_mae": float(np.abs(err[:,1]).mean()),
        "C_corr": float(np.corrcoef(p[:,0], y[:,0])[0,1]) if len(y) > 2 else float("nan"),
        "Q_corr": float(np.corrcoef(p[:,1], y[:,1])[0,1]) if len(y) > 2 else float("nan"),
    }
    k = max(1, len(y)//3)
    co = np.argsort(p[:,0]); qo = np.argsort(p[:,1])
    out["C_actual_pred_top"] = float(y[co[-k:],0].mean())
    out["C_actual_pred_bottom"] = float(y[co[:k],0].mean())
    out["Q_actual_pred_low"] = float(y[qo[:k],1].mean())
    out["Q_actual_pred_high"] = float(y[qo[-k:],1].mean())
    return out


def main() -> None:
    if W != 30:
        raise ValueError("audit locked to W=30")
    np.random.seed(SEED); torch.manual_seed(SEED)

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    targets = _centered_targets(df, paths)
    gate = build_prev_w_gate(df, paths)
    joined = select_pass_entries(targets, gate)

    matched = joined.loc[joined.decision.ne("missing")]
    pass_n = int((matched.decision == "pass").sum())
    block_n = int((matched.decision == "block").sum())
    print(f"S1 L2PW50 PREFILTER decisions={len(targets)} matched={len(matched)} pass={pass_n} block={block_n} pass_rate={pass_n/len(matched):.6f} block_rate={block_n/len(matched):.6f} handoff=prev_end_tminus1")

    x, y, idx = build_samples(df, joined)
    train, test, cut = split_train_test(x, y, idx)
    xtr, ytr, itr = train; xte, yte, ite = test
    print(f"S1 L2PW50 SAMPLES finite_pass={len(y)} train={len(ytr)} test={len(yte)} embargo={W} cut={cut}")
    if len(ytr) < 10 or len(yte) < 5:
        raise RuntimeError(f"split too small train={len(ytr)} test={len(yte)} total={len(y)}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = CenteredCQNet().to(device)
    mu = torch.from_numpy(ytr.mean(axis=0, keepdims=True)).float().to(device)
    sd_np = ytr.std(axis=0, keepdims=True); sd_np[sd_np < 1e-6] = 1.0
    sd = torch.from_numpy(sd_np).float().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    loss_fn = nn.SmoothL1Loss()

    for epoch in range(EPOCHS):
        model.train()
        for xb, yb in loader(xtr, ytr, True):
            xb, yb = xb.to(device), yb.to(device)
            pred = model(xb)
            loss = loss_fn(pred, (yb-mu)/sd)
            opt.zero_grad(); loss.backward(); opt.step()
        if epoch in (0, EPOCHS-1):
            print(f"S1 L2PW50 TRAIN epoch={epoch+1} loss={float(loss.detach().cpu()):.6f}")

    for name, xx, yy in (("train", xtr, ytr), ("test", xte, yte)):
        m = metrics(model, xx, yy, device, mu, sd)
        print("S1 L2PW50 METRIC split=" + name + " " + " ".join(f"{k}={v:.6f}" for k,v in m.items()))

    print(f"S1 L2PW50 START ticker={TICKER} rows={audit.rows} W={W} target=centered_raw_CQ good_bad_labels=false device={device}")
    print("S1 L2PW50 COMPLETE prefilter=previous_W_neutral_block layer2_target=raw_CQ")

if __name__ == "__main__":
    main()

from __future__ import annotations

import os
import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_entry_exit_cq_compare import build_cq
from .strategy1_exit_window_cq_audit import classify_causal
from .strategy1_layer2_forward_smoke import make_input_features
from .strategy1_layer2_consensus_group_audit import consensus_label
from .strategy1_layer2_consensus_condition_audit import train_conditioned
from .strategy1_layer2_price_distribution import MODEL_HISTORY, SEED

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "8y")
ROLL_DAYS = int(os.environ.get("FUTUREVIEW_ROLL_DAYS", "10"))
L2_MEMORY = int(os.environ.get("FUTUREVIEW_L2_MEMORY", "150"))
L3_MIN_TRAIN = int(os.environ.get("FUTUREVIEW_L3_MIN_TRAIN", "60"))
L3_EPOCHS = int(os.environ.get("FUTUREVIEW_L3_EPOCHS", "300"))
HORIZONS = (5, 10, 15, 20, 25, 30)
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-layer3-multihorizon-audit.csv")


class MetaMLP(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.net = nn.Sequential(nn.Linear(24, 16), nn.GELU(), nn.Linear(16, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(1)


class MetaCNN(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        # Input shape: [batch, 4 channels, 6 horizons]. Convolution is only
        # across the horizon axis; Layer3 never sees raw price/volume.
        self.conv = nn.Sequential(
            nn.Conv1d(4, 12, kernel_size=3, padding=1), nn.GELU(),
            nn.Conv1d(12, 12, kernel_size=3, padding=1), nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Linear(12, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = self.conv(x).squeeze(-1)
        return self.head(z).squeeze(1)


def _train_binary(model: nn.Module, x: torch.Tensor, y: torch.Tensor) -> nn.Module:
    np.random.seed(SEED); torch.manual_seed(SEED)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    loss_fn = nn.BCEWithLogitsLoss()
    for _ in range(L3_EPOCHS):
        model.train()
        loss = loss_fn(model(x), y)
        opt.zero_grad(); loss.backward(); opt.step()
    return model


def _evaluate(frame: pd.DataFrame, score_col: str, name: str) -> None:
    if frame.empty:
        print(f"S1 L3 SUMMARY model={name} n=0")
        return
    score = frame[score_col].to_numpy(float)
    y = frame.actual_r30.to_numpy(float)
    obs = (y > 0).astype(float)
    rho = float(pd.Series(y).corr(pd.Series(score), method="spearman"))
    lo, hi = np.quantile(score, [0.2, 0.8])
    bot = frame[frame[score_col] <= lo]
    top = frame[frame[score_col] >= hi]
    print(
        f"S1 L3 SUMMARY model={name} n={len(frame)} folds={frame.fold_id.nunique()} "
        f"observed_up={obs.mean():.6f} spearman={rho:.6f}"
    )
    print(
        f"S1 L3 BUCKET model={name} bottom_n={len(bot)} bottom_up={(bot.actual_r30>0).mean():.6f} "
        f"bottom_ret={bot.actual_r30.mean():.6f} top_n={len(top)} top_up={(top.actual_r30>0).mean():.6f} "
        f"top_ret={top.actual_r30.mean():.6f}"
    )


def main() -> None:
    if MODEL_HISTORY != 90:
        raise ValueError("Layer3 audit requires established 90D normalized P/V Layer2 input")
    torch.set_num_threads(2)
    np.random.seed(SEED); torch.manual_seed(SEED)

    df = download_ticker_daily(TICKER, period=DATA_PERIOD).reset_index(drop=True)
    validate_daily_ohlcv(df, minimum_rows=1800)
    close = df.close.to_numpy(float)

    paths = build_deterministic_path_table(add_strategy1_events(df).reset_index(drop=True))
    ce = classify_causal(build_cq(df, paths, membership="entry").rename(columns={"B": "B_periodic"}))
    cx = classify_causal(build_cq(df, paths, membership="exit").rename(columns={"B": "B_periodic"}))
    states = ce[["start_index","end_index","state"]].merge(
        cx[["start_index","end_index","state"]], on=["start_index","end_index"], suffixes=("_entry","_exit")
    ).sort_values("end_index").reset_index(drop=True)
    states["consensus"] = [consensus_label(a, b) for a, b in zip(states.state_entry, states.state_exit)]

    # Layer2 may use the established eligible H/L population for its 150-sample
    # memory, but Layer3 research/evaluation is H-only.
    rows, xs = [], []
    for r in states.itertuples(index=False):
        if r.consensus not in ("high", "low"):
            continue
        cutoff = int(r.end_index)
        start = cutoff - MODEL_HISTORY + 1
        if start < 0 or cutoff + max(HORIZONS) >= len(df):
            continue
        xs.append(make_input_features(df, start, cutoff))
        rec = {"cutoff_index": cutoff, "consensus": r.consensus}
        for h in HORIZONS:
            rec[f"r{h}"] = float(np.log(close[cutoff+h] / close[cutoff]))
        rows.append(rec)
    rows = pd.DataFrame(rows).sort_values("cutoff_index").reset_index(drop=True)
    x = torch.from_numpy(np.stack(xs)).float()
    c = torch.tensor(np.where(rows.consensus.eq("high"), 1.0, -1.0), dtype=torch.float32)

    # Stage 1: strictly OOS Layer2 predictions for all six horizons.
    l2_out = []
    first_cut, last_cut = int(rows.cutoff_index.min()), int(rows.cutoff_index.max())
    fid = 0
    for block_start in range(first_cut, last_cut + 1, ROLL_DAYS):
        block_end = min(block_start + ROLL_DAYS - 1, last_cut)
        va = (rows.cutoff_index >= block_start) & (rows.cutoff_index <= block_end)
        if not va.any():
            continue
        tr_idx = np.flatnonzero((rows.cutoff_index < block_start).to_numpy())
        if len(tr_idx) < L2_MEMORY:
            continue
        tr_idx = tr_idx[-L2_MEMORY:]
        va_idx = np.flatnonzero(va.to_numpy())
        high_va_idx = va_idx[rows.iloc[va_idx].consensus.eq("high").to_numpy()]
        if len(high_va_idx) == 0:
            continue

        feat = rows.iloc[high_va_idx][["cutoff_index", "r30"]].copy().reset_index(drop=True)
        for h in HORIZONS:
            y = torch.tensor(rows[f"r{h}"].to_numpy(float), dtype=torch.float32)
            model = train_conditioned(x[torch.from_numpy(tr_idx)], y[torch.from_numpy(tr_idx)], c[torch.from_numpy(tr_idx)])
            model.eval()
            with torch.no_grad():
                q, logit = model(x[torch.from_numpy(high_va_idx)], c[torch.from_numpy(high_va_idx)])
            qn = q.numpy(); pn = torch.sigmoid(logit).numpy()
            feat[f"q10_{h}"] = qn[:,0]
            feat[f"q50_{h}"] = qn[:,1]
            feat[f"q90_{h}"] = qn[:,2]
            feat[f"pup_{h}"] = pn
        feat["l2_fold"] = fid
        l2_out.append(feat)
        fid += 1

    if not l2_out:
        raise RuntimeError("no H-only OOS Layer2 rows for Layer3")
    meta = pd.concat(l2_out, ignore_index=True).sort_values("cutoff_index").reset_index(drop=True)

    feature_cols = [f"{k}_{h}" for h in HORIZONS for k in ("q10", "q50", "q90", "pup")]
    # Order into 6 horizons x 4 channels, then flatten for MLP.
    xmeta = meta[feature_cols].to_numpy(np.float32).reshape(len(meta), len(HORIZONS), 4)
    xmeta_mlp = torch.from_numpy(xmeta.reshape(len(meta), -1))
    xmeta_cnn = torch.from_numpy(np.transpose(xmeta, (0, 2, 1)))
    ymeta = torch.tensor((meta.r30.to_numpy(float) > 0).astype(np.float32))

    # Stage 2: Layer3 itself is chronological OOS. It trains only on earlier
    # Layer2-OOS rows, preventing stacking leakage.
    outs = []
    fid = 0
    for block_start in range(int(meta.cutoff_index.min()), int(meta.cutoff_index.max()) + 1, ROLL_DAYS):
        block_end = min(block_start + ROLL_DAYS - 1, int(meta.cutoff_index.max()))
        va = (meta.cutoff_index >= block_start) & (meta.cutoff_index <= block_end)
        va_idx = np.flatnonzero(va.to_numpy())
        tr_idx = np.flatnonzero((meta.cutoff_index < block_start).to_numpy())
        if len(va_idx) == 0 or len(tr_idx) < L3_MIN_TRAIN:
            continue

        mlp = _train_binary(MetaMLP(), xmeta_mlp[torch.from_numpy(tr_idx)], ymeta[torch.from_numpy(tr_idx)])
        cnn = _train_binary(MetaCNN(), xmeta_cnn[torch.from_numpy(tr_idx)], ymeta[torch.from_numpy(tr_idx)])
        mlp.eval(); cnn.eval()
        with torch.no_grad():
            p_mlp = torch.sigmoid(mlp(xmeta_mlp[torch.from_numpy(va_idx)])).numpy()
            p_cnn = torch.sigmoid(cnn(xmeta_cnn[torch.from_numpy(va_idx)])).numpy()
        f = meta.iloc[va_idx].copy().reset_index(drop=True)
        f["score_30d_single"] = f["pup_30"].to_numpy(float)
        f["score_mlp"] = p_mlp
        f["score_cnn"] = p_cnn
        f["actual_r30"] = f["r30"]
        f["fold_id"] = fid
        outs.append(f)
        fid += 1

    if not outs:
        raise RuntimeError("no eligible Layer3 OOS folds")
    out = pd.concat(outs, ignore_index=True).sort_values("cutoff_index").reset_index(drop=True)
    _evaluate(out, "score_30d_single", "single30")
    _evaluate(out, "score_mlp", "multihorizon_mlp")
    _evaluate(out, "score_cnn", "multihorizon_cnn")
    out.to_csv(OUTPUT, index=False)
    print(
        f"S1 L3 CONFIG period={DATA_PERIOD} horizons={','.join(map(str,HORIZONS))} "
        f"l2_memory={L2_MEMORY} roll_days={ROLL_DAYS} l3_min_train={L3_MIN_TRAIN} l2_oos_high={len(meta)} l3_oos={len(out)}"
    )
    print(f"S1 L3 OUTPUT file={OUTPUT}")
    print("S1 L3 COMPLETE")


if __name__ == "__main__":
    main()

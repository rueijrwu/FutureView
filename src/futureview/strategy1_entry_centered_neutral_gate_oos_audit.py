from __future__ import annotations

import os

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    precision_score,
    recall_score,
    roc_auc_score,
)
from torch import nn

from .strategy1_entry_centered_unsupervised_audit import build_samples

W = int(os.environ.get("FUTUREVIEW_W", "30"))
SEED = int(os.environ.get("FUTUREVIEW_SEED", "20260827"))
EPOCHS = int(os.environ.get("FUTUREVIEW_EPOCHS", "400"))
LR = float(os.environ.get("FUTUREVIEW_LR", "0.001"))
TRAIN_FRAC = float(os.environ.get("FUTUREVIEW_TRAIN_FRAC", "0.70"))
OUTPUT = os.environ.get("FUTUREVIEW_OUTPUT", "strategy1-entry-centered-neutral-gate-oos-audit.csv")


class NeutralGate(nn.Module):
    def __init__(self, dim: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(dim, 64),
            nn.GELU(),
            nn.Dropout(0.10),
            nn.Linear(64, 24),
            nn.GELU(),
            nn.Linear(24, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


def label_from_thresholds(df: pd.DataFrame, c40: float, c60: float, q40: float, q60: float) -> pd.Series:
    good = (df.C >= c60) & (df.Q <= q40)
    bad = (df.C <= c40) & (df.Q >= q60)
    return (good | bad).astype(np.int64)


def main() -> None:
    if W != 30:
        raise ValueError("Neutral gate audit locked to W=30")
    if not (0.55 <= TRAIN_FRAC <= 0.80):
        raise ValueError("TRAIN_FRAC must be in [0.55, 0.80]")

    np.random.seed(SEED)
    torch.manual_seed(SEED)

    out, x = build_samples()
    n = len(out)
    raw_cut = int(np.floor(n * TRAIN_FRAC))
    if raw_cut <= 0 or raw_cut >= n:
        raise RuntimeError("invalid chronological split")

    # First OOS Entry defines the deployment boundary. Historical centered labels
    # used for training must be fully mature before that Entry, hence W-session embargo.
    test = out.iloc[raw_cut:].copy().reset_index(drop=True)
    x_test = x[raw_cut:].copy()
    cut_entry = int(test.entry_index.iloc[0])
    train_mask = out.entry_index.to_numpy(dtype=int) + W < cut_entry
    train = out.loc[train_mask].copy().reset_index(drop=True)
    x_train = x[train_mask].copy()

    if len(train) < 60 or len(test) < 30:
        raise RuntimeError(f"split too small train={len(train)} test={len(test)} total={n}")

    # C/Q are used only to construct historical supervision. Thresholds are fit on
    # training history and then frozen; OOS labels use those same frozen thresholds.
    c40 = float(train.C.quantile(0.40))
    c60 = float(train.C.quantile(0.60))
    q40 = float(train.Q.quantile(0.40))
    q60 = float(train.Q.quantile(0.60))
    y_train = label_from_thresholds(train, c40, c60, q40, q60).to_numpy(dtype=np.float32)
    y_test = label_from_thresholds(test, c40, c60, q40, q60).to_numpy(dtype=np.int64)

    # Causal feature normalization fit on train only.
    mu = x_train.mean(axis=0, keepdims=True)
    sd = x_train.std(axis=0, keepdims=True)
    sd[sd < 1e-8] = 1.0
    xn_train = ((x_train - mu) / sd).astype(np.float32)
    xn_test = ((x_test - mu) / sd).astype(np.float32)

    xt = torch.from_numpy(xn_train)
    yt = torch.from_numpy(y_train)
    model = NeutralGate(xn_train.shape[1])
    positives = float(y_train.sum())
    negatives = float(len(y_train) - positives)
    pos_weight = torch.tensor([negatives / max(positives, 1.0)], dtype=torch.float32)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)

    for epoch in range(EPOCHS):
        model.train()
        logits = model(xt)
        loss = loss_fn(logits, yt)
        opt.zero_grad()
        loss.backward()
        opt.step()
        if epoch in (0, EPOCHS - 1):
            print(f"S1 NGATE TRAIN epoch={epoch+1} bce={float(loss.detach()):.6f}")

    model.eval()
    with torch.no_grad():
        train_prob = torch.sigmoid(model(torch.from_numpy(xn_train))).numpy()
        test_prob = torch.sigmoid(model(torch.from_numpy(xn_test))).numpy()

    # Fixed 0.5 gate threshold: no OOS threshold tuning.
    threshold = 0.5
    pred = (test_prob >= threshold).astype(np.int64)
    tn, fp, fn, tp = confusion_matrix(y_test, pred, labels=[0, 1]).ravel()
    prevalence_train = float(y_train.mean())
    prevalence_test = float(y_test.mean())
    pass_rate = float(pred.mean())
    precision = float(precision_score(y_test, pred, zero_division=0))
    recall = float(recall_score(y_test, pred, zero_division=0))
    bal_acc = float(balanced_accuracy_score(y_test, pred))
    roc = float(roc_auc_score(y_test, test_prob)) if len(np.unique(y_test)) == 2 else float("nan")
    ap = float(average_precision_score(y_test, test_prob)) if len(np.unique(y_test)) == 2 else float("nan")

    passed = test.loc[pred == 1]
    blocked = test.loc[pred == 0]
    passed_y = y_test[pred == 1]
    blocked_y = y_test[pred == 0]

    print(
        f"S1 NGATE SPLIT total={n} train={len(train)} test={len(test)} cut_entry={cut_entry} "
        f"train_last={train.entry_date.iloc[-1]} test_first={test.entry_date.iloc[0]} embargo={W}"
    )
    print(
        f"S1 NGATE THRESH C40={c40:.6f} C60={c60:.6f} Q40={q40:.6f} Q60={q60:.6f} "
        f"train_non_neutral_rate={prevalence_train:.6f} test_non_neutral_rate={prevalence_test:.6f}"
    )
    print(
        f"S1 NGATE OOS threshold={threshold:.2f} pass_rate={pass_rate:.6f} roc_auc={roc:.6f} ap={ap:.6f} "
        f"balanced_acc={bal_acc:.6f} precision={precision:.6f} recall={recall:.6f} "
        f"tn={tn} fp={fp} fn={fn} tp={tp}"
    )
    print(
        f"S1 NGATE PASS n={len(passed)} actual_non_neutral_rate={float(passed_y.mean()) if len(passed_y) else float('nan'):.6f} "
        f"C_mean={float(passed.C.mean()) if len(passed) else float('nan'):.6f} Q_mean={float(passed.Q.mean()) if len(passed) else float('nan'):.6f}"
    )
    print(
        f"S1 NGATE BLOCK n={len(blocked)} actual_non_neutral_rate={float(blocked_y.mean()) if len(blocked_y) else float('nan'):.6f} "
        f"neutral_rate={float(1.0-blocked_y.mean()) if len(blocked_y) else float('nan'):.6f} "
        f"C_mean={float(blocked.C.mean()) if len(blocked) else float('nan'):.6f} Q_mean={float(blocked.Q.mean()) if len(blocked) else float('nan'):.6f}"
    )

    result = test.copy()
    result["actual_non_neutral"] = y_test
    result["p_non_neutral"] = test_prob
    result["gate_pass"] = pred
    result.to_csv(OUTPUT, index=False)
    print(f"S1 NGATE OUTPUT file={OUTPUT} rows={len(result)}")
    print("S1 NGATE COMPLETE scaler_train_only=true cq_thresholds_train_only=true test_thresholds_frozen=true oos_threshold_tuned=false")


if __name__ == "__main__":
    main()

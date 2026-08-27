from __future__ import annotations

from pathlib import Path
import os
import random

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.metrics import balanced_accuracy_score, confusion_matrix, precision_recall_fscore_support

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table
from .strategy1_layer1_state import build_samples, chronological_purged_split
from .strategy1_layer1_threshold_audit import build_outcome_table, rolling_labels

TICKER = os.environ.get("FUTUREVIEW_TICKER", "TSLA")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
WINDOW = int(os.environ.get("FUTUREVIEW_LAYER1_WINDOW", "30"))
INPUT_LENGTH = int(os.environ.get("FUTUREVIEW_LAYER1_INPUT", "60"))
REFERENCE_DAYS = int(os.environ.get("FUTUREVIEW_LAYER1_REFERENCE_DAYS", "60"))
LOW_Q = float(os.environ.get("FUTUREVIEW_LAYER1_LOW_Q", "0.40"))
HIGH_Q = float(os.environ.get("FUTUREVIEW_LAYER1_HIGH_Q", "0.60"))
TRAIN_FRAC = float(os.environ.get("FUTUREVIEW_LAYER1_TRAIN_FRAC", "0.60"))
VAL_FRAC = float(os.environ.get("FUTUREVIEW_LAYER1_VAL_FRAC", "0.20"))
RANDOM_SAMPLES = int(os.environ.get("FUTUREVIEW_A_RANDOM_SAMPLES", "20"))
RANDOM_SEED = int(os.environ.get("FUTUREVIEW_A_RANDOM_SEED", "20260827"))
EPOCHS = int(os.environ.get("FUTUREVIEW_LAYER1_CNN_EPOCHS", "80"))
BATCH_SIZE = int(os.environ.get("FUTUREVIEW_LAYER1_CNN_BATCH", "32"))
LEARNING_RATE = float(os.environ.get("FUTUREVIEW_LAYER1_CNN_LR", "0.001"))
OUTPUT = Path(os.environ.get("FUTUREVIEW_LAYER1_CNN_OUTPUT", "strategy1-layer1-cnn.csv"))

CLASS_NAMES = {-1: "low", 0: "neutral", 1: "high"}
CLASS_TO_INDEX = {-1: 0, 0: 1, 1: 2}
INDEX_TO_CLASS = {0: -1, 1: 0, 2: 1}


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)


class Layer1CNN(nn.Module):
    """Small 1-D CNN over the locked 8 x 60 input; no engineered features."""

    def __init__(self) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv1d(8, 32, kernel_size=5, padding=2),
            nn.ReLU(),
            nn.Conv1d(32, 64, kernel_size=5, padding=2),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Linear(64, 3)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = self.features(x).squeeze(-1)
        return self.head(z)


def _make_labelled_samples(df: pd.DataFrame, windows: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    meta, x = build_samples(df, windows)
    outcomes = build_outcome_table(df, windows)
    labelled = rolling_labels(outcomes, REFERENCE_DAYS).loc[:, [
        "start_index", "label", "C25", "C75", "U25", "U75", "reference_count"
    ]]
    merged = meta.merge(labelled, on="start_index", how="inner", validate="one_to_one")
    if merged.empty:
        raise RuntimeError("no samples remain after joining rolling labels")

    pos = pd.Series(np.arange(len(meta)), index=meta["start_index"].astype(int))
    take = pos.loc[merged["start_index"].astype(int)].to_numpy(dtype=int)
    return merged.reset_index(drop=True), x[take]


def _class_weights(y_train: np.ndarray) -> torch.Tensor:
    counts = np.bincount(y_train, minlength=3).astype(float)
    if np.any(counts == 0):
        raise RuntimeError(f"training split missing a class: counts={counts.tolist()}")
    weights = counts.sum() / (3.0 * counts)
    return torch.tensor(weights, dtype=torch.float32)


def _evaluate(name: str, model: nn.Module, x: np.ndarray, y: np.ndarray, idx: np.ndarray) -> dict[str, np.ndarray]:
    model.eval()
    with torch.no_grad():
        logits = model(torch.tensor(x[idx], dtype=torch.float32))
        probs = torch.softmax(logits, dim=1).cpu().numpy()
    pred_idx = probs.argmax(axis=1)
    y_pred = np.array([INDEX_TO_CLASS[int(i)] for i in pred_idx], dtype=int)
    y_true = np.array([INDEX_TO_CLASS[int(i)] for i in y[idx]], dtype=int)

    bal = balanced_accuracy_score(y_true, y_pred)
    p, r, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=[-1, 0, 1], zero_division=0
    )
    macro_f1 = float(np.mean(f1))
    print(f"S1 LAYER1 CNN METRIC part={name} balanced_accuracy={bal:.6f} macro_f1={macro_f1:.6f}")
    for i, cls in enumerate((-1, 0, 1)):
        print(
            f"S1 LAYER1 CNN CLASS part={name} class={CLASS_NAMES[cls]} support={int(support[i])} "
            f"precision={p[i]:.6f} recall={r[i]:.6f} f1={f1[i]:.6f}"
        )
    cm = confusion_matrix(y_true, y_pred, labels=[-1, 0, 1])
    print(f"S1 LAYER1 CNN CONFUSION part={name} rows=true_low_neutral_high values={cm.tolist()}")

    k = max(1, int(np.ceil(len(idx) * 0.10)))
    top = np.argsort(probs[:, 2])[-k:]
    high_precision = float((y_true[top] == 1).mean())
    base_high_rate = float((y_true == 1).mean())
    lift = high_precision / base_high_rate if base_high_rate > 0 else np.nan
    print(
        f"S1 LAYER1 CNN RANK part={name} top10_n={k} high_precision={high_precision:.6f} "
        f"base_high_rate={base_high_rate:.6f} lift={lift:.6f}"
    )
    return {"prob": probs, "pred": y_pred}


def main() -> None:
    if WINDOW != 30 or INPUT_LENGTH != 60 or REFERENCE_DAYS != 60:
        raise ValueError("Layer-1 CNN is locked to W=30, input=60, reference=60")
    if not (np.isclose(LOW_Q, 0.40) and np.isclose(HIGH_Q, 0.60)):
        raise ValueError("Layer-1 CNN is locked to rolling 40/60 percentile labels")

    seed_everything(RANDOM_SEED)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    paths = build_deterministic_path_table(events)
    windows = build_representation_a_table(
        df,
        paths,
        window=WINDOW,
        stride=1,
        random_samples=RANDOM_SAMPLES,
        random_seed=RANDOM_SEED,
    )
    meta, x = _make_labelled_samples(df, windows)
    split = chronological_purged_split(meta)
    y_class = meta["label"].to_numpy(dtype=int)
    y = np.array([CLASS_TO_INDEX[int(v)] for v in y_class], dtype=np.int64)

    print(
        f"S1 LAYER1 CNN START ticker={TICKER} rows={audit.rows} first={audit.start} last={audit.end} "
        f"W={WINDOW} input={INPUT_LENGTH} channels=8 reference={REFERENCE_DAYS} samples={len(meta)} seed={RANDOM_SEED}"
    )
    print(
        "S1 LAYER1 CNN DEFINITION C=U-B_periodic rolling_percentiles=0.40,0.60 "
        "high=(C>C60 and U>U60) low=(C<C40 and U<U40) neutral=otherwise "
        "input=locked_8x60_price_volume model=conv1d_8-32-64_gap"
    )
    for name in ("train", "val", "test"):
        idx = split[name]
        cls = y_class[idx]
        counts = {k: int((cls == k).sum()) for k in (-1, 0, 1)}
        print(
            f"S1 LAYER1 CNN SPLIT part={name} n={len(idx)} low={counts[-1]} neutral={counts[0]} high={counts[1]} "
            f"first={meta.iloc[idx[0]]['start_date']} last={meta.iloc[idx[-1]]['start_date']}"
        )

    model = Layer1CNN()
    train_idx = split["train"]
    train_ds = TensorDataset(
        torch.tensor(x[train_idx], dtype=torch.float32),
        torch.tensor(y[train_idx], dtype=torch.long),
    )
    generator = torch.Generator().manual_seed(RANDOM_SEED)
    loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, generator=generator)
    criterion = nn.CrossEntropyLoss(weight=_class_weights(y[train_idx]))
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)

    model.train()
    for epoch in range(1, EPOCHS + 1):
        total_loss = 0.0
        total_n = 0
        for xb, yb in loader:
            optimizer.zero_grad(set_to_none=True)
            logits = model(xb)
            loss = criterion(logits, yb)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item()) * len(xb)
            total_n += len(xb)
        if epoch in {1, 10, 20, 40, 60, EPOCHS}:
            print(f"S1 LAYER1 CNN TRAIN epoch={epoch} loss={total_loss / total_n:.6f}")

    out = meta.copy()
    out["partition"] = "purged"
    out["p_low"] = np.nan
    out["p_neutral"] = np.nan
    out["p_high"] = np.nan
    out["prediction"] = np.nan
    out.loc[train_idx, "partition"] = "train"

    for name in ("val", "test"):
        idx = split[name]
        result = _evaluate(name, model, x, y, idx)
        out.loc[idx, "partition"] = name
        out.loc[idx, "p_low"] = result["prob"][:, 0]
        out.loc[idx, "p_neutral"] = result["prob"][:, 1]
        out.loc[idx, "p_high"] = result["prob"][:, 2]
        out.loc[idx, "prediction"] = result["pred"]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT, index=False)
    print(f"S1 LAYER1 CNN OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 LAYER1 CNN COMPLETE")


if __name__ == "__main__":
    main()

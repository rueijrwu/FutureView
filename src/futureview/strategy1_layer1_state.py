from __future__ import annotations

from pathlib import Path
import os

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, confusion_matrix, precision_recall_fscore_support

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_cq_data import HORIZON
from .strategy1_deterministic_paths import build_deterministic_path_table
from .strategy1_representation_a import build_representation_a_table

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
OUTPUT = Path(os.environ.get("FUTUREVIEW_LAYER1_OUTPUT", "strategy1-layer1-state.csv"))

NORMALIZATION_WINDOWS = (5, 10, 20, 60)
CLASS_NAMES = {-1: "low", 0: "neutral", 1: "high"}


def make_locked_price_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    if not {"close", "volume"}.issubset(df.columns):
        raise ValueError("df must contain close and volume")

    close = df["close"].astype(float)
    volume = df["volume"].astype(float)
    out = pd.DataFrame(index=df.index)
    for n in NORMALIZATION_WINDOWS:
        past_close_sum = close.shift(1).rolling(n, min_periods=n).sum()
        past_volume_sum = volume.shift(1).rolling(n, min_periods=n).sum()
        out[f"price_{n}"] = close / past_close_sum.replace(0.0, np.nan)
        out[f"volume_{n}"] = volume / past_volume_sum.replace(0.0, np.nan)
    return out.replace([np.inf, -np.inf], np.nan)


def _feature_columns() -> list[str]:
    return [
        *(f"price_{n}" for n in NORMALIZATION_WINDOWS),
        *(f"volume_{n}" for n in NORMALIZATION_WINDOWS),
    ]


def build_samples(df: pd.DataFrame, windows: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    features = make_locked_price_volume_features(df)
    cols = _feature_columns()
    metadata: list[dict[str, float | int | str]] = []
    tensors: list[np.ndarray] = []

    for row in windows.sort_values("start_index").itertuples(index=False):
        start = int(row.start_index)
        anchor = start - 1
        first_input = anchor - INPUT_LENGTH + 1
        if first_input < 0:
            continue
        block = features.loc[first_input:anchor, cols].to_numpy(dtype=float)
        if block.shape != (INPUT_LENGTH, len(cols)) or not np.isfinite(block).all():
            continue

        metadata.append(
            {
                "ticker": TICKER,
                "start_index": start,
                "end_index": int(row.end_index),
                "anchor_index": anchor,
                "start_date": row.start_date,
                "end_date": row.end_date,
                "U": float(row.U),
                "B_periodic": float(row.B_periodic),
                "C": float(row.U - row.B_periodic),
                "path_count": int(row.path_count),
                "dependency_end": int(row.end_index) + HORIZON,
            }
        )
        tensors.append(block.T)

    if not tensors:
        raise RuntimeError("no valid Layer-1 samples")
    return pd.DataFrame(metadata), np.stack(tensors, axis=0)


def apply_rolling_labels(meta: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Label each target from prior completed outcomes in the last REFERENCE_DAYS sessions."""
    labels = np.full(len(meta), 99, dtype=int)
    valid = np.zeros(len(meta), dtype=bool)
    c_low = np.full(len(meta), np.nan)
    c_high = np.full(len(meta), np.nan)
    u_low = np.full(len(meta), np.nan)
    u_high = np.full(len(meta), np.nan)
    ref_count = np.zeros(len(meta), dtype=int)

    min_ref = max(10, REFERENCE_DAYS // 3)
    for i, row in enumerate(meta.itertuples(index=False)):
        s = int(row.start_index)
        ref = meta.loc[
            (meta["dependency_end"] >= s - REFERENCE_DAYS)
            & (meta["dependency_end"] < s)
        ]
        if len(ref) < min_ref:
            continue

        c_low[i] = float(ref["C"].quantile(LOW_Q))
        c_high[i] = float(ref["C"].quantile(HIGH_Q))
        u_low[i] = float(ref["U"].quantile(LOW_Q))
        u_high[i] = float(ref["U"].quantile(HIGH_Q))
        ref_count[i] = len(ref)
        valid[i] = True

        if row.C > c_high[i] and row.U > u_high[i]:
            labels[i] = 1
        elif row.C < c_low[i] and row.U < u_low[i]:
            labels[i] = -1
        else:
            labels[i] = 0

    out = meta.copy()
    out["C_low"] = c_low
    out["C_high"] = c_high
    out["U_low"] = u_low
    out["U_high"] = u_high
    out["reference_count"] = ref_count
    out["label"] = labels
    return out, labels, valid


def chronological_purged_split(meta: pd.DataFrame) -> dict[str, np.ndarray]:
    n = len(meta)
    if n < 100:
        raise RuntimeError("too few samples for chronological Layer-1 split")
    val_pos = max(1, min(n - 2, int(np.floor(n * TRAIN_FRAC))))
    test_pos = max(val_pos + 1, min(n - 1, int(np.floor(n * (TRAIN_FRAC + VAL_FRAC)))))
    val_start = int(meta.iloc[val_pos]["start_index"])
    test_start = int(meta.iloc[test_pos]["start_index"])

    start = meta["start_index"].to_numpy(dtype=int)
    dep_end = meta["dependency_end"].to_numpy(dtype=int)
    train = np.flatnonzero((start < val_start) & (dep_end < val_start))
    val = np.flatnonzero((start >= val_start) & (start < test_start) & (dep_end < test_start))
    test = np.flatnonzero(start >= test_start)
    if min(len(train), len(val), len(test)) == 0:
        raise RuntimeError("purged chronological split produced an empty partition")
    return {"train": train, "val": val, "test": test}


def _print_partition(name: str, idx: np.ndarray, labels: np.ndarray, meta: pd.DataFrame) -> None:
    y = labels[idx]
    counts = {k: int((y == k).sum()) for k in (-1, 0, 1)}
    print(
        f"S1 LAYER1 SPLIT part={name} n={len(idx)} low={counts[-1]} neutral={counts[0]} high={counts[1]} "
        f"first={meta.iloc[idx[0]]['start_date']} last={meta.iloc[idx[-1]]['start_date']}"
    )


def _evaluate(name: str, y_true: np.ndarray, y_pred: np.ndarray, prob_high: np.ndarray) -> None:
    bal = balanced_accuracy_score(y_true, y_pred)
    p, r, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=[-1, 0, 1], zero_division=0
    )
    macro_f1 = float(np.mean(f1))
    print(f"S1 LAYER1 METRIC part={name} balanced_accuracy={bal:.6f} macro_f1={macro_f1:.6f}")
    for i, cls in enumerate((-1, 0, 1)):
        print(
            f"S1 LAYER1 CLASS part={name} class={CLASS_NAMES[cls]} support={int(support[i])} "
            f"precision={p[i]:.6f} recall={r[i]:.6f} f1={f1[i]:.6f}"
        )
    cm = confusion_matrix(y_true, y_pred, labels=[-1, 0, 1])
    print(f"S1 LAYER1 CONFUSION part={name} rows=true_low_neutral_high values={cm.tolist()}")

    k = max(1, int(np.ceil(len(y_true) * 0.10)))
    top = np.argsort(prob_high)[-k:]
    high_precision_at_top10 = float((y_true[top] == 1).mean())
    base_high_rate = float((y_true == 1).mean())
    lift = high_precision_at_top10 / base_high_rate if base_high_rate > 0 else np.nan
    print(
        f"S1 LAYER1 RANK part={name} top10_n={k} high_precision={high_precision_at_top10:.6f} "
        f"base_high_rate={base_high_rate:.6f} lift={lift:.6f}"
    )


def main() -> None:
    if WINDOW != 30:
        raise ValueError("Layer-1 experiment is currently locked to W=30")
    if INPUT_LENGTH != 60:
        raise ValueError("Layer-1 input is currently locked to 60 sessions")
    if REFERENCE_DAYS != 60:
        raise ValueError("Layer-1 reference is currently locked to 60 sessions")
    if not (0.0 < LOW_Q < HIGH_Q < 1.0):
        raise ValueError("invalid percentile thresholds")
    if not (0.0 < TRAIN_FRAC < 1.0 and 0.0 < VAL_FRAC < 1.0 and TRAIN_FRAC + VAL_FRAC < 1.0):
        raise ValueError("invalid chronological split fractions")

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
    meta, x = build_samples(df, windows)
    meta, labels, valid = apply_rolling_labels(meta)
    meta = meta.loc[valid].reset_index(drop=True)
    x = x[valid]
    labels = labels[valid]
    split = chronological_purged_split(meta)

    print(
        f"S1 LAYER1 START ticker={TICKER} rows={audit.rows} first={audit.start} last={audit.end} "
        f"W={WINDOW} input={INPUT_LENGTH} channels=8 reference={REFERENCE_DAYS} samples={len(meta)} horizon={HORIZON}"
    )
    print(
        f"S1 LAYER1 DEFINITION C=U-B_periodic rolling_percentiles={LOW_Q:.2f},{HIGH_Q:.2f} "
        "high=(C>C_high and U>U_high) low=(C<C_low and U<U_low) neutral=otherwise "
        "reference=prior_completed_outcomes_only input=past_only"
    )
    for name in ("train", "val", "test"):
        _print_partition(name, split[name], labels, meta)

    train_idx = split["train"]
    if len(np.unique(labels[train_idx])) != 3:
        raise RuntimeError("training split does not contain all three Layer-1 classes")

    x_flat = x.reshape(len(x), -1)
    model = LogisticRegression(max_iter=5000, class_weight="balanced", solver="lbfgs")
    model.fit(x_flat[train_idx], labels[train_idx])
    class_to_col = {int(cls): i for i, cls in enumerate(model.classes_)}

    out = meta.copy()
    out["partition"] = "purged"
    out["p_low"] = np.nan
    out["p_neutral"] = np.nan
    out["p_high"] = np.nan
    out["prediction"] = np.nan

    for name in ("val", "test"):
        idx = split[name]
        prob = model.predict_proba(x_flat[idx])
        pred = model.predict(x_flat[idx])
        p_high = prob[:, class_to_col[1]]
        _evaluate(name, labels[idx], pred, p_high)
        out.loc[idx, "partition"] = name
        out.loc[idx, "p_low"] = prob[:, class_to_col[-1]]
        out.loc[idx, "p_neutral"] = prob[:, class_to_col[0]]
        out.loc[idx, "p_high"] = p_high
        out.loc[idx, "prediction"] = pred

    out.loc[train_idx, "partition"] = "train"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT, index=False)
    print(f"S1 LAYER1 OUTPUT file={OUTPUT} rows={len(out)}")
    print("S1 LAYER1 COMPLETE")


if __name__ == "__main__":
    main()

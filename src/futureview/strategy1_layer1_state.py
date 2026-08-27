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
LOW_Q = float(os.environ.get("FUTUREVIEW_LAYER1_LOW_Q", "0.25"))
HIGH_Q = float(os.environ.get("FUTUREVIEW_LAYER1_HIGH_Q", "0.75"))
TRAIN_FRAC = float(os.environ.get("FUTUREVIEW_LAYER1_TRAIN_FRAC", "0.60"))
VAL_FRAC = float(os.environ.get("FUTUREVIEW_LAYER1_VAL_FRAC", "0.20"))
RANDOM_SAMPLES = int(os.environ.get("FUTUREVIEW_A_RANDOM_SAMPLES", "20"))
RANDOM_SEED = int(os.environ.get("FUTUREVIEW_A_RANDOM_SEED", "20260827"))
OUTPUT = Path(os.environ.get("FUTUREVIEW_LAYER1_OUTPUT", "strategy1-layer1-state.csv"))

NORMALIZATION_WINDOWS = (5, 10, 20, 60)
CLASS_NAMES = {-1: "low", 0: "neutral", 1: "high"}


def make_locked_price_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    """Locked causal price/volume normalization agreed for the project.

    For N in {5,10,20,60}:
      price_N(t)  = P_t / sum_{i=1..N} P_{t-i}
      volume_N(t) = V_t / sum_{i=1..N} V_{t-i}
    """
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
    """Align past-only 8x60 inputs with next-W retrospective outcome labels."""
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

        # Current project definition: C = U - B_periodic.
        c_value = float(row.U - row.B_periodic)
        dependency_end = int(row.end_index) + HORIZON
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
                "C": c_value,
                "path_count": int(row.path_count),
                "dependency_end": dependency_end,
            }
        )
        # Keep channel-first semantics: 8 x 60, flatten only at baseline-model fit time.
        tensors.append(block.T)

    if not tensors:
        raise RuntimeError("no valid Layer-1 samples")
    return pd.DataFrame(metadata), np.stack(tensors, axis=0)


def chronological_purged_split(meta: pd.DataFrame) -> dict[str, np.ndarray]:
    """Chronological 60/20/20 nominal split with future-label purge at boundaries."""
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


def fit_thresholds(meta: pd.DataFrame, train_idx: np.ndarray) -> dict[str, float]:
    train = meta.iloc[train_idx]
    return {
        "C25": float(train["C"].quantile(LOW_Q)),
        "C75": float(train["C"].quantile(HIGH_Q)),
        "U25": float(train["U"].quantile(LOW_Q)),
        "U75": float(train["U"].quantile(HIGH_Q)),
    }


def apply_state_labels(meta: pd.DataFrame, thresholds: dict[str, float]) -> np.ndarray:
    c = meta["C"].to_numpy(dtype=float)
    u = meta["U"].to_numpy(dtype=float)
    labels = np.zeros(len(meta), dtype=int)
    labels[(c > thresholds["C75"]) & (u > thresholds["U75"])] = 1
    labels[(c < thresholds["C25"]) & (u < thresholds["U25"])] = -1
    return labels


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
    print(
        f"S1 LAYER1 RANK part={name} top10_n={k} high_precision={high_precision_at_top10:.6f} "
        f"base_high_rate={base_high_rate:.6f} lift={(high_precision_at_top10 / base_high_rate if base_high_rate > 0 else np.nan):.6f}"
    )


def main() -> None:
    if WINDOW != 30:
        raise ValueError("Layer-1 experiment is currently locked to W=30")
    if INPUT_LENGTH != 60:
        raise ValueError("Layer-1 input is currently locked to 60 sessions")
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
    split = chronological_purged_split(meta)
    thresholds = fit_thresholds(meta, split["train"])
    labels = apply_state_labels(meta, thresholds)

    print(
        f"S1 LAYER1 START ticker={TICKER} rows={audit.rows} first={audit.start} last={audit.end} "
        f"W={WINDOW} input={INPUT_LENGTH} channels=8 samples={len(meta)} horizon={HORIZON}"
    )
    print(
        "S1 LAYER1 DEFINITION C=U-B_periodic high=(C>C75 and U>U75) "
        "low=(C<C25 and U<U25) neutral=otherwise thresholds=train_only input=past_only"
    )
    print(
        f"S1 LAYER1 THRESHOLD C25={thresholds['C25']:.6f} C75={thresholds['C75']:.6f} "
        f"U25={thresholds['U25']:.6f} U75={thresholds['U75']:.6f}"
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
    out["label"] = labels
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

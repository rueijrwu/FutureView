from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch
from torch import nn

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_cq_data import (
    HORIZON,
    LOOKBACK,
    REFERENCE_LOOKBACK,
    ADDON2_SPACING_TOLERANCE,
    make_input_windows,
)
from . import strategy1_reference_distribution as base
from .strategy1_reference_distribution_fast import _simulate_path_fast

TICKER = "SMH"
DATA_PERIOD = "5y"
SEEDS = (20260823, 20260824, 20260825)
EPOCHS = 100
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
N_FOLDS = 4
PURGE_DAYS = HORIZON
MIN_TRAIN_SAMPLES = 40
MIN_TEST_SAMPLES = 10


@dataclass(frozen=True)
class EntryTargets:
    raw_indices: np.ndarray
    addon1_present: np.ndarray
    addon2_present: np.ndarray
    partial_present: np.ndarray


def make_entry_targets(df: pd.DataFrame) -> EntryTargets:
    events = add_strategy1_events(df).reset_index(drop=True)
    base._prepare_worker_state(events)
    _simulate_path_fast.cache_clear()

    indices: list[int] = []
    addon1: list[float] = []
    addon2: list[float] = []
    partial: list[float] = []

    for raw_entry in np.flatnonzero(events["entry_candidate"].to_numpy(dtype=bool)):
        entry = int(raw_entry)
        end = entry + HORIZON - 1
        if end >= len(events):
            continue
        history_start = max(0, entry - REFERENCE_LOOKBACK + 1)
        configs = base._addon_reference_sets(history_start, entry)
        by_path: dict[tuple[int, int, int, int, int, int], int] = {}
        for config in configs:
            level_indices = tuple(level[0] for level in config)
            _, _, _, executed_addons, path = _simulate_path_fast(
                entry, end, level_indices, ADDON2_SPACING_TOLERANCE
            )
            by_path.setdefault(path, int(executed_addons))
        if not by_path:
            continue
        paths = list(by_path.keys())
        counts = list(by_path.values())
        indices.append(entry)
        addon1.append(float(any(c >= 1 for c in counts)))
        addon2.append(float(any(c >= 2 for c in counts)))
        partial.append(float(any(p[3] >= 0 for p in paths)))

    return EntryTargets(
        raw_indices=np.asarray(indices, dtype=int),
        addon1_present=np.asarray(addon1, dtype=np.float32),
        addon2_present=np.asarray(addon2, dtype=np.float32),
        partial_present=np.asarray(partial, dtype=np.float32),
    )


def _make_folds(raw_indices: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    raw_indices = np.asarray(raw_indices, dtype=int)
    order = np.argsort(raw_indices)
    remaining = len(order) - MIN_TRAIN_SAMPLES
    test_size = max(MIN_TEST_SAMPLES, remaining // N_FOLDS)
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    test_start = MIN_TRAIN_SAMPLES
    while test_start < len(order) and len(folds) < N_FOLDS:
        test_end = min(len(order), test_start + test_size)
        test = order[test_start:test_end]
        if len(test) < MIN_TEST_SAMPLES:
            break
        first_test_raw = int(raw_indices[test[0]])
        train_candidates = order[:test_start]
        train = train_candidates[raw_indices[train_candidates] + PURGE_DAYS < first_test_raw]
        if len(train) >= MIN_TRAIN_SAMPLES:
            folds.append((train, test))
        test_start = test_end
    if not folds:
        raise RuntimeError("no complete purged chronological classifier folds")
    return folds


class StrategyStateCNN(nn.Module):
    """First-version multi-label classifier on agreed 8x60 price/volume input."""

    def __init__(self, in_channels: int = 8) -> None:
        super().__init__()
        self.branches = nn.ModuleList([
            nn.Sequential(nn.Conv1d(in_channels, 8, kernel_size=k, padding="same"), nn.GELU())
            for k in (5, 10, 20)
        ])
        self.fusion = nn.Sequential(
            nn.Conv1d(24, 16, kernel_size=3, padding="same"),
            nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
            nn.Flatten(),
            nn.Linear(16, 8),
            nn.GELU(),
        )
        self.head = nn.Linear(8, 3)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = torch.cat([branch(x) for branch in self.branches], dim=1)
        return self.head(self.fusion(z))


def _auc(y: np.ndarray, score: np.ndarray) -> float:
    y = np.asarray(y, dtype=int)
    score = np.asarray(score, dtype=float)
    pos = np.flatnonzero(y == 1)
    neg = np.flatnonzero(y == 0)
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    # Pairwise probability that a random positive receives a higher score.
    diff = score[pos][:, None] - score[neg][None, :]
    return float((np.mean(diff > 0.0) + 0.5 * np.mean(diff == 0.0)))


def _fit(x: torch.Tensor, y: torch.Tensor, seed: int) -> StrategyStateCNN:
    torch.manual_seed(seed)
    np.random.seed(seed)
    model = StrategyStateCNN(x.shape[1]).cpu()
    opt = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    loss_fn = nn.BCEWithLogitsLoss()  # deliberately unweighted first version
    model.train()
    for _ in range(EPOCHS):
        opt.zero_grad(set_to_none=True)
        loss = loss_fn(model(x), y)
        loss.backward()
        opt.step()
    return model


def main() -> None:
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    targets = make_entry_targets(df)
    x_np, kept_raw = make_input_windows(df, targets.raw_indices)
    lookup = {int(r): i for i, r in enumerate(targets.raw_indices)}
    idx = np.asarray([lookup[int(r)] for r in kept_raw], dtype=int)
    y_np = np.stack([
        targets.addon1_present[idx],
        targets.addon2_present[idx],
        targets.partial_present[idx],
    ], axis=1).astype(np.float32)

    x = torch.from_numpy(x_np)
    y = torch.from_numpy(y_np)
    folds = _make_folds(kept_raw)

    names = ("addon1_present", "addon2_present", "partial_present")
    print(
        f"S1 CLASSIFIER_V1 DATA ticker={TICKER} rows={audit.rows} entries={len(kept_raw)} "
        f"lookback={LOOKBACK} horizon={HORIZON} folds={len(folds)}"
    )
    print(
        "S1 CLASSIFIER_V1 INPUT source=close,volume scales=5,10,20,60 "
        "normalization=current_value/rolling_sum_N channels=8 sequence_length=60 "
        "no_handcrafted_statistics=true"
    )
    print(
        "S1 CLASSIFIER_V1 TARGET type=entry_level_multilabel "
        "heads=addon1_present,addon2_present,partial_present "
        "definition=exists_at_least_one_unique_realized_path_with_event"
    )
    for j, name in enumerate(names):
        print(f"S1 CLASSIFIER_V1 PREVALENCE head={name} positives={int(y_np[:, j].sum())} total={len(y_np)} rate={y_np[:, j].mean():.6f}")
    print(
        "S1 CLASSIFIER_V1 TRAIN loss=unweighted_BCE heads_equal_weight=true "
        f"epochs={EPOCHS} lr={LEARNING_RATE} weight_decay={WEIGHT_DECAY} seeds={len(SEEDS)}"
    )

    all_auc: dict[str, list[float]] = {name: [] for name in names}
    for fold_id, (train, test) in enumerate(folds, start=1):
        print(f"S1 CLASSIFIER_V1 FOLD id={fold_id} train={len(train)} test={len(test)}")
        for seed in SEEDS:
            model = _fit(x[train], y[train], seed)
            model.eval()
            with torch.no_grad():
                logits = model(x[test]).numpy().astype(float)
            parts = []
            for j, name in enumerate(names):
                auc = _auc(y_np[test, j], logits[:, j])
                if np.isfinite(auc):
                    all_auc[name].append(auc)
                parts.append(f"{name}_auc={auc:.6f}")
            print(f"S1 CLASSIFIER_V1 FOLD_RESULT id={fold_id} seed={seed} " + " ".join(parts))

    for name in names:
        vals = np.asarray(all_auc[name], dtype=float)
        if len(vals):
            print(
                f"S1 CLASSIFIER_V1 SUMMARY head={name} n={len(vals)} "
                f"auc_mean={vals.mean():.6f} auc_median={np.median(vals):.6f} "
                f"above_random={int(np.sum(vals > 0.5))}/{len(vals)}"
            )
        else:
            print(f"S1 CLASSIFIER_V1 SUMMARY head={name} n=0")
    print("S1 CLASSIFIER_V1 COMPLETE")


if __name__ == "__main__":
    main()

from __future__ import annotations

import numpy as np
import torch
from torch import nn

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1_classifier_path_labels import TICKER, DATA_PERIOD
from .strategy1_cq_data import make_input_windows
from .strategy1 import add_strategy1_events
from .strategy1_cq_data import HORIZON, REFERENCE_LOOKBACK, ADDON2_SPACING_TOLERANCE
from . import strategy1_reference_distribution as base
from .strategy1_reference_distribution_fast import _simulate_path_fast

SEEDS = (20260826, 20260827, 20260828)
EPOCHS = 100
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
MIN_TRAIN_ENTRIES = 40
MIN_TEST_ENTRIES = 20
N_FOLDS = 4
PURGE_DAYS = HORIZON


def _build_path_labels(df):
    events = add_strategy1_events(df).reset_index(drop=True)
    base._prepare_worker_state(events)
    _simulate_path_fast.cache_clear()

    rows = []
    for raw_entry in np.flatnonzero(events["entry_candidate"].to_numpy(dtype=bool)):
        entry = int(raw_entry)
        end = entry + HORIZON - 1
        if end >= len(events):
            continue
        history_start = max(0, entry - REFERENCE_LOOKBACK + 1)
        configs = base._addon_reference_sets(history_start, entry)
        unique = {}
        for config in configs:
            level_indices = tuple(int(level[0]) for level in config)
            ret, _, _, executed_addons, path = _simulate_path_fast(
                entry, end, level_indices, ADDON2_SPACING_TOLERANCE
            )
            if path in unique:
                continue
            _, _, _, exit5_index, _, _ = path
            unique[path] = (int(executed_addons), int(exit5_index >= 0), float(ret))
        for path, (addon, partial, ret) in unique.items():
            rows.append((entry, addon, partial, ret, path))
    return rows


def _make_entry_folds(entries: np.ndarray):
    entries = np.asarray(sorted(set(int(v) for v in entries)), dtype=int)
    if len(entries) < MIN_TRAIN_ENTRIES + MIN_TEST_ENTRIES:
        raise RuntimeError("insufficient distinct entries for chronological folds")
    remaining = len(entries) - MIN_TRAIN_ENTRIES
    test_size = max(MIN_TEST_ENTRIES, remaining // N_FOLDS)
    folds = []
    test_start = MIN_TRAIN_ENTRIES
    while test_start < len(entries) and len(folds) < N_FOLDS:
        test_entries = entries[test_start:min(len(entries), test_start + test_size)]
        if len(test_entries) < MIN_TEST_ENTRIES:
            break
        first_test = int(test_entries[0])
        train_entries = entries[:test_start]
        train_entries = train_entries[train_entries + PURGE_DAYS < first_test]
        if len(train_entries) >= MIN_TRAIN_ENTRIES:
            folds.append((train_entries, test_entries))
        test_start += test_size
    if not folds:
        raise RuntimeError("no chronological entry-grouped folds")
    return folds


class PathCNN(nn.Module):
    def __init__(self, n_classes: int) -> None:
        super().__init__()
        self.branches = nn.ModuleList([
            nn.Sequential(nn.Conv1d(8, 8, kernel_size=k, padding="same"), nn.GELU())
            for k in (5, 10, 20)
        ])
        self.fusion = nn.Sequential(
            nn.Conv1d(24, 16, kernel_size=3, padding="same"),
            nn.GELU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(16, 8),
            nn.GELU(),
            nn.Linear(8, n_classes),
        )

    def forward(self, x):
        z = torch.cat([b(x) for b in self.branches], dim=1)
        return self.head(self.fusion(z))


def _fit(x_train, y_train, n_classes, seed):
    torch.manual_seed(seed)
    np.random.seed(seed)
    model = PathCNN(n_classes).cpu()
    opt = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    loss_fn = nn.CrossEntropyLoss()
    model.train()
    for _ in range(EPOCHS):
        opt.zero_grad(set_to_none=True)
        loss = loss_fn(model(x_train), y_train)
        loss.backward()
        opt.step()
    return model


def _confusion(y_true, y_pred, n_classes):
    out = np.zeros((n_classes, n_classes), dtype=int)
    for a, b in zip(y_true, y_pred):
        out[int(a), int(b)] += 1
    return out


def _run_task(name, x, entries, labels, folds, n_classes):
    all_acc = []
    for fold_id, (train_entries, test_entries) in enumerate(folds, start=1):
        train_mask = np.isin(entries, train_entries)
        test_mask = np.isin(entries, test_entries)
        x_train = x[train_mask]
        y_train = torch.from_numpy(labels[train_mask].astype(np.int64))
        x_test = x[test_mask]
        y_test = labels[test_mask]
        print(
            f"S1 PATH_CNN FOLD task={name} id={fold_id} train_entries={len(train_entries)} "
            f"test_entries={len(test_entries)} train_samples={int(train_mask.sum())} test_samples={int(test_mask.sum())}"
        )
        for seed in SEEDS:
            model = _fit(x_train, y_train, n_classes, seed)
            model.eval()
            with torch.no_grad():
                pred = model(x_test).argmax(dim=1).cpu().numpy()
            acc = float((pred == y_test).mean())
            cm = _confusion(y_test, pred, n_classes)
            all_acc.append(acc)
            print(
                f"S1 PATH_CNN RESULT task={name} fold={fold_id} seed={seed} accuracy={acc:.6f} "
                f"confusion={cm.tolist()}"
            )
    print(
        f"S1 PATH_CNN SUMMARY task={name} runs={len(all_acc)} "
        f"accuracy_mean={np.mean(all_acc):.6f} accuracy_median={np.median(all_acc):.6f}"
    )


def main() -> None:
    torch.set_num_threads(2)
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    rows = _build_path_labels(df)
    raw_entries = np.asarray([r[0] for r in rows], dtype=int)
    addon = np.asarray([r[1] for r in rows], dtype=int)
    partial = np.asarray([r[2] for r in rows], dtype=int)

    unique_entries = np.asarray(sorted(set(raw_entries.tolist())), dtype=int)
    x_unique_np, kept_entries = make_input_windows(df, unique_entries)
    x_lookup = {int(e): x_unique_np[i] for i, e in enumerate(kept_entries)}

    keep = np.asarray([int(e) in x_lookup for e in raw_entries], dtype=bool)
    entries = raw_entries[keep]
    addon = addon[keep]
    partial = partial[keep]
    x = torch.from_numpy(np.stack([x_lookup[int(e)] for e in entries]))

    folds = _make_entry_folds(entries)
    print(
        f"S1 PATH_CNN DATA ticker={TICKER} rows={audit.rows} samples={len(entries)} "
        f"distinct_entries={len(set(entries.tolist()))} folds={len(folds)}"
    )
    print(
        "S1 PATH_CNN INPUT channels=8 sequence_length=60 source=normalized_close_volume "
        "scales=5,10,20,60 execution_labels_not_input=true"
    )
    print(
        "S1 PATH_CNN SPLIT chronological=true grouped_by_entry=true purge_days=60 "
        "same_entry_never_crosses_train_test=true"
    )
    print(
        "S1 PATH_CNN TRAINING separate_models=true class_weighting=false oversampling=false "
        "engineered_statistics=false"
    )

    _run_task("addon", x, entries, addon, folds, 3)
    _run_task("partial", x, entries, partial, folds, 2)
    print("S1 PATH_CNN COMPLETE")


if __name__ == "__main__":
    main()

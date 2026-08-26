from __future__ import annotations

import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1_cq_data import HORIZON, REFERENCE_LOOKBACK, ADDON2_SPACING_TOLERANCE, make_cq_labels, make_input_windows
from .strategy1_smh_cnn_close_volume_multiscale import _make_cq_folds
from . import strategy1_reference_distribution as base
from .strategy1 import add_strategy1_events
from .strategy1_reference_distribution_fast import _simulate_path_fast

TICKER = "SMH"
DATA_PERIOD = "5y"


def _entry_returns(entry: int, end: int) -> np.ndarray:
    history_start = max(0, entry - REFERENCE_LOOKBACK + 1)
    configs = base._addon_reference_sets(history_start, entry)
    by_path: dict[tuple[int, int, int, int, int, int], float] = {}
    for config in configs:
        level_indices = tuple(level[0] for level in config)
        ret, _, _, _, path = _simulate_path_fast(entry, end, level_indices, ADDON2_SPACING_TOLERANCE)
        by_path.setdefault(path, float(ret))
    return np.asarray(list(by_path.values()), dtype=float)


def _stats(r: np.ndarray) -> dict[str, float]:
    return {
        "n_paths": float(len(r)),
        "mean": float(np.mean(r)),
        "median": float(np.median(r)),
        "std": float(np.std(r, ddof=0)),
        "q10": float(np.quantile(r, 0.10)),
        "q25": float(np.quantile(r, 0.25)),
        "q75": float(np.quantile(r, 0.75)),
        "q90": float(np.quantile(r, 0.90)),
        "min": float(np.min(r)),
        "max": float(np.max(r)),
        "frac_pos": float(np.mean(r > 0.0)),
        "frac_nonneg": float(np.mean(r >= 0.0)),
        "frac_neg": float(np.mean(r < 0.0)),
        "iqr": float(np.quantile(r, 0.75) - np.quantile(r, 0.25)),
    }


def _summarize(name: str, vals: np.ndarray) -> str:
    return (
        f"metric={name} mean={np.mean(vals):.6f} median={np.median(vals):.6f} "
        f"q25={np.quantile(vals,0.25):.6f} q75={np.quantile(vals,0.75):.6f} "
        f"min={np.min(vals):.6f} max={np.max(vals):.6f}"
    )


def main() -> None:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    labels = make_cq_labels(df)
    x, kept_raw = make_input_windows(df, labels.raw_indices)
    pos = {int(r): i for i, r in enumerate(labels.raw_indices)}
    keep = np.asarray([pos[int(r)] for r in kept_raw], dtype=int)
    raw_indices = labels.raw_indices[keep]
    dates = pd.to_datetime(labels.dates[keep])

    events = add_strategy1_events(df).reset_index(drop=True)
    base._prepare_worker_state(events)
    _simulate_path_fast.cache_clear()

    folds = _make_cq_folds(raw_indices)
    print(f"S1 ENTRY_DIST DATA ticker={TICKER} rows={audit.rows} samples={len(raw_indices)} folds={len(folds)}")

    for fold_id, (_, test) in enumerate(folds, start=1):
        rows: list[dict[str, float]] = []
        for j in test:
            entry = int(raw_indices[j])
            r = _entry_returns(entry, entry + HORIZON - 1)
            s = _stats(r)
            rows.append(s)
            print(
                "S1 ENTRY_DIST ENTRY "
                f"fold={fold_id} date={pd.Timestamp(dates[j]).date()} raw_index={entry} "
                f"n_paths={int(s['n_paths'])} mean={s['mean']:.6f} median={s['median']:.6f} "
                f"std={s['std']:.6f} q10={s['q10']:.6f} q25={s['q25']:.6f} "
                f"q75={s['q75']:.6f} q90={s['q90']:.6f} min={s['min']:.6f} max={s['max']:.6f} "
                f"frac_pos={s['frac_pos']:.6f} frac_neg={s['frac_neg']:.6f} iqr={s['iqr']:.6f}"
            )
        keys = ["mean","median","std","q10","q25","q75","q90","frac_pos","frac_neg","iqr","n_paths"]
        print(f"S1 ENTRY_DIST FOLD fold={fold_id} test_dates={dates[test[0]].date()}..{dates[test[-1]].date()} n_entries={len(test)}")
        for k in keys:
            vals = np.asarray([row[k] for row in rows], dtype=float)
            print(f"S1 ENTRY_DIST SUMMARY fold={fold_id} {_summarize(k, vals)}")

    print("S1 ENTRY_DIST COMPLETE")


if __name__ == "__main__":
    main()

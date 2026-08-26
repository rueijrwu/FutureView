from __future__ import annotations

import numpy as np
import pandas as pd

from . import strategy1_reference_distribution as base
from .strategy1 import add_strategy1_events
from .strategy1_cq_data import HORIZON, REFERENCE_LOOKBACK, ADDON2_SPACING_TOLERANCE
from .strategy1_reference_distribution_fast import _simulate_path_fast

LOOKBACKS = (60, 120, 180)
GRID_Q = np.linspace(0.0, 1.0, 11)


def _entry_returns(entry: int, end: int) -> np.ndarray:
    history_start = max(0, entry - REFERENCE_LOOKBACK + 1)
    configs = base._addon_reference_sets(history_start, entry)
    by_path: dict[tuple[int, int, int, int, int, int], float] = {}
    for config in configs:
        level_indices = tuple(level[0] for level in config)
        ret, _, _, _, path = _simulate_path_fast(entry, end, level_indices, ADDON2_SPACING_TOLERANCE)
        by_path.setdefault(path, float(ret))
    return np.asarray(list(by_path.values()), dtype=float)


def _daily_map(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    events = add_strategy1_events(df).reset_index(drop=True)
    base._prepare_worker_state(events)
    _simulate_path_fast.cache_clear()
    dates = pd.to_datetime(events["date"]).to_numpy()
    n = len(events)
    out = np.zeros((n, len(GRID_Q)), dtype=np.float32)
    is_legal = np.zeros(n, dtype=bool)
    maturity = np.full(n, -1, dtype=int)

    for entry in np.flatnonzero(events["entry_candidate"].to_numpy(dtype=bool)):
        end = int(entry) + HORIZON - 1
        if end >= n:
            continue
        returns = _entry_returns(int(entry), end)
        if returns.size == 0 or not np.all(np.isfinite(returns)):
            continue
        out[int(entry)] = np.quantile(returns, GRID_Q).astype(np.float32)
        is_legal[int(entry)] = True
        maturity[int(entry)] = end
    return dates, out, maturity


def main() -> None:
    df = base._download_history("SMH")
    dates, daily, maturity = _daily_map(df)

    # Match prior 3-fold chronology on the last 123 matured legal entries approximately.
    legal_idx = np.flatnonzero(maturity >= 0)
    legal_idx = legal_idx[maturity[legal_idx] < len(df)]
    # last 123 entries split 41/41/41 to align prior entry-distribution diagnostic
    legal_idx = legal_idx[-123:]
    folds = np.array_split(legal_idx, 3)

    print(f"S1 DAILY_MAP DATA ticker=SMH rows={len(df)} legal_entries={len(legal_idx)} qgrid={len(GRID_Q)}")
    for fi, test_entries in enumerate(folds, start=1):
        start = int(test_entries[0]); end = int(test_entries[-1])
        print(f"S1 DAILY_MAP FOLD fold={fi} test_dates={dates[start]}..{dates[end]} n_test_entries={len(test_entries)}")
        for lb in LOOKBACKS:
            vals = []
            densities = []
            matured_counts = []
            for t in test_entries:
                a = max(0, int(t)-lb)
                # only outcomes already matured strictly before decision date t
                idx = np.arange(a, int(t))
                usable = idx[(maturity[idx] >= 0) & (maturity[idx] < int(t))]
                window = np.zeros((lb, daily.shape[1]), dtype=np.float32)
                src = idx[-lb:]
                offset = lb-len(src)
                if len(src):
                    mask = (maturity[src] >= 0) & (maturity[src] < int(t))
                    window[offset:][mask] = daily[src[mask]]
                vals.append(window)
                densities.append(float(np.count_nonzero(np.linalg.norm(window, axis=1))) / lb)
                matured_counts.append(int(len(usable)))
            x = np.stack(vals)
            nonzero = np.linalg.norm(x, axis=2) > 0
            abs_mean = float(np.abs(x[nonzero]).mean()) if np.any(nonzero) else 0.0
            print(
                f"S1 DAILY_MAP SUMMARY fold={fi} lookback={lb} shape={x.shape} "
                f"density_mean={np.mean(densities):.6f} density_median={np.median(densities):.6f} "
                f"matured_count_mean={np.mean(matured_counts):.3f} matured_count_min={np.min(matured_counts)} "
                f"matured_count_max={np.max(matured_counts)} nonzero_abs_mean={abs_mean:.6f}"
            )
    print("S1 DAILY_MAP COMPLETE")


if __name__ == "__main__":
    main()

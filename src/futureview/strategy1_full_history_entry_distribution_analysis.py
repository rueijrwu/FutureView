from __future__ import annotations

import json
import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1_cq_data import HORIZON, REFERENCE_LOOKBACK, ADDON2_SPACING_TOLERANCE
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
    q10, q25, q50, q75, q90 = np.quantile(r, [0.10, 0.25, 0.50, 0.75, 0.90])
    return {
        "n_paths": float(len(r)),
        "L": float(np.min(r)),
        "mu": float(np.mean(r)),
        "U": float(np.max(r)),
        "median": float(q50),
        "std": float(np.std(r, ddof=0)),
        "q10": float(q10),
        "q25": float(q25),
        "q75": float(q75),
        "q90": float(q90),
        "iqr": float(q75 - q25),
        "frac_pos": float(np.mean(r > 0.0)),
        "frac_neg": float(np.mean(r < 0.0)),
    }


def main() -> None:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    base._prepare_worker_state(events)
    _simulate_path_fast.cache_clear()

    dates = pd.to_datetime(events["date"])
    rows: list[dict[str, object]] = []

    for entry in np.flatnonzero(events["entry_candidate"].to_numpy(dtype=bool)):
        end = int(entry) + HORIZON - 1
        if end >= len(events):
            continue
        r = _entry_returns(int(entry), end)
        if r.size == 0 or not np.all(np.isfinite(r)):
            continue
        s = _stats(r)
        row: dict[str, object] = {
            "date": str(pd.Timestamp(dates.iloc[int(entry)]).date()),
            "raw_index": int(entry),
            **s,
            "returns": [float(x) for x in r.tolist()],
        }
        rows.append(row)
        print(
            "S1 FULL_ENTRY ENTRY "
            f"date={row['date']} raw_index={entry} n_paths={int(s['n_paths'])} "
            f"L={s['L']:.6f} mu={s['mu']:.6f} U={s['U']:.6f} median={s['median']:.6f} "
            f"std={s['std']:.6f} q10={s['q10']:.6f} q25={s['q25']:.6f} q75={s['q75']:.6f} q90={s['q90']:.6f} "
            f"iqr={s['iqr']:.6f} frac_pos={s['frac_pos']:.6f} frac_neg={s['frac_neg']:.6f}"
        )

    table = pd.DataFrame([{k: v for k, v in row.items() if k != "returns"} for row in rows])
    table.to_csv("strategy1-full-history-entry-distribution-summary.csv", index=False)
    with open("strategy1-full-history-entry-distributions.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)

    print(
        f"S1 FULL_ENTRY COMPLETE ticker={TICKER} rows={audit.rows} legal_entries={len(rows)} "
        f"first_date={rows[0]['date'] if rows else 'NA'} last_date={rows[-1]['date'] if rows else 'NA'}"
    )


if __name__ == "__main__":
    main()

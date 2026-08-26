from __future__ import annotations

import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_cq_data import HORIZON, REFERENCE_LOOKBACK, ADDON2_SPACING_TOLERANCE
from . import strategy1_reference_distribution as base
from .strategy1_reference_distribution_fast import _simulate_path_fast

TICKER = "SMH"
DATA_PERIOD = "5y"


def main() -> None:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    base._prepare_worker_state(events)
    _simulate_path_fast.cache_clear()

    rows: list[dict[str, object]] = []
    dates = pd.to_datetime(events["date"])

    for entry in np.flatnonzero(events["entry_candidate"].to_numpy(dtype=bool)):
        entry = int(entry)
        end = entry + HORIZON - 1
        if end >= len(events):
            continue

        history_start = max(0, entry - REFERENCE_LOOKBACK + 1)
        configs = base._addon_reference_sets(history_start, entry)
        by_path: dict[tuple[int, int, int, int, int, int], tuple[float, int]] = {}

        for config in configs:
            level_indices = tuple(level[0] for level in config)
            ret, _, _, executed_addons, path = _simulate_path_fast(
                entry,
                end,
                level_indices,
                ADDON2_SPACING_TOLERANCE,
            )
            by_path.setdefault(path, (float(ret), int(executed_addons)))

        for path, (ret, addon_count) in by_path.items():
            rows.append(
                {
                    "date": str(pd.Timestamp(dates.iloc[entry]).date()),
                    "raw_index": entry,
                    "class_label": int(addon_count),
                    "return": float(ret),
                    "path": str(path),
                }
            )

    table = pd.DataFrame(rows)
    if table.empty:
        raise RuntimeError("No classifier-label rows were produced")

    table.to_csv("strategy1-classifier-labels.csv", index=False)

    print(
        f"S1 CLASSIFIER_LABEL COMPLETE ticker={TICKER} rows={audit.rows} "
        f"paths={len(table)} entries={table['raw_index'].nunique()}"
    )
    for label in (0, 1, 2):
        sub = table.loc[table["class_label"] == label]
        if sub.empty:
            print(f"S1 CLASSIFIER_LABEL class={label} paths=0 entries=0")
            continue
        returns = sub["return"].to_numpy(dtype=float)
        print(
            "S1 CLASSIFIER_LABEL "
            f"class={label} paths={len(sub)} entries={sub['raw_index'].nunique()} "
            f"mean={returns.mean():.6f} median={np.median(returns):.6f} "
            f"min={returns.min():.6f} max={returns.max():.6f} "
            f"frac_pos={(returns > 0.0).mean():.6f}"
        )


if __name__ == "__main__":
    main()

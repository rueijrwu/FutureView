from __future__ import annotations

import numpy as np
import pandas as pd

from . import strategy1_reference_distribution as base
from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_cq_data import ADDON2_SPACING_TOLERANCE, HORIZON, REFERENCE_LOOKBACK
from .strategy1_reference_distribution_fast import _simulate_path_fast

TICKER = "SMH"
DATA_PERIOD = "5y"
OUTPUT = "strategy1-path-labels.csv"


def main() -> None:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    dates = pd.to_datetime(events["date"]).reset_index(drop=True)
    base._prepare_worker_state(events)
    _simulate_path_fast.cache_clear()

    rows: list[dict[str, object]] = []
    legal_entries = 0

    for raw_entry in np.flatnonzero(events["entry_candidate"].to_numpy(dtype=bool)):
        entry = int(raw_entry)
        end = entry + HORIZON - 1
        if end >= len(events):
            continue
        legal_entries += 1

        history_start = max(0, entry - REFERENCE_LOOKBACK + 1)
        configs = base._addon_reference_sets(history_start, entry)

        # One independent sample per unique realized execution path. Multiple
        # reference configurations that execute identically are not duplicated.
        unique: dict[tuple[int, int, int, int, int, int], dict[str, object]] = {}
        for config in configs:
            level_indices = tuple(int(level[0]) for level in config)
            ret, efficiency, exposure_days, executed_addons, path = _simulate_path_fast(
                entry, end, level_indices, ADDON2_SPACING_TOLERANCE
            )
            if path in unique:
                continue

            _, addon1_index, addon2_index, exit5_index, exit10_index, horizon_exit_index = path
            partial_exit = int(exit5_index >= 0)
            if exit10_index >= 0:
                terminal_exit = "full"
            elif horizon_exit_index >= 0:
                terminal_exit = "horizon"
            else:
                terminal_exit = "none"

            unique[path] = {
                "entry_date": str(pd.Timestamp(dates.iloc[entry]).date()),
                "raw_index": entry,
                "path_id": "|".join(str(int(v)) for v in path),
                "requested_addon_levels": len(level_indices),
                "reference_indices": "|".join(str(v) for v in level_indices),
                "executed_addons": int(executed_addons),
                "addon1_index": int(addon1_index),
                "addon2_index": int(addon2_index),
                "partial_exit": partial_exit,
                "partial_exit_index": int(exit5_index),
                "full_exit_index": int(exit10_index),
                "horizon_exit_index": int(horizon_exit_index),
                "terminal_exit": terminal_exit,
                "campaign_return": float(ret),
                "efficiency": float(efficiency),
                "exposure_days": float(exposure_days),
            }

        rows.extend(unique.values())

    table = pd.DataFrame(rows).sort_values(["raw_index", "path_id"]).reset_index(drop=True)
    if table.empty:
        raise RuntimeError("No Strategy 1 path-level labels were produced")
    if table["path_id"].duplicated().any():
        raise RuntimeError("path_id must be globally unique")

    table.to_csv(OUTPUT, index=False)

    print(
        f"S1 PATH_LABEL COMPLETE ticker={TICKER} rows={audit.rows} legal_entries={legal_entries} "
        f"samples={len(table)} distinct_entries={table['raw_index'].nunique()} output={OUTPUT}"
    )
    print(
        "S1 PATH_LABEL SEMANTICS one_unique_realized_path_one_sample=true "
        "same_entry_may_have_multiple_samples=true execution_fields_are_labels_not_inputs=true"
    )

    for addon in (0, 1, 2):
        sub = table.loc[table["executed_addons"] == addon]
        print(
            f"S1 PATH_LABEL ADDON executed={addon} samples={len(sub)} "
            f"entries={sub['raw_index'].nunique()}"
        )

    for partial in (0, 1):
        sub = table.loc[table["partial_exit"] == partial]
        print(
            f"S1 PATH_LABEL PARTIAL value={partial} samples={len(sub)} "
            f"entries={sub['raw_index'].nunique()}"
        )

    print("S1 PATH_LABEL JOINT_BEGIN")
    joint = (
        table.groupby(["executed_addons", "partial_exit", "terminal_exit"], dropna=False)
        .agg(samples=("path_id", "size"), entries=("raw_index", "nunique"))
        .reset_index()
    )
    for row in joint.itertuples(index=False):
        print(
            f"S1 PATH_LABEL JOINT addon={int(row.executed_addons)} partial={int(row.partial_exit)} "
            f"terminal={row.terminal_exit} samples={int(row.samples)} entries={int(row.entries)}"
        )
    print("S1 PATH_LABEL JOINT_END")


if __name__ == "__main__":
    main()

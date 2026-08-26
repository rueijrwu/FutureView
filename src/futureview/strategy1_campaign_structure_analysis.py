from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_cq_data import HORIZON, REFERENCE_LOOKBACK, ADDON2_SPACING_TOLERANCE
from . import strategy1_reference_distribution as base
from .strategy1_reference_distribution_fast import _simulate_path_fast

TICKER = "SMH"
DATA_PERIOD = "5y"


def _stats(values: list[float]) -> dict[str, float]:
    x = np.asarray(values, dtype=float)
    if x.size == 0:
        return {"n": 0.0}
    q10, q25, q50, q75, q90 = np.quantile(x, [0.10, 0.25, 0.50, 0.75, 0.90])
    return {
        "n": float(x.size),
        "mean": float(x.mean()),
        "median": float(q50),
        "std": float(x.std(ddof=0)),
        "q10": float(q10),
        "q25": float(q25),
        "q75": float(q75),
        "q90": float(q90),
        "min": float(x.min()),
        "max": float(x.max()),
        "frac_pos": float((x > 0.0).mean()),
    }


def _print_group(prefix: str, key: str, values: list[float], entries: set[int]) -> None:
    s = _stats(values)
    if not values:
        print(f"S1 STRUCT {prefix} key={key} paths=0 entries=0")
        return
    print(
        f"S1 STRUCT {prefix} key={key} paths={int(s['n'])} entries={len(entries)} "
        f"mean={s['mean']:.6f} median={s['median']:.6f} std={s['std']:.6f} "
        f"q10={s['q10']:.6f} q25={s['q25']:.6f} q75={s['q75']:.6f} q90={s['q90']:.6f} "
        f"min={s['min']:.6f} max={s['max']:.6f} frac_pos={s['frac_pos']:.6f}"
    )


def main() -> None:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    base._prepare_worker_state(events)
    _simulate_path_fast.cache_clear()

    addon_returns: dict[int, list[float]] = defaultdict(list)
    addon_entries: dict[int, set[int]] = defaultdict(set)
    partial_returns: dict[str, list[float]] = defaultdict(list)
    partial_entries: dict[str, set[int]] = defaultdict(set)
    terminal_returns: dict[str, list[float]] = defaultdict(list)
    terminal_entries: dict[str, set[int]] = defaultdict(set)
    joint_returns: dict[tuple[int, str, str], list[float]] = defaultdict(list)
    joint_entries: dict[tuple[int, str, str], set[int]] = defaultdict(set)

    legal_entry_count = 0
    unique_path_count = 0

    for entry in np.flatnonzero(events["entry_candidate"].to_numpy(dtype=bool)):
        entry = int(entry)
        end = entry + HORIZON - 1
        if end >= len(events):
            continue
        legal_entry_count += 1
        history_start = max(0, entry - REFERENCE_LOOKBACK + 1)
        configs = base._addon_reference_sets(history_start, entry)

        # A realized path is counted once even if multiple reference configs lead to it.
        unique: dict[tuple[int, int, int, int, int, int], tuple[float, int]] = {}
        for config in configs:
            level_indices = tuple(level[0] for level in config)
            ret, _, _, executed_addons, path = _simulate_path_fast(
                entry, end, level_indices, ADDON2_SPACING_TOLERANCE
            )
            unique.setdefault(path, (float(ret), int(executed_addons)))

        unique_path_count += len(unique)
        for path, (ret, executed_addons) in unique.items():
            _, _, _, exit5_index, exit10_index, horizon_exit_index = path
            partial = "yes" if exit5_index >= 0 else "no"
            terminal = "full" if exit10_index >= 0 else "horizon"
            if exit10_index < 0 and horizon_exit_index < 0:
                terminal = "none"

            addon_returns[executed_addons].append(ret)
            addon_entries[executed_addons].add(entry)
            partial_returns[partial].append(ret)
            partial_entries[partial].add(entry)
            terminal_returns[terminal].append(ret)
            terminal_entries[terminal].add(entry)
            key = (executed_addons, partial, terminal)
            joint_returns[key].append(ret)
            joint_entries[key].add(entry)

    print(
        f"S1 STRUCT COMPLETE ticker={TICKER} rows={audit.rows} legal_entries={legal_entry_count} "
        f"unique_realized_paths={unique_path_count}"
    )

    for k in (0, 1, 2):
        _print_group("ADDON", str(k), addon_returns[k], addon_entries[k])

    for k in ("no", "yes"):
        _print_group("PARTIAL", k, partial_returns[k], partial_entries[k])

    for k in ("full", "horizon", "none"):
        _print_group("TERMINAL", k, terminal_returns[k], terminal_entries[k])

    print("S1 STRUCT JOINT_BEGIN")
    for key in sorted(joint_returns):
        addon, partial, terminal = key
        _print_group(
            "JOINT",
            f"addon{addon}|partial={partial}|terminal={terminal}",
            joint_returns[key],
            joint_entries[key],
        )
    print("S1 STRUCT JOINT_END")


if __name__ == "__main__":
    main()

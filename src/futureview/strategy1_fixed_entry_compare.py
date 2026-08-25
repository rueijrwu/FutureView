from __future__ import annotations

import numpy as np

from . import strategy1_reference_distribution as base
from . import strategy1_reference_distribution_fast as fast
from . import strategy1_reference_distribution_formal as formal
from .data import download_spy_daily, validate_daily_ohlcv

DATA_PERIOD = "5y"
WINDOW = 60
ENTRY_OFFSETS = (0, 20, 40)


def _fixed_three_entry_return(close: np.ndarray, start: int, end: int) -> float:
    final_price = float(close[end])
    wealth = 0.0
    for offset in ENTRY_OFFSETS:
        entry_price = float(close[start + offset])
        wealth += (1.0 / 3.0) * (final_price / entry_price)
    return wealth - 1.0


def _formal_60d_row(start: int) -> dict[str, object]:
    _, _, entry_indices, _, _, _ = base._require_state()
    end = start + WINDOW - 1
    entries = base._slice_indices(entry_indices, start, end)

    config_cache: dict[int, tuple[tuple[tuple[int, float], ...], ...]] = {}
    local_max_count_cache: dict[int, int] = {}
    for raw_entry in entries:
        entry = int(raw_entry)
        local_max_count_cache[entry] = len(base._window_local_maxima(start, entry))
        config_cache[entry] = base._addon_reference_sets(start, entry)

    return formal._summarize_window(
        start,
        end,
        entries,
        config_cache,
        local_max_count_cache,
    )


def main() -> None:
    df = download_spy_daily(period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = base.add_strategy1_events(df).reset_index(drop=True)
    base._prepare_worker_state(events)
    formal._simulate_path = fast._simulate_path_fast

    _, close, _, _, _, _ = base._require_state()
    anchor_count = len(events) - WINDOW + 1

    upper_values: list[float] = []
    lower_values: list[float] = []
    fixed_values: list[float] = []
    gaps: list[float] = []
    captures: list[float] = []

    for start in range(anchor_count):
        end = start + WINDOW - 1
        row = _formal_60d_row(start)
        if int(row["return"]["n"]) == 0:  # type: ignore[index]
            continue

        lower = float(row["return"]["lower"])  # type: ignore[index]
        upper = float(row["return"]["upper"])  # type: ignore[index]
        fixed = _fixed_three_entry_return(close, start, end)
        gap = upper - fixed
        width = upper - lower
        capture = (fixed - lower) / width if width > 0.0 else 0.0

        lower_values.append(lower)
        upper_values.append(upper)
        fixed_values.append(fixed)
        gaps.append(gap)
        captures.append(capture)

    upper = np.asarray(upper_values, dtype=float)
    lower = np.asarray(lower_values, dtype=float)
    fixed = np.asarray(fixed_values, dtype=float)
    gap = np.asarray(gaps, dtype=float)
    capture = np.asarray(captures, dtype=float)

    if upper.size == 0:
        raise RuntimeError("no non-empty 60D reference windows")

    print(
        "S1 FIXED_ENTRY_COMPARE DATA "
        f"period={DATA_PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"window={WINDOW} anchors={anchor_count} evaluated={upper.size}"
    )
    print(
        "S1 FIXED_ENTRY_COMPARE RULE "
        "baseline=fixed_three_equal_entries_hold_to_horizon "
        f"entry_offsets={','.join(str(offset) for offset in ENTRY_OFFSETS)} "
        "capital_per_entry=0.333333 strategy_upper=formal_max2_spacing20_unique_realized_paths"
    )
    print(
        "S1 FIXED_ENTRY_COMPARE RESULT "
        f"upper_mean={upper.mean():.6f} upper_median={np.median(upper):.6f} "
        f"fixed_mean={fixed.mean():.6f} fixed_median={np.median(fixed):.6f} "
        f"gap_mean={gap.mean():.6f} gap_median={np.median(gap):.6f} "
        f"upper_beats_fixed_rate={np.mean(upper > fixed):.3f} "
        f"fixed_positive_rate={np.mean(fixed > 0.0):.3f} "
        f"upper_positive_rate={np.mean(upper > 0.0):.3f}"
    )
    print(
        "S1 FIXED_ENTRY_COMPARE CAPTURE "
        f"capture_mean={capture.mean():.6f} capture_median={np.median(capture):.6f} "
        f"capture_p25={np.quantile(capture, 0.25):.6f} "
        f"capture_p75={np.quantile(capture, 0.75):.6f} "
        f"fixed_above_midpoint_rate={np.mean(fixed > (lower + upper) / 2.0):.3f}"
    )
    print("S1 FIXED_ENTRY_COMPARE COMPLETE")


if __name__ == "__main__":
    main()

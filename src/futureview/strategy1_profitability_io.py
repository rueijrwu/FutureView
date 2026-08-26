from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os

import numpy as np
import pandas as pd

from . import strategy1_reference_distribution as base
from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_cq_data import ADDON2_SPACING_TOLERANCE, HORIZON, REFERENCE_LOOKBACK
from .strategy1_reference_distribution_fast import _simulate_path_fast

TICKER = os.environ.get("FUTUREVIEW_TICKER", "SMH")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
REGIME_WINDOW = int(os.environ.get("FUTUREVIEW_REGIME_WINDOW", "60"))
REGIME_STRIDE = int(os.environ.get("FUTUREVIEW_REGIME_STRIDE", "1"))
OUTPUT = Path(os.environ.get("FUTUREVIEW_PROFITABILITY_IO_OUTPUT", "strategy1-profitability-io.npz"))
META_OUTPUT = OUTPUT.with_suffix(".json")

N_ADDON_CLASSES = 3
N_EXIT_CLASSES = 2
N_CATEGORIES = N_ADDON_CLASSES * N_EXIT_CLASSES


@dataclass(frozen=True)
class ProfitabilityIO:
    sequence: np.ndarray  # [window, category, calendar, slot, campaign]
    profit: np.ndarray  # [window, category, calendar, slot]
    mask: np.ndarray  # [window, category, calendar, slot]
    entry_index: np.ndarray  # [window, category, calendar, slot]
    window_start: np.ndarray  # [window]
    window_end: np.ndarray  # [window]
    lower: np.ndarray  # [window]
    upper: np.ndarray  # [window]
    path_count: np.ndarray  # [window]
    max_paths_per_cell: int


def _category(executed_addons: int, partial_exit: int) -> int:
    if executed_addons not in (0, 1, 2):
        raise ValueError(f"unexpected executed_addons={executed_addons}")
    exit_count = 2 if partial_exit else 1
    return executed_addons * N_EXIT_CLASSES + (exit_count - 1)


def _exposure_sequence(
    entry: int,
    addon1: int,
    addon2: int,
    partial: int,
    full_exit: int,
    horizon_exit: int,
    horizon: int = HORIZON,
) -> np.ndarray:
    """Reconstruct Strategy-1 capital-exposure fraction from realized event indices."""
    seq = np.zeros(horizon, dtype=np.float32)
    exposure = 1.0 / 3.0
    seq[0] = exposure

    event_by_index: dict[int, list[str]] = {}
    for idx, name in (
        (addon1, "addon"),
        (addon2, "addon"),
        (partial, "partial"),
        (full_exit, "full"),
        (horizon_exit, "horizon"),
    ):
        if idx >= 0:
            event_by_index.setdefault(int(idx), []).append(name)

    for rel in range(1, horizon):
        raw = entry + rel
        # Simulator priority is full exit > partial exit > addon. Horizon liquidation
        # happens after the loop and therefore sets terminal exposure to zero.
        events = event_by_index.get(raw, [])
        if "full" in events:
            exposure = 0.0
        elif "partial" in events:
            exposure *= 0.5
        elif "addon" in events:
            exposure += 1.0 / 3.0
        if "horizon" in events:
            exposure = 0.0
        seq[rel] = exposure
    return seq


def build_path_table(events: pd.DataFrame) -> pd.DataFrame:
    base._prepare_worker_state(events)
    _simulate_path_fast.cache_clear()
    rows: list[dict[str, object]] = []

    for raw_entry in np.flatnonzero(events["entry_candidate"].to_numpy(dtype=bool)):
        entry = int(raw_entry)
        end = entry + HORIZON - 1
        if end >= len(events):
            continue

        history_start = max(0, entry - REFERENCE_LOOKBACK + 1)
        configs = base._addon_reference_sets(history_start, entry)
        unique: dict[tuple[int, int, int, int, int, int], dict[str, object]] = {}

        for config in configs:
            level_indices = tuple(int(level[0]) for level in config)
            ret, _, _, executed_addons, path = _simulate_path_fast(
                entry, end, level_indices, ADDON2_SPACING_TOLERANCE
            )
            if path in unique:
                continue
            _, addon1, addon2, partial, full_exit, horizon_exit = path
            partial_flag = int(partial >= 0)
            seq = _exposure_sequence(
                entry, addon1, addon2, partial, full_exit, horizon_exit
            )
            unique[path] = {
                "entry_index": entry,
                "executed_addons": int(executed_addons),
                "partial_exit": partial_flag,
                "category": _category(int(executed_addons), partial_flag),
                "campaign_return": float(ret),
                "sequence": seq,
                "path_id": "|".join(str(int(v)) for v in path),
            }
        rows.extend(unique.values())

    table = pd.DataFrame(rows).sort_values(["entry_index", "category", "path_id"]).reset_index(drop=True)
    if table.empty:
        raise RuntimeError("No legal Strategy-1 paths were produced")
    if table["path_id"].duplicated().any():
        raise RuntimeError("path_id must be globally unique")
    return table


def build_profitability_io(
    events: pd.DataFrame,
    path_table: pd.DataFrame,
    regime_window: int,
    stride: int = 1,
) -> ProfitabilityIO:
    if regime_window <= 0 or stride <= 0:
        raise ValueError("regime_window and stride must be positive")

    grouped = path_table.groupby(["entry_index", "category"], sort=False)
    multiplicities = grouped.size()
    max_paths_per_cell = int(multiplicities.max())

    valid_last_entry = int(path_table["entry_index"].max())
    starts = np.arange(0, valid_last_entry - regime_window + 2, stride, dtype=np.int32)
    if len(starts) == 0:
        raise RuntimeError("regime window is longer than available completed-entry history")

    shape = (len(starts), N_CATEGORIES, regime_window, max_paths_per_cell)
    sequence = np.zeros(shape + (HORIZON,), dtype=np.float32)
    profit = np.zeros(shape, dtype=np.float32)
    mask = np.zeros(shape, dtype=np.uint8)
    entry_index = np.full(shape, -1, dtype=np.int32)
    lower = np.full(len(starts), np.nan, dtype=np.float32)
    upper = np.full(len(starts), np.nan, dtype=np.float32)
    path_count = np.zeros(len(starts), dtype=np.int32)

    by_entry: dict[int, pd.DataFrame] = {
        int(k): g for k, g in path_table.groupby("entry_index", sort=False)
    }

    for wi, start in enumerate(starts):
        end = int(start + regime_window - 1)
        returns: list[float] = []
        for calendar_offset, raw_entry in enumerate(range(int(start), end + 1)):
            day = by_entry.get(raw_entry)
            if day is None:
                continue
            for category, cat_rows in day.groupby("category", sort=False):
                cat = int(category)
                for slot, row in enumerate(cat_rows.itertuples(index=False)):
                    if slot >= max_paths_per_cell:
                        raise AssertionError("slot overflow")
                    sequence[wi, cat, calendar_offset, slot] = np.asarray(row.sequence, dtype=np.float32)
                    profit[wi, cat, calendar_offset, slot] = float(row.campaign_return)
                    mask[wi, cat, calendar_offset, slot] = 1
                    entry_index[wi, cat, calendar_offset, slot] = raw_entry
                    returns.append(float(row.campaign_return))
        if returns:
            lower[wi] = float(np.min(returns))
            upper[wi] = float(np.max(returns))
            path_count[wi] = len(returns)

    observed = int(mask.sum())
    expected = int(path_count.sum())
    if observed != expected:
        raise RuntimeError(f"mask/path_count mismatch observed={observed} expected={expected}")

    return ProfitabilityIO(
        sequence=sequence,
        profit=profit,
        mask=mask,
        entry_index=entry_index,
        window_start=starts,
        window_end=starts + regime_window - 1,
        lower=lower,
        upper=upper,
        path_count=path_count,
        max_paths_per_cell=max_paths_per_cell,
    )


def save_profitability_io(io: ProfitabilityIO, output: Path, metadata: dict[str, object]) -> None:
    np.savez_compressed(
        output,
        sequence=io.sequence,
        profit=io.profit,
        mask=io.mask,
        entry_index=io.entry_index,
        window_start=io.window_start,
        window_end=io.window_end,
        lower=io.lower,
        upper=io.upper,
        path_count=io.path_count,
    )
    metadata = dict(metadata)
    metadata.update(
        {
            "schema_version": 1,
            "sequence_shape": list(io.sequence.shape),
            "profit_shape": list(io.profit.shape),
            "mask_shape": list(io.mask.shape),
            "max_paths_per_cell": io.max_paths_per_cell,
            "campaign_horizon": HORIZON,
            "n_categories": N_CATEGORIES,
            "category_order": ["A0E1", "A0E2", "A1E1", "A1E2", "A2E1", "A2E2"],
            "path_count_min": int(io.path_count.min()),
            "path_count_median": float(np.median(io.path_count)),
            "path_count_max": int(io.path_count.max()),
        }
    )
    META_OUTPUT.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    path_table = build_path_table(events)

    multiplicity = path_table.groupby(["entry_index", "category"]).size()
    io = build_profitability_io(events, path_table, REGIME_WINDOW, REGIME_STRIDE)
    save_profitability_io(
        io,
        OUTPUT,
        {
            "ticker": TICKER,
            "data_period": DATA_PERIOD,
            "source_rows": int(audit.rows),
            "regime_window": REGIME_WINDOW,
            "regime_stride": REGIME_STRIDE,
            "regime_window_research_frozen": False,
            "unique_paths": int(len(path_table)),
            "distinct_entries": int(path_table["entry_index"].nunique()),
            "cell_multiplicity_p50": float(multiplicity.quantile(0.50)),
            "cell_multiplicity_p90": float(multiplicity.quantile(0.90)),
            "cell_multiplicity_p99": float(multiplicity.quantile(0.99)),
            "cell_multiplicity_max": int(multiplicity.max()),
        },
    )

    valid = io.path_count > 0
    bad_anchor = valid & (io.upper < 0)
    good_anchor = valid & (io.lower > 0)
    mixed = valid & (io.lower < 0) & (io.upper > 0)

    print(
        "S1 PROFITABILITY_IO COMPLETE "
        f"ticker={TICKER} rows={audit.rows} paths={len(path_table)} "
        f"entries={path_table['entry_index'].nunique()} windows={len(io.window_start)} "
        f"W={REGIME_WINDOW} stride={REGIME_STRIDE} research_frozen=false"
    )
    print(
        "S1 PROFITABILITY_IO SHAPE "
        f"sequence={io.sequence.shape} profit={io.profit.shape} mask={io.mask.shape} "
        f"max_paths_per_cell={io.max_paths_per_cell}"
    )
    print(
        "S1 PROFITABILITY_IO MULTIPLICITY "
        f"p50={multiplicity.quantile(0.50):.3f} p90={multiplicity.quantile(0.90):.3f} "
        f"p99={multiplicity.quantile(0.99):.3f} max={multiplicity.max()}"
    )
    print(
        "S1 PROFITABILITY_IO PATH_COUNT "
        f"min={io.path_count.min()} median={np.median(io.path_count):.1f} max={io.path_count.max()}"
    )
    print(
        "S1 PROFITABILITY_IO ANCHORS "
        f"U_lt_0={int(bad_anchor.sum())} L_gt_0={int(good_anchor.sum())} mixed={int(mixed.sum())}"
    )
    print(f"S1 PROFITABILITY_IO OUTPUT npz={OUTPUT} metadata={META_OUTPUT}")


if __name__ == "__main__":
    main()

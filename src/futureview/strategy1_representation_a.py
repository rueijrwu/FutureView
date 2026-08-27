from __future__ import annotations

from pathlib import Path
import os

import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv
from .strategy1 import add_strategy1_events
from .strategy1_cq_data import HORIZON
from .strategy1_profitability_io import build_path_table

TICKER = os.environ.get("FUTUREVIEW_TICKER", "SMH")
DATA_PERIOD = os.environ.get("FUTUREVIEW_DATA_PERIOD", "5y")
WINDOWS = tuple(int(v) for v in os.environ.get("FUTUREVIEW_A_WINDOWS", "20,30,60").split(","))
STRIDE = int(os.environ.get("FUTUREVIEW_A_STRIDE", "5"))
RANDOM_SAMPLES = int(os.environ.get("FUTUREVIEW_A_RANDOM_SAMPLES", "20"))
RANDOM_SEED = int(os.environ.get("FUTUREVIEW_A_RANDOM_SEED", "20260827"))
OUTPUT = Path(os.environ.get("FUTUREVIEW_A_OUTPUT", "strategy1-representation-a.csv"))


def _portfolio_return_to_end(close: np.ndarray, entries: list[int], end: int) -> float:
    """Return on total capital with 1/3 deployed at each supplied entry and remainder kept as cash."""
    if len(entries) > 3:
        raise ValueError("at most three entries are allowed")
    total = 0.0
    for entry in entries:
        if entry < 0 or entry > end:
            raise ValueError("entry must lie within the evaluation window")
        total += (1.0 / 3.0) * float(close[end] / close[entry] - 1.0)
    return total


def _periodic_baseline(close: np.ndarray, start: int, end: int) -> float:
    """Three equal 1/3 investments at evenly spaced times, all marked to the common window end."""
    span = end - start
    entries = [start, start + span // 3, start + (2 * span) // 3]
    return _portfolio_return_to_end(close, entries, end)


def _random_baseline(
    close: np.ndarray,
    start: int,
    end: int,
    *,
    n_samples: int,
    seed: int,
) -> float:
    """Coarse random-entry indicator using a small fixed-seed sample.

    Each sample chooses 1, 2, or 3 distinct entry dates uniformly within the
    evaluation window. Each used entry deploys 1/3 of total capital; unused
    capital remains cash. All positions are marked to the common window end.
    The mean over n_samples is retained only as a simple reference indicator.
    """
    if n_samples <= 0:
        raise ValueError("n_samples must be positive")
    candidates = np.arange(start, end + 1, dtype=int)
    rng = np.random.default_rng(seed)
    returns: list[float] = []
    for _ in range(n_samples):
        k = int(rng.integers(1, 4))
        k = min(k, len(candidates))
        entries = np.sort(rng.choice(candidates, size=k, replace=False)).astype(int).tolist()
        returns.append(_portfolio_return_to_end(close, entries, end))
    return float(np.mean(returns))


def build_representation_a_table(
    df: pd.DataFrame,
    path_table: pd.DataFrame,
    *,
    window: int,
    stride: int,
    random_samples: int,
    random_seed: int,
) -> pd.DataFrame:
    if window <= 1 or stride <= 0:
        raise ValueError("window must be > 1 and stride must be positive")

    close = df["close"].to_numpy(dtype=float)
    valid_last_entry = int(path_table["entry_index"].max())
    rows: list[dict[str, float | int | str]] = []

    for start in range(0, valid_last_entry - window + 2, stride):
        end = start + window - 1
        selected = path_table.loc[
            (path_table["entry_index"] >= start) & (path_table["entry_index"] <= end),
            "campaign_return",
        ].to_numpy(dtype=float)
        if len(selected) == 0:
            continue

        L = float(np.min(selected))
        U = float(np.max(selected))
        b_periodic = _periodic_baseline(close, start, end)
        # Window-specific deterministic seed keeps the coarse indicator reproducible.
        b_random = _random_baseline(
            close,
            start,
            end,
            n_samples=random_samples,
            seed=random_seed + 1000003 * window + start,
        )

        rows.append(
            {
                "ticker": TICKER,
                "window": window,
                "start_index": start,
                "end_index": end,
                "start_date": str(pd.to_datetime(df.at[start, "date"]).date()),
                "end_date": str(pd.to_datetime(df.at[end, "date"]).date()),
                "L": L,
                "U": U,
                "B_periodic": b_periodic,
                "B_random": b_random,
                # Derived diagnostics only; these are not independent Representation A inputs.
                "C": U - L,
                "A_periodic": U - b_periodic,
                "A_random": U - b_random,
                "path_count": int(len(selected)),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError(f"no valid Representation A windows for W={window}")
    return out


def _fmt(x: float) -> str:
    return "nan" if not np.isfinite(x) else f"{x:.6f}"


def _print_distribution(frame: pd.DataFrame, window: int) -> None:
    cols = ["L", "U", "B_periodic", "B_random", "C", "A_periodic", "A_random"]
    for col in cols:
        values = frame[col].to_numpy(dtype=float)
        q = np.quantile(values, [0.05, 0.25, 0.50, 0.75, 0.95])
        print(
            f"S1 REP_A DIST W={window} var={col} mean={values.mean():.6f} std={values.std(ddof=0):.6f} "
            f"p05={q[0]:.6f} p25={q[1]:.6f} p50={q[2]:.6f} p75={q[3]:.6f} p95={q[4]:.6f}"
        )


def _print_correlations(frame: pd.DataFrame, window: int) -> None:
    cols = ["L", "U", "B_periodic", "B_random"]
    pearson = frame[cols].corr(method="pearson")
    spearman = frame[cols].corr(method="spearman")
    for method, corr in (("pearson", pearson), ("spearman", spearman)):
        for i, left in enumerate(cols):
            for right in cols[i + 1 :]:
                print(
                    f"S1 REP_A CORR W={window} method={method} left={left} right={right} "
                    f"r={_fmt(float(corr.loc[left, right]))}"
                )


def _print_chronological(frame: pd.DataFrame, window: int) -> None:
    ordered = frame.sort_values("start_index").reset_index(drop=True)
    parts = np.array_split(np.arange(len(ordered)), 3)
    for part_id, idx in enumerate(parts, start=1):
        if len(idx) == 0:
            continue
        chunk = ordered.iloc[idx]
        print(
            f"S1 REP_A CHRONO W={window} part={part_id} n={len(chunk)} "
            f"L_mean={chunk['L'].mean():.6f} U_mean={chunk['U'].mean():.6f} "
            f"B_periodic_mean={chunk['B_periodic'].mean():.6f} B_random_mean={chunk['B_random'].mean():.6f} "
            f"A_periodic_mean={chunk['A_periodic'].mean():.6f} A_random_mean={chunk['A_random'].mean():.6f}"
        )


def main() -> None:
    if not WINDOWS or any(w <= 1 for w in WINDOWS):
        raise ValueError("FUTUREVIEW_A_WINDOWS must contain integers > 1")
    if RANDOM_SAMPLES <= 0:
        raise ValueError("FUTUREVIEW_A_RANDOM_SAMPLES must be positive")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    path_table = build_path_table(events)

    print(
        f"S1 REP_A START ticker={TICKER} rows={audit.rows} first={audit.start} last={audit.end} "
        f"paths={len(path_table)} entries={path_table['entry_index'].nunique()} horizon={HORIZON} "
        f"windows={','.join(map(str, WINDOWS))} stride={STRIDE} random_samples={RANDOM_SAMPLES} random_seed={RANDOM_SEED}"
    )
    print(
        "S1 REP_A DEFINITION inputs=L,U,B_periodic,B_random "
        "B_periodic=three_equal_one_third_evenly_spaced_entries_common_window_end "
        "B_random=mean_of_small_fixed_seed_samples_each_using_1_to_3_equal_one_third_random_entries_common_window_end "
        "derived_only=C,A_periodic,A_random"
    )

    frames: list[pd.DataFrame] = []
    for window in WINDOWS:
        frame = build_representation_a_table(
            df,
            path_table,
            window=window,
            stride=STRIDE,
            random_samples=RANDOM_SAMPLES,
            random_seed=RANDOM_SEED,
        )
        frames.append(frame)
        print(
            f"S1 REP_A DATA W={window} n={len(frame)} path_count_median={frame['path_count'].median():.1f} "
            f"first={frame['start_date'].iloc[0]} last={frame['end_date'].iloc[-1]}"
        )
        _print_distribution(frame, window)
        _print_correlations(frame, window)
        _print_chronological(frame, window)

    combined = pd.concat(frames, ignore_index=True)
    combined.to_csv(OUTPUT, index=False)
    print(f"S1 REP_A OUTPUT file={OUTPUT} rows={len(combined)}")
    print("S1 REP_A COMPLETE")


if __name__ == "__main__":
    main()

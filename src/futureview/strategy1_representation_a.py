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
OUTPUT = Path(os.environ.get("FUTUREVIEW_A_OUTPUT", "strategy1-representation-a.csv"))


def _random_entry_hold_baseline(close: np.ndarray, start: int, end: int) -> float:
    """Expected return for a uniformly random date in [start, end], held for HORIZON sessions.

    This is a deterministic expectation over all eligible dates, not a Monte Carlo draw.
    It is intentionally a simple random-entry null and does not retain Strategy add/exit rules.
    """
    returns: list[float] = []
    for i in range(start, end + 1):
        j = i + HORIZON - 1
        if j >= len(close):
            continue
        returns.append(float(close[j] / close[i] - 1.0))
    if not returns:
        return float("nan")
    return float(np.mean(returns))


def build_representation_a_table(
    df: pd.DataFrame,
    path_table: pd.DataFrame,
    *,
    window: int,
    stride: int,
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
        b_market = float(close[end] / close[start] - 1.0)
        b_random = _random_entry_hold_baseline(close, start, end)
        if not np.isfinite(b_random):
            continue

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
                "B_market": b_market,
                "B_random": b_random,
                # Derived diagnostics only; these are not independent Representation A inputs.
                "C": U - L,
                "A_market": U - b_market,
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
    cols = ["L", "U", "B_market", "B_random", "C", "A_market", "A_random"]
    for col in cols:
        values = frame[col].to_numpy(dtype=float)
        q = np.quantile(values, [0.05, 0.25, 0.50, 0.75, 0.95])
        print(
            f"S1 REP_A DIST W={window} var={col} mean={values.mean():.6f} std={values.std(ddof=0):.6f} "
            f"p05={q[0]:.6f} p25={q[1]:.6f} p50={q[2]:.6f} p75={q[3]:.6f} p95={q[4]:.6f}"
        )


def _print_correlations(frame: pd.DataFrame, window: int) -> None:
    # Representation A only. Derived C/A variables are deliberately excluded.
    cols = ["L", "U", "B_market", "B_random"]
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
            f"B_market_mean={chunk['B_market'].mean():.6f} B_random_mean={chunk['B_random'].mean():.6f} "
            f"A_market_mean={chunk['A_market'].mean():.6f} A_random_mean={chunk['A_random'].mean():.6f}"
        )


def main() -> None:
    if not WINDOWS or any(w <= 1 for w in WINDOWS):
        raise ValueError("FUTUREVIEW_A_WINDOWS must contain integers > 1")

    df = download_ticker_daily(TICKER, period=DATA_PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = add_strategy1_events(df).reset_index(drop=True)
    path_table = build_path_table(events)

    print(
        f"S1 REP_A START ticker={TICKER} rows={audit.rows} first={audit.start} last={audit.end} "
        f"paths={len(path_table)} entries={path_table['entry_index'].nunique()} horizon={HORIZON} "
        f"windows={','.join(map(str, WINDOWS))} stride={STRIDE}"
    )
    print(
        "S1 REP_A DEFINITION inputs=L,U,B_market,B_random "
        "B_market=window_buy_hold B_random=uniform_random_entry_expected_60_session_hold "
        "derived_only=C,A_market,A_random"
    )

    frames: list[pd.DataFrame] = []
    for window in WINDOWS:
        frame = build_representation_a_table(df, path_table, window=window, stride=STRIDE)
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

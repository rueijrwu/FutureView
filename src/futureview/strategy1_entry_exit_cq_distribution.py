from __future__ import annotations

import os

import numpy as np
import pandas as pd

from .data import download_ticker_daily, validate_daily_ohlcv

PERIOD = os.environ.get("FUTUREVIEW_PERIOD", "5y")
WINDOW = int(os.environ.get("FUTUREVIEW_CQ_WINDOW", "60"))
MIN_OUTCOMES = int(os.environ.get("FUTUREVIEW_CQ_MIN_OUTCOMES", "5"))


def _events(df: pd.DataFrame) -> pd.DataFrame:
    """Build the close-only Entry/Exit event set used by the first-day audit.

    Entry opportunity: every close satisfying the bullish 5/10/20 MA stack.
    Exit5: close < MA5.  Exit10: close < MA10.

    This diagnostic intentionally excludes add-ons, AE/model features, volume,
    cooldown logic, and any classification layer.
    """
    out = df.copy().reset_index(drop=True)
    close = out["close"].astype(float)
    out["ma5"] = close.rolling(5, min_periods=5).mean()
    out["ma10"] = close.rolling(10, min_periods=10).mean()
    out["ma20"] = close.rolling(20, min_periods=20).mean()
    out["entry"] = (
        (close > out["ma5"])
        & (close > out["ma10"])
        & (close > out["ma20"])
        & (out["ma5"] > out["ma10"])
        & (out["ma10"] > out["ma20"])
    ).fillna(False)
    out["exit5"] = (close < out["ma5"]).fillna(False)
    out["exit10"] = (close < out["ma10"]).fillna(False)
    return out


def _entry_outcomes(events: pd.DataFrame) -> pd.DataFrame:
    """Map every legal Entry to its deterministic 40%/60% close-only Exit outcome.

    40% exits at the first post-entry close below MA5.
    The remaining 60% exits at the first post-entry close below MA10.
    If both conditions first occur on the same session, the campaign fully exits
    on that close. Entries without both realized exits inside available history
    are excluded as right-censored observations.
    """
    close = events["close"].to_numpy(dtype=float)
    exit5 = events["exit5"].to_numpy(dtype=bool)
    exit10 = events["exit10"].to_numpy(dtype=bool)
    dates = pd.to_datetime(events["date"])
    rows: list[dict[str, object]] = []

    for entry in np.flatnonzero(events["entry"].to_numpy(dtype=bool)):
        e = int(entry)
        j5: int | None = None
        j10: int | None = None
        for j in range(e + 1, len(events)):
            if j5 is None and exit5[j]:
                j5 = j
            if j10 is None and exit10[j]:
                j10 = j
            if j5 is not None and j10 is not None:
                break
        if j5 is None or j10 is None:
            continue
        # The remaining 60% cannot be sold before the 40% tranche in this audit.
        if j10 < j5:
            j10 = j5
        p0 = close[e]
        p5 = close[j5]
        p10 = close[j10]
        ret = 0.40 * (p5 / p0 - 1.0) + 0.60 * (p10 / p0 - 1.0)
        rows.append(
            {
                "entry_index": e,
                "entry_date": dates.iloc[e],
                "entry_price": p0,
                "exit5_index": j5,
                "exit5_date": dates.iloc[j5],
                "exit5_price": p5,
                "exit10_index": j10,
                "exit10_date": dates.iloc[j10],
                "exit10_price": p10,
                "return": float(ret),
                "holding_sessions": int(j10 - e),
            }
        )
    return pd.DataFrame(rows)


def _window_cq(events: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    """Compute C/Q over all rolling fixed-size historical windows.

    A window population consists of complete Entry->Exit outcomes whose Entry
    occurs inside the window. C and Q use only realized returns:
        L = min(R), U = max(R), mu = mean(R)
        C = U - L
        Q = (U - mu) / C
    """
    if outcomes.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    entry_idx = outcomes["entry_index"].to_numpy(dtype=int)
    returns = outcomes["return"].to_numpy(dtype=float)
    dates = pd.to_datetime(events["date"])

    for start in range(0, len(events) - WINDOW + 1):
        end = start + WINDOW - 1
        mask = (entry_idx >= start) & (entry_idx <= end)
        vals = returns[mask]
        if len(vals) < MIN_OUTCOMES:
            continue
        L = float(np.min(vals))
        U = float(np.max(vals))
        mu = float(np.mean(vals))
        C = U - L
        if not np.isfinite(C) or C <= 1e-12:
            continue
        Q = (U - mu) / C
        rows.append(
            {
                "start": dates.iloc[start],
                "end": dates.iloc[end],
                "n": int(len(vals)),
                "L": L,
                "mu": mu,
                "U": U,
                "C": C,
                "Q": float(Q),
            }
        )
    return pd.DataFrame(rows)


def _skew(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    if len(x) < 3:
        return float("nan")
    s = float(np.std(x, ddof=0))
    if s <= 1e-12:
        return 0.0
    return float(np.mean(((x - np.mean(x)) / s) ** 3))


def _describe(name: str, x: np.ndarray) -> None:
    x = np.asarray(x, dtype=float)
    qs = np.quantile(x, [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95])
    print(
        f"S1 CQ DIST {name} n={len(x)} mean={np.mean(x):.6f} std={np.std(x):.6f} "
        f"min={np.min(x):.6f} p05={qs[0]:.6f} p10={qs[1]:.6f} p25={qs[2]:.6f} "
        f"p50={qs[3]:.6f} p75={qs[4]:.6f} p90={qs[5]:.6f} p95={qs[6]:.6f} "
        f"max={np.max(x):.6f} iqr={(qs[4]-qs[2]):.6f} skew={_skew(x):.6f}"
    )


def _hist(name: str, x: np.ndarray, bins: int = 10) -> None:
    counts, edges = np.histogram(np.asarray(x, dtype=float), bins=bins)
    total = int(np.sum(counts))
    for i, count in enumerate(counts):
        rate = count / total if total else 0.0
        print(
            f"S1 CQ HIST {name} bin={i+1:02d} lo={edges[i]:.6f} hi={edges[i+1]:.6f} "
            f"n={int(count)} rate={rate:.6f}"
        )


def run_symbol(ticker: str) -> None:
    df = download_ticker_daily(ticker, period=PERIOD)
    audit = validate_daily_ohlcv(df, minimum_rows=1000)
    events = _events(df)
    outcomes = _entry_outcomes(events)
    windows = _window_cq(events, outcomes)
    if outcomes.empty:
        raise RuntimeError(f"{ticker}: no complete Entry/Exit outcomes")
    if windows.empty:
        raise RuntimeError(f"{ticker}: no C/Q windows survived")

    ret = outcomes["return"].to_numpy(dtype=float)
    c = windows["C"].to_numpy(dtype=float)
    q = windows["Q"].to_numpy(dtype=float)
    corr = float(np.corrcoef(c, q)[0, 1]) if len(c) > 1 else float("nan")
    print(
        "S1 CQ DATA "
        f"ticker={ticker} period={PERIOD} rows={audit.rows} start={audit.start} end={audit.end} "
        f"entry_definition=every_close_with_MA5_gt_MA10_gt_MA20_and_close_above_all "
        f"exit_definition=first_close_below_MA5_sell40_then_first_close_below_MA10_sell60 "
        f"complete_entries={len(outcomes)} rolling_window={WINDOW} min_outcomes={MIN_OUTCOMES} "
        f"cq_windows={len(windows)} model=false ae=false addons=false volume=false"
    )
    _describe(f"{ticker}_ENTRY_RETURN", ret)
    _describe(f"{ticker}_C", c)
    _describe(f"{ticker}_Q", q)
    _hist(f"{ticker}_C", c)
    _hist(f"{ticker}_Q", q)
    print(
        f"S1 CQ JOINT ticker={ticker} corr_C_Q={corr:.6f} "
        f"Q_lt_025={np.mean(q < 0.25):.6f} Q_025_075={np.mean((q >= 0.25) & (q <= 0.75)):.6f} "
        f"Q_gt_075={np.mean(q > 0.75):.6f}"
    )
    print(f"S1 CQ PASS ticker={ticker}")


def main() -> None:
    symbols = os.environ.get("FUTUREVIEW_TICKERS", "SPY,QQQ")
    tickers = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not tickers:
        raise ValueError("FUTUREVIEW_TICKERS must contain at least one ticker")
    for ticker in tickers:
        run_symbol(ticker)


if __name__ == "__main__":
    main()

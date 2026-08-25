from __future__ import annotations

import numpy as np
import pandas as pd

from .alpaca_data import aggregate_rth_two_bars


def main() -> None:
    rows: list[dict[str, object]] = []
    session = pd.Timestamp("2026-08-20")
    times = pd.date_range(
        "2026-08-20 09:30",
        "2026-08-20 15:30",
        freq="30min",
        tz="America/New_York",
    )
    if len(times) != 13:
        raise RuntimeError("unexpected synthetic regular-session bar count")
    for i, ts in enumerate(times):
        base = 100.0 + i
        rows.append(
            {
                "timestamp": ts,
                "date": session,
                "open": base,
                "high": base + 1.0,
                "low": base - 1.0,
                "close": base + 0.5,
                "volume": 1000.0 + i,
            }
        )
    raw = pd.DataFrame(rows)
    out = aggregate_rth_two_bars(raw)
    if len(out) != 2:
        raise RuntimeError(f"expected 2 session bars, got {len(out)}")
    first = out.iloc[0]
    second = out.iloc[1]
    if int(first["session_bar"]) != 0 or int(second["session_bar"]) != 1:
        raise RuntimeError("unexpected session bar labels")
    if abs(float(first["open"]) - 100.0) > 1e-12:
        raise RuntimeError("first bar open mismatch")
    if abs(float(first["close"]) - 107.5) > 1e-12:
        raise RuntimeError("first bar close mismatch")
    if abs(float(second["open"]) - 108.0) > 1e-12:
        raise RuntimeError("second bar open mismatch")
    if abs(float(second["close"]) - 112.5) > 1e-12:
        raise RuntimeError("second bar close mismatch")
    expected_first_volume = float(np.sum([1000.0 + i for i in range(8)]))
    expected_second_volume = float(np.sum([1000.0 + i for i in range(8, 13)]))
    if abs(float(first["volume"]) - expected_first_volume) > 1e-12:
        raise RuntimeError("first bar volume mismatch")
    if abs(float(second["volume"]) - expected_second_volume) > 1e-12:
        raise RuntimeError("second bar volume mismatch")
    print("ALPACA INTRADAY AGGREGATION SMOKE PASS")


if __name__ == "__main__":
    main()

import pandas as pd

from futureview.market_data.provider import CANONICAL_BAR_COLUMNS
from futureview.market_data.yahoo import _date_chunks, normalize_yfinance_frame


def test_date_chunks_are_contiguous_and_end_exclusive() -> None:
    assert _date_chunks("2026-01-01", "2026-04-01", 30) == [
        ("2026-01-01", "2026-01-31"),
        ("2026-01-31", "2026-03-02"),
        ("2026-03-02", "2026-04-01"),
    ]


def test_normalize_yfinance_single_symbol_frame() -> None:
    index = pd.DatetimeIndex(
        ["2026-09-10 13:30:00+00:00", "2026-09-10 13:35:00+00:00"],
        name="Datetime",
    )
    raw = pd.DataFrame(
        {
            "Open": [6500.0, 6501.0],
            "High": [6502.0, 6503.0],
            "Low": [6499.0, 6500.0],
            "Close": [6501.0, 6502.0],
            "Volume": [100.0, 120.0],
        },
        index=index,
    )

    out = normalize_yfinance_frame(raw, "MES=F")

    assert list(out.columns) == CANONICAL_BAR_COLUMNS
    assert out["symbol"].tolist() == ["MES=F", "MES=F"]
    assert str(out["timestamp"].dt.tz) == "UTC"
    assert out["volume"].tolist() == [100.0, 120.0]


def test_normalize_yfinance_multiindex_frame() -> None:
    index = pd.DatetimeIndex(["2026-09-10 13:30:00+00:00"], name="Datetime")
    columns = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close", "Volume"], ["MES=F"]]
    )
    raw = pd.DataFrame([[6500.0, 6502.0, 6499.0, 6501.0, 100.0]], index=index, columns=columns)

    out = normalize_yfinance_frame(raw, "MES=F")

    assert len(out) == 1
    assert out.loc[0, "close"] == 6501.0
    assert out.loc[0, "volume"] == 100.0

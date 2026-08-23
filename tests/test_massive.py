from datetime import date

from futureview.data.massive import grouped_daily_payload_to_frame


def test_grouped_daily_payload_normalizes_to_canonical_schema() -> None:
    trading_date = date(2026, 8, 21)
    payload = {
        "status": "OK",
        "results": [
            {
                "T": "AAPL",
                "o": 225.0,
                "h": 229.0,
                "l": 224.0,
                "c": 228.5,
                "v": 50_000_000,
                "vw": 227.1,
            }
        ],
    }

    frame = grouped_daily_payload_to_frame(payload, trading_date)

    assert frame.columns == ["symbol", "date", "open", "high", "low", "close", "volume"]
    assert frame.height == 1
    row = frame.row(0, named=True)
    assert row["symbol"] == "AAPL"
    assert row["date"] == trading_date
    assert row["open"] == 225.0
    assert row["high"] == 229.0
    assert row["low"] == 224.0
    assert row["close"] == 228.5
    assert row["volume"] == 50_000_000.0


def test_grouped_daily_payload_handles_empty_session() -> None:
    frame = grouped_daily_payload_to_frame({"status": "OK", "results": []}, date(2026, 8, 22))
    assert frame.is_empty()

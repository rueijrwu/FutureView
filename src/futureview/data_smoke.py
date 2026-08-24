from __future__ import annotations

from pathlib import Path
import tempfile

from .data import download_spy_daily, save_canonical_csv, validate_daily_ohlcv


def main() -> None:
    frame = download_spy_daily(period="3y")
    audit = validate_daily_ohlcv(frame)

    with tempfile.TemporaryDirectory() as tmpdir:
        path = save_canonical_csv(frame, Path(tmpdir) / "spy_daily_3y.csv")
        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError("Canonical CSV was not written correctly")

    print(
        "DATA SMOKE PASS "
        f"rows={audit.rows} start={audit.start} end={audit.end} "
        f"duplicates={audit.duplicate_dates} missing={audit.missing_values}"
    )


if __name__ == "__main__":
    main()

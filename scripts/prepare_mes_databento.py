#!/usr/bin/env python3
"""Prepare Databento MES OHLCV-1m archives for FutureView.

Input
-----
Monthly ``*.ohlcv-1m.dbn.zst`` files downloaded from Databento for the MES
parent product and stored under ``data/databento/mes/raw`` by default.

Output
------
One Parquet file per input month for each resolution:

    data/databento/mes/parquet/1m/<source-stem>.parquet
    data/databento/mes/parquet/5m/<source-stem>.parquet

The raw DBN.zst files remain the immutable source of truth. This script does
not construct a continuous futures series and does not choose a roll rule.
Rows are kept per actual MES outright contract.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import databento as db
import pandas as pd

# CME quarterly MES outright symbols. Examples include MESM9, MESZ24, MESU6.
# Parent-product downloads may also contain calendar spreads; those contain
# separators and therefore do not match this pattern.
MES_OUTRIGHT_RE = re.compile(r"^MES[HMUZ]\d{1,2}$")

CANONICAL_COLUMNS = [
    "timestamp",
    "symbol",
    "instrument_id",
    "open",
    "high",
    "low",
    "close",
    "volume",
]


@dataclass(frozen=True)
class FileSummary:
    source: str
    rows_raw: int
    rows_outright_1m: int
    rows_outright_5m: int
    symbols: list[str]
    first_timestamp: str | None
    last_timestamp: str | None
    output_1m: str
    output_5m: str


def _load_ohlcv(path: Path) -> pd.DataFrame:
    store = db.DBNStore.from_file(path)
    # Current Databento to_df() uses price_type rather than pretty_px.
    # Request float display prices explicitly and preserve UTC timestamps plus
    # mapped raw symbols as part of the canonical FutureView conversion.
    df = store.to_df(price_type="float", pretty_ts=True, map_symbols=True)
    if df.empty:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)

    df = df.reset_index()
    if "ts_event" in df.columns:
        df = df.rename(columns={"ts_event": "timestamp"})
    elif df.columns[0] not in {"timestamp", "symbol"}:
        # Databento normally names the event-time index ts_event. This fallback
        # keeps the failure message useful if a client version differs.
        df = df.rename(columns={df.columns[0]: "timestamp"})

    required = {"timestamp", "symbol", "instrument_id", "open", "high", "low", "close", "volume"}
    missing = sorted(required.difference(df.columns))
    if missing:
        raise ValueError(f"{path}: DBN frame missing required columns: {missing}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="raise")
    return df


def _filter_outrights(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.loc[:, CANONICAL_COLUMNS].copy()

    symbol = df["symbol"].astype(str)
    out = df.loc[symbol.str.fullmatch(MES_OUTRIGHT_RE)].copy()
    if out.empty:
        sample = sorted(symbol.dropna().unique().tolist())[:20]
        raise ValueError(
            "No MES outright contracts found after symbol filtering. "
            f"Sample mapped symbols: {sample}"
        )

    out = out.loc[:, CANONICAL_COLUMNS]
    out = out.sort_values(["symbol", "timestamp"], kind="stable")
    dup = out.duplicated(["symbol", "timestamp"])
    if dup.any():
        raise ValueError(f"duplicate symbol/timestamp rows found: {int(dup.sum())}")
    if out[["open", "high", "low", "close", "volume"]].isna().any().any():
        raise ValueError("OHLCV contains null values")
    if (out["volume"] < 0).any():
        raise ValueError("negative volume found")
    if (out["high"] < out[["open", "close", "low"]].max(axis=1)).any():
        raise ValueError("invalid OHLC high values")
    if (out["low"] > out[["open", "close", "high"]].min(axis=1)).any():
        raise ValueError("invalid OHLC low values")
    return out


def _to_5m(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate independently inside each actual contract.

    Databento OHLCV timestamps are treated as UTC event/bar timestamps. We use
    origin='epoch' so 5-minute buckets have deterministic UTC boundaries and
    never aggregate across symbols.
    """
    if df.empty:
        return df.copy()

    pieces: list[pd.DataFrame] = []
    for symbol, group in df.groupby("symbol", sort=False):
        group = group.sort_values("timestamp").set_index("timestamp")
        agg = group.resample("5min", origin="epoch", label="left", closed="left").agg(
            instrument_id=("instrument_id", "last"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        agg = agg.dropna(subset=["open", "high", "low", "close"])
        agg.insert(0, "symbol", symbol)
        agg = agg.reset_index()
        pieces.append(agg.loc[:, CANONICAL_COLUMNS])

    out = pd.concat(pieces, ignore_index=True)
    return out.sort_values(["symbol", "timestamp"], kind="stable").reset_index(drop=True)


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, engine="pyarrow", compression="zstd")


def process_file(path: Path, output_root: Path) -> FileSummary:
    raw = _load_ohlcv(path)
    one = _filter_outrights(raw)
    five = _to_5m(one)

    stem = path.name
    if stem.endswith(".dbn.zst"):
        stem = stem[: -len(".dbn.zst")]
    out_1m = output_root / "1m" / f"{stem}.parquet"
    out_5m = output_root / "5m" / f"{stem}.parquet"
    _write_parquet(one, out_1m)
    _write_parquet(five, out_5m)

    first = one["timestamp"].min() if not one.empty else None
    last = one["timestamp"].max() if not one.empty else None
    return FileSummary(
        source=str(path),
        rows_raw=int(len(raw)),
        rows_outright_1m=int(len(one)),
        rows_outright_5m=int(len(five)),
        symbols=sorted(one["symbol"].astype(str).unique().tolist()),
        first_timestamp=first.isoformat() if first is not None else None,
        last_timestamp=last.isoformat() if last is not None else None,
        output_1m=str(out_1m),
        output_5m=str(out_5m),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/databento/mes/raw"))
    parser.add_argument("--output", type=Path, default=Path("data/databento/mes/parquet"))
    parser.add_argument("--manifest", type=Path, default=Path("data/databento/mes/processed_manifest.json"))
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N monthly files (smoke testing).")
    args = parser.parse_args()

    files = sorted(args.input.glob("*.dbn.zst"))
    if args.limit is not None:
        files = files[: args.limit]
    if not files:
        raise SystemExit(f"No *.dbn.zst files found under {args.input}")

    summaries: list[FileSummary] = []
    for idx, path in enumerate(files, start=1):
        print(f"MES_DBN_PROCESS file={idx}/{len(files)} path={path}", flush=True)
        summary = process_file(path, args.output)
        summaries.append(summary)
        print(
            "MES_DBN_OK",
            f"source={path.name}",
            f"raw_rows={summary.rows_raw}",
            f"rows_1m={summary.rows_outright_1m}",
            f"rows_5m={summary.rows_outright_5m}",
            f"symbols={','.join(summary.symbols)}",
            f"first={summary.first_timestamp}",
            f"last={summary.last_timestamp}",
            flush=True,
        )

    manifest = {
        "dataset": "GLBX.MDP3",
        "product": "MES",
        "source_schema": "ohlcv-1m",
        "source_format": "dbn.zst",
        "working_format": "parquet-zstd",
        "continuous_series": False,
        "roll_rule": None,
        "files": [asdict(x) for x in summaries],
        "totals": {
            "source_files": len(summaries),
            "rows_1m": sum(x.rows_outright_1m for x in summaries),
            "rows_5m": sum(x.rows_outright_5m for x in summaries),
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(
        "MES_DBN_SUMMARY",
        f"files={manifest['totals']['source_files']}",
        f"rows_1m={manifest['totals']['rows_1m']}",
        f"rows_5m={manifest['totals']['rows_5m']}",
        f"manifest={args.manifest}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

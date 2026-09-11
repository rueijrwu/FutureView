from __future__ import annotations

import json
import re
from pathlib import Path

import databento as db
import pandas as pd

MES_OUTRIGHT = re.compile(r"^MES[HMUZ]\d{1,2}$")
COLUMNS = ["timestamp", "symbol", "instrument_id", "open", "high", "low", "close", "volume"]


def _load(path: Path) -> pd.DataFrame:
    store = db.DBNStore.from_file(path)
    frame = store.to_df(price_type="float", pretty_ts=True, map_symbols=True).reset_index()
    if frame.empty:
        return pd.DataFrame(columns=COLUMNS)
    if "ts_event" in frame.columns:
        frame = frame.rename(columns={"ts_event": "timestamp"})
    elif "timestamp" not in frame.columns:
        frame = frame.rename(columns={frame.columns[0]: "timestamp"})
    missing = sorted(set(COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"{path}: missing DBN columns {missing}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["symbol"] = frame["symbol"].astype(str)
    frame = frame.loc[frame["symbol"].str.fullmatch(MES_OUTRIGHT), COLUMNS].copy()
    if frame.empty:
        raise ValueError(f"{path}: no MES outright futures after filtering")
    frame = frame.drop_duplicates(["symbol", "timestamp"], keep="last")
    frame = frame.sort_values(["symbol", "timestamp"], kind="stable").reset_index(drop=True)
    return frame


def _to_5m(one: pd.DataFrame) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for symbol, group in one.groupby("symbol", sort=False):
        group = group.sort_values("timestamp").set_index("timestamp")
        out = group.resample("5min", origin="epoch", label="left", closed="left").agg(
            instrument_id=("instrument_id", "last"),
            open=("open", "first"), high=("high", "max"), low=("low", "min"),
            close=("close", "last"), volume=("volume", "sum"),
        )
        out = out.dropna(subset=["open", "high", "low", "close"])
        out.insert(0, "symbol", symbol)
        pieces.append(out.reset_index()[COLUMNS])
    result = pd.concat(pieces, ignore_index=True)
    return result.sort_values(["symbol", "timestamp"], kind="stable").reset_index(drop=True)


def prepare(raw_dir: Path, runtime_dir: Path, *, limit: int | None = None, force: bool = False) -> Path:
    files = sorted(raw_dir.glob("*.dbn.zst"))
    if limit is not None:
        files = files[:limit]
    if not files:
        raise FileNotFoundError(f"No .dbn.zst files under {raw_dir}")

    one_dir = runtime_dir / "parquet" / "1m"
    five_dir = runtime_dir / "parquet" / "5m"
    one_dir.mkdir(parents=True, exist_ok=True)
    five_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []

    for index, raw_path in enumerate(files, start=1):
        stem = raw_path.name.removesuffix(".dbn.zst")
        one_path = one_dir / f"{stem}.parquet"
        five_path = five_dir / f"{stem}.parquet"
        print(f"PREPARE {index}/{len(files)} {raw_path.name}", flush=True)
        if force or not one_path.exists() or not five_path.exists():
            one = _load(raw_path)
            five = _to_5m(one)
            one.to_parquet(one_path, index=False, compression="zstd")
            five.to_parquet(five_path, index=False, compression="zstd")
        else:
            one = pd.read_parquet(one_path, columns=["timestamp", "symbol"])
            five = pd.read_parquet(five_path, columns=["timestamp", "symbol"])
        symbols = sorted(one["symbol"].astype(str).unique().tolist())
        entries.append({
            "source": raw_path.name,
            "one_minute": str(one_path.relative_to(runtime_dir)),
            "five_minute": str(five_path.relative_to(runtime_dir)),
            "symbols": symbols,
            "rows_1m": int(len(one)),
            "rows_5m": int(len(five)),
            "first": pd.to_datetime(one["timestamp"], utc=True).min().isoformat(),
            "last": pd.to_datetime(one["timestamp"], utc=True).max().isoformat(),
        })
        print(f"PREPARE_OK symbols={','.join(symbols)} rows_1m={len(one)} rows_5m={len(five)}", flush=True)

    manifest = {
        "version": 1,
        "dataset": "GLBX.MDP3",
        "product": "MES",
        "source_schema": "ohlcv-1m",
        "continuous_series": False,
        "roll_rule": None,
        "files": entries,
    }
    manifest_path = runtime_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"PREPARE_SUMMARY files={len(entries)} manifest={manifest_path}", flush=True)
    return manifest_path

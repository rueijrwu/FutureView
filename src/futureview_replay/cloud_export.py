from __future__ import annotations

import gzip
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from futureview_replay.resolver import DISPLAY_TIME_ZONE, SESSION_ROLL_HOUR_ET, session_date


INTRADAY_DISPLAY_RESOLUTIONS: dict[str, int] = {"5": 5, "30": 30, "240": 240}
DISPLAY_WINDOW_BARS = 512


def _session_start_epoch(value: pd.Timestamp) -> int:
    value = pd.Timestamp(value)
    local = value.tz_convert(DISPLAY_TIME_ZONE)
    day = local.date()
    if local.hour < SESSION_ROLL_HOUR_ET:
        day = (local - pd.Timedelta(days=1)).date()
    start = pd.Timestamp(
        year=day.year,
        month=day.month,
        day=day.day,
        hour=SESSION_ROLL_HOUR_ET,
        tz=DISPLAY_TIME_ZONE,
    )
    return int(start.tz_convert("UTC").timestamp())


def _prepare_display_frame(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Normalize/sort a contract once, then reuse it for every display resolution."""
    frame = pd.concat(frames, ignore_index=True)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp", kind="stable").reset_index(drop=True)
    frame["session_start"] = frame["timestamp"].map(_session_start_epoch)
    # Do not depend on pandas' internal datetime unit (ns/us/ms). Explicit timestamp()
    # remains correct across pandas versions and is paid only once per contract.
    frame["epoch_seconds"] = frame["timestamp"].map(lambda value: int(pd.Timestamp(value).timestamp()))
    frame["trading_day"] = frame["timestamp"].map(
        lambda value: session_date(pd.Timestamp(value).to_pydatetime()).isoformat()
    )
    return frame


def _aggregate_ohlcv(group: pd.DataFrame, stamp: int) -> dict[str, float | int]:
    # `group` comes from an already timestamp-sorted prepared frame, so sorting again
    # for every output candle is unnecessary.
    return {
        "t": int(stamp),
        "o": float(group.iloc[0]["open"]),
        "h": float(group["high"].max()),
        "l": float(group["low"].min()),
        "c": float(group.iloc[-1]["close"]),
        "v": float(group["volume"].sum()),
    }


def _intraday_bars(frame: pd.DataFrame, minutes: int) -> list[dict[str, float | int]]:
    buckets = frame["session_start"] + (
        (frame["epoch_seconds"] - frame["session_start"]) // (minutes * 60)
    ) * (minutes * 60)
    return [_aggregate_ohlcv(group, int(bucket)) for bucket, group in frame.groupby(buckets, sort=True)]


def _daily_bars(frame: pd.DataFrame) -> list[dict[str, float | int]]:
    out: list[dict[str, float | int]] = []
    for trading_day, group in frame.groupby("trading_day", sort=True):
        day = date.fromisoformat(str(trading_day))
        stamp = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
        out.append(_aggregate_ohlcv(group, stamp))
    return out


def _write_display_windows(
    output_dir: Path,
    contract: str,
    resolution_dir: str,
    bars: list[dict[str, float | int]],
) -> list[dict[str, object]]:
    if not bars:
        return []
    windows: list[dict[str, object]] = []
    for offset in range(0, len(bars), DISPLAY_WINDOW_BARS):
        chunk = bars[offset : offset + DISPLAY_WINDOW_BARS]
        window_index = offset // DISPLAY_WINDOW_BARS
        relative = Path("contracts") / contract / resolution_dir / f"window-{window_index:06d}.json.gz"
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(target, "wt", encoding="utf-8", compresslevel=6) as f:
            json.dump(chunk, f, separators=(",", ":"))
        windows.append({
            "key": relative.as_posix(),
            "window": window_index,
            "offset": offset,
            "count": len(chunk),
            "first_time": chunk[0]["t"],
            "last_time": chunk[-1]["t"],
        })
    return windows


def export_cloud(runtime_dir: Path, output_dir: Path) -> Path:
    manifest_path = runtime_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    contracts: dict[str, dict[str, object]] = {}
    session_volumes: dict[date, dict[str, float]] = {}
    display_source: dict[str, list[pd.DataFrame]] = {}

    for entry in manifest["files"]:
        path = runtime_dir / str(entry["one_minute"])
        frame = pd.read_parquet(path)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        month = frame["timestamp"].min().strftime("%Y-%m")
        for contract, group in frame.groupby(frame["symbol"].astype(str), sort=False):
            group = group.sort_values("timestamp")
            if group.empty:
                continue
            display_source.setdefault(contract, []).append(
                group[["timestamp", "open", "high", "low", "close", "volume"]].copy()
            )
            for row in group.itertuples(index=False):
                volumes = session_volumes.setdefault(session_date(pd.Timestamp(row.timestamp).to_pydatetime()), {})
                volumes[contract] = volumes.get(contract, 0.0) + float(row.volume)
            bars = [
                {
                    "t": int(row.timestamp.timestamp()),
                    "o": float(row.open),
                    "h": float(row.high),
                    "l": float(row.low),
                    "c": float(row.close),
                    "v": float(row.volume),
                }
                for row in group.itertuples(index=False)
            ]
            relative = Path("contracts") / contract / "1m" / f"{month}.json.gz"
            target = output_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(target, "wt", encoding="utf-8", compresslevel=6) as f:
                json.dump(bars, f, separators=(",", ":"))

            info = contracts.setdefault(
                contract,
                {
                    "contract": contract,
                    "bars": 0,
                    "first_time": bars[0]["t"],
                    "last_time": bars[-1]["t"],
                    "shards": [],
                    "display_shards": {"1": [], "5": [], "30": [], "240": [], "1D": []},
                },
            )
            info["bars"] = int(info["bars"]) + len(bars)
            info["first_time"] = min(int(info["first_time"]), bars[0]["t"])
            info["last_time"] = max(int(info["last_time"]), bars[-1]["t"])
            shard = {
                "key": relative.as_posix(),
                "count": len(bars),
                "first_time": bars[0]["t"],
                "last_time": bars[-1]["t"],
            }
            info["shards"].append(shard)
            info["display_shards"]["1"].append(dict(shard))

    for contract, frames in display_source.items():
        info = contracts[contract]
        prepared = _prepare_display_frame(frames)
        for resolution, minutes in INTRADAY_DISPLAY_RESOLUTIONS.items():
            info["display_shards"][resolution] = _write_display_windows(
                output_dir, contract, f"{minutes}m", _intraday_bars(prepared, minutes)
            )
        info["display_shards"]["1D"] = _write_display_windows(
            output_dir, contract, "1D", _daily_bars(prepared)
        )

    ordered: dict[str, dict[str, object]] = {}
    for contract, info in contracts.items():
        info["shards"] = sorted(info["shards"], key=lambda x: (x["first_time"], x["key"]))
        for resolution in info["display_shards"]:
            info["display_shards"][resolution] = sorted(
                info["display_shards"][resolution], key=lambda x: (x["first_time"], x["key"])
            )
        ordered[contract] = info

    sessions = sorted(session_volumes)
    cloud_manifest = {
        "version": 7,
        "dataset": manifest.get("dataset"),
        "product": manifest.get("product"),
        "resolution": "1m",
        "supported_display_resolutions": ["1", "5", "30", "240", "1D"],
        "native_display_resolutions": ["1", "5", "30", "240", "1D"],
        "intraday_multipliers": ["1", "5", "30", "240"],
        "daily_multipliers": ["1"],
        "display_cache": {
            "strategy": "rolling_precomputed_windows",
            "window_bars": DISPLAY_WINDOW_BARS,
            "prefetch_threshold": 0.75,
            "partial_bar_source": "released_1m_only",
        },
        "continuous_series": False,
        "roll_rule": "runtime_prior_session_max_volume",
        "contract_selection": {
            "rule": "runtime_prior_session_max_volume",
            "time_zone": str(DISPLAY_TIME_ZONE),
            "session_roll_hour_et": SESSION_ROLL_HOUR_ET,
            "expiry_cutoff_et": "09:30",
            "sessions": [current.isoformat() for current in sessions],
            "session_volumes": {
                current.isoformat(): {contract: float(volume) for contract, volume in volumes.items()}
                for current, volumes in sorted(session_volumes.items())
            },
        },
        "contracts": ordered,
    }
    out = output_dir / "manifest.json"
    out.write_text(json.dumps(cloud_manifest, indent=2), encoding="utf-8")
    print(
        f"CLOUD_EXPORT_OK product={cloud_manifest['product']} native=1m,5m,30m,4h,1D "
        f"window={DISPLAY_WINDOW_BARS} contracts={len(ordered)} manifest={out}",
        flush=True,
    )
    return out

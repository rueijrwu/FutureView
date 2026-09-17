from __future__ import annotations

import gzip
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from futureview_replay.resolver import DISPLAY_TIME_ZONE, SESSION_ROLL_HOUR_ET, session_date


def _daily_bars(frames: list[pd.DataFrame]) -> list[dict[str, float | int]]:
    frame = pd.concat(frames, ignore_index=True)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp", kind="stable")
    frame["trading_day"] = frame["timestamp"].map(
        lambda value: session_date(pd.Timestamp(value).to_pydatetime()).isoformat()
    )
    out: list[dict[str, float | int]] = []
    for trading_day, group in frame.groupby("trading_day", sort=True):
        group = group.sort_values("timestamp", kind="stable")
        day = date.fromisoformat(str(trading_day))
        # TradingView requires D/W/M bars to be stamped at 00:00 UTC for the
        # trading day, not at the futures session open.
        stamp = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
        out.append(
            {
                "t": stamp,
                "o": float(group.iloc[0]["open"]),
                "h": float(group["high"].max()),
                "l": float(group["low"].min()),
                "c": float(group.iloc[-1]["close"]),
                "v": float(group["volume"].sum()),
            }
        )
    return out


def export_cloud(runtime_dir: Path, output_dir: Path) -> Path:
    manifest_path = runtime_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    contracts: dict[str, dict[str, object]] = {}
    session_volumes: dict[date, dict[str, float]] = {}
    daily_source: dict[str, list[pd.DataFrame]] = {}

    for entry in manifest["files"]:
        path = runtime_dir / str(entry["one_minute"])
        frame = pd.read_parquet(path)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        month = frame["timestamp"].min().strftime("%Y-%m")
        for contract, group in frame.groupby(frame["symbol"].astype(str), sort=False):
            group = group.sort_values("timestamp")
            if group.empty:
                continue
            daily_source.setdefault(contract, []).append(
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
                    "display_shards": {"1m": [], "1D": []},
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
            # `shards` stays the authoritative replay path consumed by the Durable
            # Object; display_shards makes the native datafeed resolutions explicit.
            info["shards"].append(shard)
            info["display_shards"]["1m"].append(dict(shard))

    for contract, frames in daily_source.items():
        bars = _daily_bars(frames)
        if not bars:
            continue
        relative = Path("contracts") / contract / "1D" / "all.json.gz"
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(target, "wt", encoding="utf-8", compresslevel=6) as f:
            json.dump(bars, f, separators=(",", ":"))
        contracts[contract]["display_shards"]["1D"] = [
            {
                "key": relative.as_posix(),
                "count": len(bars),
                "first_time": bars[0]["t"],
                "last_time": bars[-1]["t"],
            }
        ]

    ordered: dict[str, dict[str, object]] = {}
    for contract, info in contracts.items():
        info["shards"] = sorted(info["shards"], key=lambda x: (x["first_time"], x["key"]))
        info["display_shards"]["1m"] = sorted(
            info["display_shards"]["1m"], key=lambda x: (x["first_time"], x["key"])
        )
        ordered[contract] = info

    sessions = sorted(session_volumes)
    cloud_manifest = {
        "version": 6,
        "dataset": manifest.get("dataset"),
        "product": manifest.get("product"),
        "resolution": "1m",
        "supported_display_resolutions": ["1", "5", "30", "240", "1D"],
        "native_display_resolutions": ["1", "1D"],
        "intraday_multipliers": ["1"],
        "daily_multipliers": ["1"],
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
        f"CLOUD_EXPORT_OK product={cloud_manifest['product']} native=1m,1D "
        f"contracts={len(ordered)} manifest={out}",
        flush=True,
    )
    return out

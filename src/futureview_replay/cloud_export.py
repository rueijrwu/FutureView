from __future__ import annotations

import gzip
import json
from pathlib import Path

import pandas as pd


def export_cloud(runtime_dir: Path, output_dir: Path) -> Path:
    manifest_path = runtime_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    contracts: dict[str, dict[str, object]] = {}

    for entry in manifest["files"]:
        path = runtime_dir / str(entry["five_minute"])
        frame = pd.read_parquet(path)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        month = frame["timestamp"].min().strftime("%Y-%m")
        for contract, group in frame.groupby(frame["symbol"].astype(str), sort=False):
            group = group.sort_values("timestamp")
            if group.empty:
                continue
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
            relative = Path("contracts") / contract / f"{month}.json.gz"
            target = output_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(target, "wt", encoding="utf-8", compresslevel=6) as f:
                json.dump(bars, f, separators=(",", ":"))

            info = contracts.setdefault(
                contract,
                {"contract": contract, "bars": 0, "first_time": bars[0]["t"], "last_time": bars[-1]["t"], "shards": []},
            )
            info["bars"] = int(info["bars"]) + len(bars)
            info["first_time"] = min(int(info["first_time"]), bars[0]["t"])
            info["last_time"] = max(int(info["last_time"]), bars[-1]["t"])
            info["shards"].append(
                {
                    "key": relative.as_posix(),
                    "count": len(bars),
                    "first_time": bars[0]["t"],
                    "last_time": bars[-1]["t"],
                }
            )

    ordered: dict[str, dict[str, object]] = {}
    for contract, info in contracts.items():
        info["shards"] = sorted(info["shards"], key=lambda x: (x["first_time"], x["key"]))
        ordered[contract] = info

    cloud_manifest = {
        "version": 2,
        "dataset": manifest.get("dataset"),
        "product": manifest.get("product"),
        "resolution": "5m",
        "continuous_series": False,
        "roll_rule": None,
        "contracts": ordered,
    }
    out = output_dir / "manifest.json"
    out.write_text(json.dumps(cloud_manifest, indent=2), encoding="utf-8")
    print(f"CLOUD_EXPORT_OK product={cloud_manifest['product']} contracts={len(ordered)} manifest={out}", flush=True)
    return out

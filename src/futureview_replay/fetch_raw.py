from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


DEFAULT_BUCKET = "futureview-data"
DEFAULT_DATASET = "GLBX.MDP3"
DEFAULT_SCHEMA = "ohlcv-1m"


def _month_from_filename(name: str) -> str | None:
    match = re.search(r"-(\d{6})\d{2}-", name)
    return match.group(1) if match else None


def _get(bucket: str, key: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "npx", "--yes", "wrangler@4.125.0", "r2", "object", "get",
            f"{bucket}/{key}", "--file", str(target), "--remote",
        ],
        check=True,
    )


def fetch_raw(
    output_dir: Path,
    *,
    product: str,
    dataset: str = DEFAULT_DATASET,
    schema: str = DEFAULT_SCHEMA,
    bucket: str = DEFAULT_BUCKET,
    start_month: str | None = None,
    end_month: str | None = None,
    limit: int | None = None,
) -> Path:
    product = product.upper()
    prefix = f"raw/databento/{dataset}/{product}/{schema}"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "raw-manifest.json"
    _get(bucket, f"{prefix}/manifest.json", manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = list(manifest.get("files", []))
    selected = []
    for item in files:
        month = _month_from_filename(str(item["filename"]))
        if start_month and month and month < start_month.replace("-", ""):
            continue
        if end_month and month and month > end_month.replace("-", ""):
            continue
        selected.append(item)
    if limit is not None:
        selected = selected[:limit]
    if not selected:
        raise ValueError("No raw files matched the requested range")

    for index, item in enumerate(selected, start=1):
        target = output_dir / str(item["filename"])
        print(f"FETCH_RAW {index}/{len(selected)} {target.name}", flush=True)
        if not target.exists() or target.stat().st_size != int(item["bytes"]):
            _get(bucket, str(item["r2_key"]), target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise ValueError(f"SHA256 mismatch for {target.name}")
    print(f"FETCH_RAW_OK product={product} files={len(selected)} output={output_dir}", flush=True)
    return manifest_path

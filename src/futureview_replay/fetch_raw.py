from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_BUCKET = "futureview-data"
DEFAULT_DATASET = "GLBX.MDP3"
DEFAULT_SCHEMA = "ohlcv-1m"
CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"


def _month_from_filename(name: str) -> str | None:
    match = re.search(r"-(\d{6})\d{2}-", name)
    return match.group(1) if match else None


def _cloudflare_credentials() -> tuple[str, str]:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID") or os.environ.get("R2_ACCOUNT_ID")
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
    missing = []
    if not account_id:
        missing.append("CLOUDFLARE_ACCOUNT_ID (or R2_ACCOUNT_ID)")
    if not api_token:
        missing.append("CLOUDFLARE_API_TOKEN")
    if missing:
        raise RuntimeError(
            "Direct R2 fetch requires Cloudflare credentials in the environment: "
            + ", ".join(missing)
        )
    return account_id, api_token


def _object_url(account_id: str, bucket: str, key: str) -> str:
    bucket_path = urllib.parse.quote(bucket, safe="")
    # Cloudflare requires slash characters inside an R2 object key to remain literal.
    key_path = urllib.parse.quote(key, safe="/")
    return f"{CLOUDFLARE_API_BASE}/accounts/{account_id}/r2/buckets/{bucket_path}/objects/{key_path}"


def _get(bucket: str, key: str, target: Path) -> None:
    account_id, api_token = _cloudflare_credentials()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.part")
    request = urllib.request.Request(
        _object_url(account_id, bucket, key),
        headers={"Authorization": f"Bearer {api_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        temporary.replace(target)
    except urllib.error.HTTPError as exc:
        temporary.unlink(missing_ok=True)
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Cloudflare R2 GET failed for {bucket}/{key}: HTTP {exc.code} {detail}"
        ) from exc
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


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

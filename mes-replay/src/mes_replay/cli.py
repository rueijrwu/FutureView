from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from mes_replay.app import create_app
from mes_replay.cloud_export import export_cloud
from mes_replay.prepare import prepare


def main() -> None:
    parser = argparse.ArgumentParser(prog="mes-replay")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prepare", help="Convert raw Databento DBN to replay Parquet")
    p.add_argument("--raw", type=Path, default=Path("/data/raw"))
    p.add_argument("--runtime", type=Path, default=Path("/data/runtime"))
    p.add_argument("--limit", type=int)
    p.add_argument("--force", action="store_true")

    e = sub.add_parser("cloud-export", help="Export compact 5m R2 replay shards")
    e.add_argument("--runtime", type=Path, default=Path("/data/runtime"))
    e.add_argument("--output", type=Path, default=Path("/data/runtime/cloud-export"))

    s = sub.add_parser("serve", help="Run the local browser replay server")
    s.add_argument("--manifest", type=Path, default=Path("/data/runtime/manifest.json"))
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)

    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.raw, args.runtime, limit=args.limit, force=args.force)
        return
    if args.command == "cloud-export":
        export_cloud(args.runtime, args.output)
        return
    uvicorn.run(create_app(args.manifest), host=args.host, port=args.port, log_level="info")

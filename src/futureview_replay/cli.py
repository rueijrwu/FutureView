from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from futureview_replay.app import create_app
from futureview_replay.cloud_export import export_cloud
from futureview_replay.fetch_raw import fetch_raw
from futureview_replay.prepare import prepare


def main() -> None:
    parser = argparse.ArgumentParser(prog="futureview-replay")
    sub = parser.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch-raw", help="Download raw Databento history from R2 for local development")
    f.add_argument("--product", default="MES")
    f.add_argument("--dataset", default="GLBX.MDP3")
    f.add_argument("--schema", default="ohlcv-1m")
    f.add_argument("--bucket", default="futureview-data")
    f.add_argument("--output", type=Path)
    f.add_argument("--from", dest="start_month")
    f.add_argument("--to", dest="end_month")
    f.add_argument("--limit", type=int)

    p = sub.add_parser("prepare", help="Convert raw Databento DBN to replay Parquet")
    p.add_argument("--product", default="MES")
    p.add_argument("--dataset", default="GLBX.MDP3")
    p.add_argument("--schema", default="ohlcv-1m")
    p.add_argument("--symbol-regex")
    p.add_argument("--raw", type=Path)
    p.add_argument("--runtime", type=Path)
    p.add_argument("--limit", type=int)
    p.add_argument("--force", action="store_true")

    e = sub.add_parser("cloud-export", help="Export compact 5m R2 replay shards")
    e.add_argument("--runtime", type=Path, default=Path("runtime"))
    e.add_argument("--output", type=Path, default=Path("runtime/cloud-export"))

    s = sub.add_parser("serve", help="Run the local browser replay server")
    s.add_argument("--manifest", type=Path, default=Path("runtime/manifest.json"))
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)

    args = parser.parse_args()
    if args.command == "fetch-raw":
        output = args.output or Path(".local-data/raw") / args.product.upper()
        fetch_raw(
            output,
            product=args.product,
            dataset=args.dataset,
            schema=args.schema,
            bucket=args.bucket,
            start_month=args.start_month,
            end_month=args.end_month,
            limit=args.limit,
        )
        return
    if args.command == "prepare":
        raw = args.raw or Path(".local-data/raw") / args.product.upper()
        runtime = args.runtime or Path("runtime") / args.product.upper()
        prepare(
            raw,
            runtime,
            product=args.product,
            dataset=args.dataset,
            source_schema=args.schema,
            symbol_regex=args.symbol_regex,
            limit=args.limit,
            force=args.force,
        )
        return
    if args.command == "cloud-export":
        export_cloud(args.runtime, args.output)
        return
    uvicorn.run(create_app(args.manifest), host=args.host, port=args.port, log_level="info")

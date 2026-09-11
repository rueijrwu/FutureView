from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from futureview.market_data.yahoo import YahooMarketDataProvider


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download canonical OHLCV bars for FutureView research."
    )
    parser.add_argument("--provider", choices=("yahoo",), default="yahoo")
    parser.add_argument("--symbol", default="MES=F")
    parser.add_argument("--interval", default="5m")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=date.today() + timedelta(days=1),
        help="exclusive end date; defaults to tomorrow so today's completed bars are included",
    )
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    provider = YahooMarketDataProvider(
        cache_dir=args.cache_dir,
        use_cache=not args.no_cache,
    )
    frame = provider.fetch_bars(
        args.symbol,
        args.start,
        args.end,
        interval=args.interval,
    )

    output = args.output
    if output is None:
        safe_symbol = args.symbol.replace("=", "_").replace("/", "_")
        output = Path("data") / f"{safe_symbol}_{args.interval}_{args.start}_{args.end}.csv.gz"
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, compression="gzip" if output.suffix == ".gz" else None)

    print(
        f"stored symbol={args.symbol} interval={args.interval} rows={len(frame)} "
        f"first={frame['timestamp'].iloc[0]} last={frame['timestamp'].iloc[-1]} output={output}"
    )


if __name__ == "__main__":
    main()

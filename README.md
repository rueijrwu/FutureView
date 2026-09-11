# FutureView Replay

Historical market replay and backtest platform. The replay engine is symbol/product agnostic; MES is the first configured futures product.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
```

## Local data

Raw archives live in Cloudflare R2, not source control. Download only what you need:

```bash
futureview-replay fetch-raw --product MES --from 2019-05 --to 2019-06
```

This writes to `.local-data/raw/MES/` by default and verifies each file against the R2 raw manifest SHA-256.

Prepare replay data:

```bash
futureview-replay prepare --product MES
```

Run locally:

```bash
futureview-replay serve --manifest runtime/MES/manifest.json
```

Open `http://127.0.0.1:8787`.

## Architecture

```text
R2 raw Databento archive
  -> local/CI fetch subset
  -> canonical actual-contract 1m Parquet
  -> actual-contract 5m Parquet
  -> replay shards
  -> local FastAPI or Cloudflare Worker/Durable Object
```

User-facing times are America/New_York (ET). Stored/protocol timestamps are UTC. The browser must never receive bars beyond the replay cursor.

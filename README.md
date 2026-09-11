# FutureView Replay

Historical market replay and backtest platform. The engine is product/symbol agnostic; MES is the first configured futures product.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
```

## Fetch local data

Raw Databento archives live in Cloudflare R2, not Git. Download only what you need:

```bash
futureview-replay fetch-raw --product MES --from 2019-05 --to 2019-06
```

Default local cache:

```text
.local-data/raw/MES/
```

Each downloaded file is checked against the R2 raw manifest SHA-256.

Prepare replay data:

```bash
futureview-replay prepare --product MES
```

Run locally:

```bash
futureview-replay serve --manifest runtime/MES/manifest.json
```

Open `http://127.0.0.1:8787`.

## Data architecture

```text
R2 raw archive
  -> selected local/CI cache
  -> actual-contract 1m Parquet
  -> actual-contract 5m Parquet
  -> replay shards
  -> local FastAPI or Cloudflare Worker/Durable Object
```

Raw source catalog is recorded in `data/raw_sources.json`.

User-facing times are America/New_York (ET). Stored/protocol timestamps are UTC. The browser must never receive bars beyond the replay cursor.

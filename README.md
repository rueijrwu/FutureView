# FutureView Replay

Historical market replay and backtest platform. The engine is product/symbol agnostic; MES is the first configured futures product. A replay is started with a product and ET timestamp; the backend causally resolves the actual contract instead of asking the user to choose a contract code.

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

## Contract selection

The resolver groups bars by CME equity-index trading session (18:00 ET boundary). The first available session uses the nearest listed quarterly expiry. Every later session uses only the preceding completed session's volume and may either retain the current contract or roll once to the next quarterly contract. It never rolls backward, skips a listed contract, or uses same-session future volume.

The selected contract and selection reason are returned in `contract_selection` when a replay starts. Contract endpoints remain available for diagnostics, but contract selection is not part of the normal UI or start request.

## Chart tools

The Lightweight Charts UI includes SMA 20, SMA 50, CME-session VWAP, magnet crosshair, horizontal price lines with undo/clear, zoom, fit/latest navigation, linear/log price scale, and an OHLCV crosshair legend. Indicators are computed only from warmup and bars already released by the replay backend; chart tools never request or expose future bars.

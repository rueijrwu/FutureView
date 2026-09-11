# FutureView

FutureView is a browser-based historical MES replay and backtest platform.

## Current scope

- Instrument: CME Micro E-mini S&P 500 futures (MES)
- Historical source: Databento GLBX.MDP3 OHLCV-1m
- Replay clock: 5-minute bars
- Browser controls: Next, Play, Pause, Restart, 1x–100x and Max
- User-facing timezone: America/New_York (ET)
- Internal/storage timestamps: UTC
- Cloud runtime: Cloudflare Worker + Durable Object + R2 + D1

The browser never receives bars beyond the replay cursor.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
```

Prepare historical data:

```bash
mes-replay prepare \
  --raw data/databento/mes/raw \
  --runtime runtime
```

Run the local replay app:

```bash
mes-replay serve \
  --manifest runtime/manifest.json \
  --host 127.0.0.1 \
  --port 8787
```

Open `http://127.0.0.1:8787`.

## Repository layout

```text
src/mes_replay/       Python replay/data package
tests/                Python tests
data/databento/       Databento source archive via Git LFS
cloudflare/           Worker, Durable Object, browser UI, D1 migrations
.github/workflows/    Python CI, Cloudflare check, production deploy
HANDOFF.md            current design/status handoff
```

There is no Docker requirement.

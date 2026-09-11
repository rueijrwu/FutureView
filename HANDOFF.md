# FutureView — MES Replay Handoff

Last updated: 2026-09-11
Primary branch: `master`

## Objective

Build a trustworthy browser-based historical MES replay/backtest platform. The replay engine is the foundation for later manual trading and automated strategy backtests.

## Locked scope

```text
Instrument: MES
Primary replay resolution: 5-minute
Raw source: Databento GLBX.MDP3 OHLCV-1m
Inputs: price + volume
Display timezone: America/New_York (ET)
Storage/protocol timestamps: UTC
```

Do not assume RTH-only, long-only, VWAP/opening-range rules, a fixed holding horizon, or a model architecture.

## Repository layout

The project is now root-level. There is no `mes-replay/` wrapper directory.

```text
src/mes_replay/       replay/data package
tests/                unit/API tests
data/databento/mes/   raw Databento archive via Git LFS
cloudflare/           production browser/Worker runtime
.github/workflows/    only active replay workflows
```

Legacy Strategy1, TSLA, Yahoo/Massive research code and workflows have been removed from the active master tree.

## Data

Source of truth:

```text
data/databento/mes/raw/*.ohlcv-1m.dbn.zst
```

Coverage is approximately 2019-05-06 through 2026-09-10.

Pipeline:

```text
Databento DBN.zst
-> actual-contract 1m Parquet
-> actual-contract 5m Parquet
-> replay manifest
-> gzip JSON cloud shards
-> R2 futureview-data/mes-replay/v1/
```

Never aggregate across contracts. Current replay selects an explicit actual MES contract; automatic rollover is not yet implemented.

## Local use

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
mes-replay prepare --raw data/databento/mes/raw --runtime runtime
mes-replay serve --manifest runtime/manifest.json --host 127.0.0.1 --port 8787
```

Open `http://127.0.0.1:8787`.

## Replay invariants

1. Browser cannot receive future bars.
2. Backend/Durable Object owns the replay cursor.
3. Actual contract identity is preserved.
4. 5m remains the logical replay clock at every playback speed.
5. 100x/Max may batch rendering but may not skip logical bars.
6. User-facing time is ET; backend/R2 remain UTC.
7. Synthetic/back-adjusted prices must never become execution truth.
8. When execution is added, no same-bar lookahead fills.
9. Manual and automated trading must share one execution engine.

Current controls:

```text
Restart / Next / Play / Pause
1x / 5x / 10x / 25x / 50x / 100x / Max
```

## Timezone rule

`datetime-local` values represent ET wall time. Frontend converts ET explicitly to UTC before API submission. Chart axis, contract ranges and status timestamps display ET. Do not regress this by using implicit browser timezone conversion.

Expected example:

```text
Select 2019-05-23 09:00 ET
-> replay/chart cursor displays 2019-05-23 09:00 ET
```

## Cloudflare runtime

```text
cloudflare/public/                  browser UI
cloudflare/worker/main.js           API/router
cloudflare/worker/replay-session.js Durable Object replay state
cloudflare/migrations/              D1 schema
cloudflare/wrangler.jsonc           deployment config
cloudflare/publish-r2.sh            replay shard publisher
```

Runtime roles:

```text
R2             historical replay shards
Durable Object active cursor/playback/WebSocket state
D1             replay session/history persistence
Browser assets candlestick + volume visualization
```

Cloudflare app name is `futureview`.

## CI / deployment

Only these workflows are part of the cleaned project:

```text
.github/workflows/replay-python.yml
.github/workflows/replay-cloudflare-check.yml
.github/workflows/replay-cloudflare-deploy.yml
```

Production deploy flow:

```text
Git LFS raw archive
-> install root Python package
-> prepare 1m/5m
-> cloud-export
-> upload R2
-> resolve/apply D1 migrations
-> deploy FutureView Worker
```

Production target should ultimately be the existing FutureView public origin. Verify the actual `futureview.pages.dev` routing rather than assuming the Worker deployment alone changes Pages routing.

## Not implemented yet

```text
manual Buy/Sell/Flatten
Order/Fill/Position/Account engine
market/limit/stop fills
commission/slippage
1m realistic fill simulation
intrabar ambiguity policy
causal front-contract resolver
rollover execution
saved replay/trade UI
automated Strategy adapter
batch backtest metrics
```

## Recommended next order

```text
1. Verify production URL/API/WebSocket after cleanup deploy.
2. Add Order / Fill / Position / Account primitives.
3. Add manual Market Buy / Sell / Flatten.
4. Add 1m fill model, tick rounding, commission and slippage.
5. Add Limit / Stop and conservative intrabar ambiguity handling.
6. Add causal ContractResolver and real rollover fills.
7. Add session/trade/equity persistence UI.
8. Add automated Strategy adapter using the same execution engine.
```

Do not begin ML/CNN research before replay and execution semantics are trustworthy.

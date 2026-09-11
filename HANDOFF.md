# FutureView — MES Replay Handoff

Last updated: 2026-09-11
Primary branch: `master`
Project status: active MES historical replay / backtest platform

## 0. Read this first

`master` is now the authoritative project line.

The previous FutureView dashboard / TSLA Strategy-1 / Layer1 / Layer2 line is obsolete for current development. Do not restore old architecture, old workflows, old model assumptions, or old dashboard behavior unless explicitly requested.

`intraday-futures-reset` was used to build the new system and was then used to replace `master`. Continue from `master` only.

Current production cutover commit before this handoff:

```text
a18c3d9bd37b1dbe9751334a516f9dcb4f4ebe55
deploy: publish MES replay data and replace FutureView production
```

---

# 1. Product objective

Build a realistic historical MES market replay and backtest platform similar in interaction to TradingView Bar Replay.

Primary user workflow:

```text
choose MES contract + historical start time
-> show only history available up to replay cursor
-> Next / Play / Pause / Restart
-> replay 5-minute bars
-> 1x / 5x / 10x / 25x / 50x / 100x / Max
-> later add manual trading
-> later add realistic execution
-> later add automated strategy interface
```

The first goal is a trustworthy replay/backtest system, not model training.

---

# 2. Locked scope

```text
Instrument: MES
Primary replay resolution: 5-minute
Raw historical source: Databento GLBX.MDP3 OHLCV-1m
Inputs: price + volume
Frontend: browser
Display timezone: America/New_York (ET)
Storage/internal timestamps: UTC
```

Do not assume:

```text
RTH-only
long-only
short-only
VWAP setup
opening range
fixed holding horizon
CNN/model architecture
synthetic continuous execution prices
```

These remain later research/configuration decisions.

---

# 3. Source data

Raw Databento archive is committed through Git LFS:

```text
data/databento/mes/raw/*.ohlcv-1m.dbn.zst
```

Coverage is approximately:

```text
2019-05-06 -> 2026-09-10
```

The archive contains actual MES contracts. Processing filters quarterly outright MES contracts and excludes spreads.

The raw `.dbn.zst` archive is the source of truth.

---

# 4. Standalone Python replay/data package

Primary package:

```text
mes-replay/
```

Important files:

```text
mes-replay/pyproject.toml
mes-replay/src/mes_replay/prepare.py
mes-replay/src/mes_replay/store.py
mes-replay/src/mes_replay/engine.py
mes-replay/src/mes_replay/app.py
mes-replay/src/mes_replay/cloud_export.py
mes-replay/src/mes_replay/cli.py
mes-replay/tests/
```

There is no Docker requirement. Docker support was intentionally removed.

Local setup:

```bash
cd mes-replay
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
```

Prepare data:

```bash
mes-replay prepare \
  --raw ../data/databento/mes/raw \
  --runtime ./runtime
```

Run local replay:

```bash
mes-replay serve \
  --manifest ./runtime/manifest.json \
  --host 127.0.0.1 \
  --port 8787
```

Then open:

```text
http://127.0.0.1:8787
```

---

# 5. Data pipeline

Current pipeline:

```text
Databento DBN.zst
    -> canonical actual-contract 1m Parquet
    -> independently aggregated actual-contract 5m Parquet
    -> replay manifest
    -> compact gzip JSON cloud shards
    -> R2
```

Cloud export command:

```bash
mes-replay cloud-export \
  --runtime ./runtime \
  --output ./runtime/cloud-export
```

Cloud R2 prefix:

```text
futureview-data/mes-replay/v1/
```

Typical layout:

```text
mes-replay/v1/manifest.json
mes-replay/v1/contracts/<CONTRACT>/<SHARD>.json.gz
```

Never aggregate bars across contracts.

---

# 6. Futures contract policy

Current replay MVP uses an explicit actual MES contract.

Example:

```text
MESM24
MESU24
MESZ24
```

There is currently no synthetic continuous execution series and no finalized automatic rollover policy.

This is intentional.

Future implementation should add a causal `ContractResolver`, but execution must always use the actual contract and actual historical price.

If an open position later crosses rollover, model it as two actual fills:

```text
close old contract
open next contract
```

with commissions/slippage applied to both.

---

# 7. Replay semantics

The backend owns the full historical dataset.

The browser must never receive future bars beyond the replay cursor.

Critical invariant:

```text
max(released_bar.timestamp) <= replay_cursor
```

Do not preload a complete historical day/month into browser JavaScript and merely hide future bars.

Replay state:

```text
STOPPED
PLAYING
PAUSED
FINISHED
```

Current controls:

```text
Restart
Next
Play
Pause

1x
5x
10x
25x
50x
100x
Max
```

Current speed semantics:

```text
1x = 1 replay bar/sec
5x = 5 bars/sec
...
100x = 100 bars/sec
Max = as fast as scheduler/runtime permits
```

The 5-minute bar resolution never changes with playback speed.

High-speed playback may batch browser updates, but simulation logic must process bars in order and never skip bars.

---

# 8. Timezone rule

This was a real bug and has been fixed.

All user-facing replay time must use:

```text
America/New_York (ET)
```

That includes:

```text
Start input
contract range
status timestamp
chart x-axis
chart tooltip/time formatter
```

Backend/R2 timestamps remain UTC.

A `datetime-local` value must not be passed through `new Date(raw).toISOString()` using the browser's implicit timezone.

The frontend now explicitly converts ET wall time to UTC before sending it to backend.

Example expected behavior:

```text
Select: 2019-05-23 09:00 ET
Chart cursor: 2019-05-23 09:00 ET
```

Do not regress this.

---

# 9. Cloudflare architecture

Cloud runtime lives under:

```text
mes-replay/cloudflare/
```

Important pieces:

```text
public/                  browser UI
worker/main.js           API/router
worker/replay-session.js Durable Object replay session
migrations/              D1 schema
wrangler.jsonc           Cloudflare configuration
publish-r2.sh            R2 publisher
```

Architecture:

```text
R2
  historical replay shards

Durable Object
  active replay session
  cursor
  play/pause/speed
  WebSocket state

D1
  replay session/history persistence

Cloudflare static assets
  visualization UI

WebSocket
  released bars + state updates
```

The Cloudflare application name has been changed to:

```text
futureview
```

The intent is that the new MES replay becomes FutureView production, not a secondary app.

---

# 10. Current browser UI

Current cloud/local visualization provides:

```text
MES actual contract selector
ET start time
warmup bar count
candlestick chart
volume histogram
Restart
Next
Play
Pause
1x / 5x / 10x / 25x / 50x / 100x / Max
current contract
current cursor
current replay state
```

TradingView Lightweight Charts is currently used only for visualization.

It is not the backtest/replay engine.

Authoritative replay state belongs to backend/Durable Object.

---

# 11. Production deployment

Production workflow:

```text
.github/workflows/mes-replay-cloudflare-deploy.yml
```

The workflow now runs from `master` and is designed to perform the production cutover:

```text
checkout + Git LFS
-> pull Databento MES raw archive
-> install standalone Python replay package
-> prepare historical data
-> cloud-export replay shards
-> publish shards to R2 futureview-data/mes-replay/v1/
-> resolve/create D1 futureview-mes-replay
-> apply D1 migrations
-> deploy Cloudflare Worker as `futureview`
```

At handoff creation time, workflow run:

```text
34644394017
```

for commit:

```text
a18c3d9bd37b1dbe9751334a516f9dcb4f4ebe55
```

was **IN PROGRESS**.

First action for the next agent: inspect this run and do not assume deployment succeeded until all steps are green.

Previous Cloudflare syntax/Wrangler dry-run checks had already passed.

---

# 12. `futureview.pages.dev`

User wants the new MES replay to replace the old FutureView site and use:

```text
https://futureview.pages.dev/
```

The old site is no longer desired.

The new Worker is being deployed under the name `futureview`, but verify the actual Pages/Worker routing after production deploy. Do not claim `futureview.pages.dev` is serving the new replay until it is verified in browser/API.

Expected production checks:

```text
GET https://futureview.pages.dev/
  -> new MES Replay UI

GET https://futureview.pages.dev/api/health
  -> replay service health

GET https://futureview.pages.dev/api/contracts
  -> MES contract metadata

Start Replay
  -> session creation succeeds
  -> WebSocket connects
  -> Next releases exactly one bar
  -> Play/Pause work
  -> ET timestamps match selected time
```

If Pages still serves stale static files or `/api/*` does not route to the new Worker, fix the Cloudflare Pages/Worker integration rather than restoring the old app.

---

# 13. Tests / CI

Relevant workflows:

```text
.github/workflows/mes-replay-python.yml
.github/workflows/mes-replay-cloudflare-check.yml
.github/workflows/mes-replay-cloudflare-deploy.yml
```

Python CI verifies:

```text
standalone package installation
unit tests
real Databento month prepare
cloud shard export
FastAPI local server smoke
```

Cloudflare check verifies:

```text
browser JavaScript syntax
Worker JavaScript syntax
Wrangler deploy dry-run
```

Do not reintroduce Docker CI.

---

# 14. Important design invariants

Keep these unless explicitly changed:

1. Browser cannot see future bars.
2. Replay cursor is backend-authoritative.
3. Actual contract identity is preserved on every bar.
4. No synthetic/back-adjusted price may be used as execution truth.
5. 5m is the main replay/strategy clock.
6. Keep 1m data for later realistic fills.
7. No same-bar lookahead execution when trading is added.
8. Manual trading and automated strategies must eventually share the same execution engine.
9. Simulation rate and browser render rate are separate; 100x must not skip logical bars.
10. User-facing times are ET; storage/protocol timestamps are UTC.

---

# 15. Not implemented yet

Do not assume these exist:

```text
manual Buy/Sell/Flatten
market/limit/stop execution engine
position/account/PnL engine
commission model
slippage model
1m fill simulator
intrabar ambiguity policy
causal front-contract selector
roll execution
continuous visualization series
saved/reloadable replay sessions UI
automated Strategy adapter
batch backtest metrics
```

These are the next layers.

---

# 16. Recommended next implementation order

First verify production cutover:

```text
1. Inspect GitHub run 34644394017.
2. Fix any LFS / prepare / R2 / D1 / Wrangler failure.
3. Verify futureview.pages.dev serves the new MES Replay UI.
4. Verify /api/health and /api/contracts on the same public origin.
5. Start a real replay and verify WebSocket Play/Pause/Next.
6. Re-test ET start-time/chart alignment.
```

Then implement trading in this order:

```text
Phase A
Order / Fill / Position / Account primitives

Phase B
manual Market Buy / Sell / Flatten

Phase C
1m execution model + tick rounding + configurable slippage/commission

Phase D
Limit / Stop + conservative intrabar ambiguity rules

Phase E
causal ContractResolver + real rollover fills

Phase F
session persistence / trades / equity curve

Phase G
automated Strategy adapter using the exact same execution engine
```

Do not start ML/CNN research before the replay and execution layers are trustworthy.

---

# 17. Obsolete paths / concepts

The old root replay MVP was removed:

```text
src/futureview/replay/**
scripts/run_replay.py
requirements-replay.txt
tests/test_replay_engine.py
.github/workflows/mes-replay-mvp.yml
```

Docker replay files/workflow were also removed.

The previous master project architecture is not the active design. Do not spend time repairing old Strategy1 workflows, old dashboard pages, old TSLA research, or old model code unless the user explicitly asks for historical recovery.

---

# 18. Short handoff summary

```text
MASTER IS THE NEW MES REPLAY PROJECT.

Goal:
realistic browser-based MES historical replay/backtest.

Current:
Databento 2019-2026 raw archive
actual-contract 1m/5m processing
local Python replay
Cloudflare R2 + D1 + Durable Object + WebSocket runtime
candlestick + volume browser UI
Play/Pause/Next/Restart
1x-100x/Max
ET display / UTC storage
future-data firewall

Production:
Cloudflare deploy run 34644394017 was in progress when this handoff was written.
Verify it first.

Next major feature after production verification:
manual trading + shared realistic execution engine.
```

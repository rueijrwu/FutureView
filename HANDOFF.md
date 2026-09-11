# FutureView Replay Handoff

Last updated: 2026-09-11
Primary branch: `master`
Current head before this handoff update: `2ba73278f46d40f5f011a8369699fe6df8adf083`

FutureView is now a generic historical market replay/backtest platform. `MES` is the first configured product, not the engine identity.

## 1. Current repository structure

```text
src/futureview_replay/
tests/
cloudflare/
data/raw_sources.json
.github/workflows/
pyproject.toml
README.md
HANDOFF.md
```

Python package:

```text
futureview_replay
```

CLI:

```text
futureview-replay
```

The old `mes_replay` package name, `mes-replay/` wrapper directory, old `futureview` research package, Strategy1 workflows/docs, Docker path, and Git-LFS raw-data layout are obsolete.

## 2. Product model

Replay infrastructure is product-agnostic.

Current first product:

```text
MES
```

Current source configuration:

```text
provider: Databento
dataset: GLBX.MDP3
schema: ohlcv-1m
product: MES
primary replay resolution: 5m
fill-resolution data retained: 1m
```

Future products such as `MNQ`, `NQ`, `ES`, etc. should reuse the same package/runtime rather than creating separate replay packages.

## 3. Raw data source of truth

Raw Databento `.dbn.zst` files are no longer stored in Git or Git LFS.

The source of truth is Cloudflare R2 bucket:

```text
futureview-data
```

Generic raw layout:

```text
raw/databento/<DATASET>/<PRODUCT>/<SCHEMA>/
```

Current MES raw prefix:

```text
raw/databento/GLBX.MDP3/MES/ohlcv-1m/
```

The R2 raw manifest contains per-file object key, byte size, and SHA-256.

Verified migration snapshot:

```text
files: 89
total bytes: 52,183,820
R2 manifest SHA-256:
a90b528a1f4d9da4b886bb46581d8b570f65e279108a97cf668708b873e1f47b
```

Git stores only the source catalog in:

```text
data/raw_sources.json
```

Do not re-add raw DBN files to Git/LFS.

## 4. Local development / testing

Local testing remains required and fully supported.

Install:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
```

Fetch a small subset from R2:

```bash
futureview-replay fetch-raw \
  --product MES \
  --from 2019-05 \
  --to 2019-06
```

Local raw cache:

```text
.local-data/raw/MES/
```

Prepare:

```bash
futureview-replay prepare \
  --product MES \
  --raw .local-data/raw/MES \
  --runtime runtime/MES
```

Serve locally:

```bash
futureview-replay serve \
  --manifest runtime/MES/manifest.json \
  --host 127.0.0.1 \
  --port 8787
```

Browser:

```text
http://127.0.0.1:8787
```

Local cache/runtime directories must remain uncommitted.

## 5. Local/CI verification status

Current root-level CI has already verified the new R2-backed local path end-to-end:

```text
package install              PASS
unit tests                   PASS
fetch one real MES month R2  PASS
Databento prepare            PASS
cloud export                 PASS
local FastAPI server smoke   PASS
```

Relevant successful run:

```text
Replay Python
run: 34646767194
commit: 2ba73278f46d40f5f011a8369699fe6df8adf083
```

This means local testing no longer depends on Git LFS raw data.

## 6. Data pipeline

Current pipeline:

```text
R2 raw Databento DBN.zst
    -> local/CI fetch-raw cache
    -> actual-contract 1m Parquet
    -> independently aggregated actual-contract 5m Parquet
    -> runtime manifest
    -> compact gzip JSON replay shards
    -> R2 replay storage
```

Never aggregate bars across futures contracts.

The Databento parser currently filters quarterly outright contracts for the selected product using futures month codes:

```text
H M U Z
```

MES is current, but the product is now passed as configuration rather than hardcoded as platform identity.

## 7. Replay semantics / invariants

Keep these unless explicitly changed:

1. Browser never receives bars after the replay cursor.
2. Backend/Durable Object owns authoritative replay state.
3. Actual futures contract identity is preserved.
4. No synthetic/back-adjusted price may become execution truth.
5. 5m is the current main replay/strategy clock.
6. 1m data is retained for later realistic fills.
7. High replay speed may batch rendering but must never skip logical bars.
8. `Next`, `Play`, `Pause`, `Restart` must remain deterministic.
9. User-facing times are `America/New_York` (ET).
10. Storage/protocol timestamps are UTC.
11. A signal using a completed 5m bar must not be filled using unavailable information from that same bar.

Current speeds:

```text
1x 5x 10x 25x 50x 100x Max
```

Speed changes release rate only; 5m bar resolution does not change.

## 8. Timezone contract

This was previously a real bug.

All UI-visible times must use:

```text
America/New_York
```

This includes:

```text
start input
contract range
status time
chart x-axis
chart tooltip
```

Backend/R2 remain UTC.

Do not restore implicit browser-local conversion via:

```js
new Date(raw).toISOString()
```

for a `datetime-local` value.

Expected example:

```text
selected: 2019-05-23 09:00 ET
chart:    2019-05-23 09:00 ET
```

## 9. Cloudflare architecture

Current production architecture:

```text
Cloudflare static assets
Cloudflare Worker
Durable Object ReplaySession
R2
D1
WebSocket
```

Responsibilities:

```text
R2
  raw source archive
  replay shards

Durable Object
  active replay session
  cursor
  speed
  play/pause state
  WebSocket fanout

D1
  replay session/history persistence

Browser
  visualization and controls only
```

The public application/Worker name is:

```text
futureview
```

User ultimately wants the new replay platform at:

```text
https://futureview.pages.dev/
```

Do not claim that URL is fully cut over until it is verified live.

## 10. Replay cloud namespace

The Python/platform identity is generic now, but some production replay storage still uses the legacy compatibility prefix:

```text
mes-replay/v1
```

This is intentionally temporary to avoid breaking the existing deployed Worker during the rename.

Recommended later migration:

```text
replay/v1/<PRODUCT>/...
```

Do the namespace migration deliberately with compatibility handling; do not silently break production data lookup.

## 11. Current production deploy status

Production workflow:

```text
.github/workflows/replay-cloudflare-deploy.yml
```

Current run:

```text
run: 34646767115
commit: 2ba73278f46d40f5f011a8369699fe6df8adf083
status at handoff update: IN PROGRESS
```

Already completed successfully in that run:

```text
install generic replay package
fetch full MES raw archive from R2
build cloud replay data
```

Currently in progress at handoff update:

```text
publish replay shards to R2
```

Still pending:

```text
resolve/create D1
production config generation
D1 migrations
Worker deployment
```

First action for the next agent: inspect run `34646767115` and do not assume production deployment succeeded until all steps are green.

## 12. CI / workflow files

Only the current replay workflows should matter:

```text
.github/workflows/replay-python.yml
.github/workflows/replay-cloudflare-check.yml
.github/workflows/replay-cloudflare-deploy.yml
```

Do not reintroduce Docker CI or Git-LFS data workflows.

## 13. Current browser feature set

Current replay UI supports:

```text
actual contract selector
ET replay start time
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

TradingView Lightweight Charts is visualization only. It is not the simulation engine.

## 14. Not implemented yet

Do not assume any of the following exist:

```text
multi-product catalog UI
continuous futures visualization
causal front-contract resolver
roll execution
manual Buy/Sell/Flatten
Market/Limit/Stop execution engine
Position / Account / PnL model
commission model
slippage model
1m fill simulator
intrabar ambiguity policy
saved replay-session UI
automated Strategy adapter
batch backtest metrics
```

## 15. Recommended next implementation order

First finish production verification:

```text
1. Inspect deploy run 34646767115.
2. Confirm replay shards published to R2.
3. Confirm D1 migration and `futureview` Worker deploy succeed.
4. Verify https://futureview.pages.dev/ serves the new replay UI.
5. Verify /api/health and /api/contracts on public origin.
6. Start a real replay and test WebSocket Next/Play/Pause.
7. Re-check ET start time vs chart time.
```

Then generalize product handling:

```text
8. Add product catalog/selector.
9. Make replay cloud storage product-aware.
10. Migrate legacy mes-replay/v1 namespace safely.
```

Then add trading/execution:

```text
11. Order / Fill / Position / Account primitives.
12. Manual Market Buy / Sell / Flatten.
13. 1m fill model + tick rounding + configurable commission/slippage.
14. Limit / Stop orders and conservative intrabar ambiguity handling.
15. Causal ContractResolver and real rollover fills.
16. Session/trade/equity persistence.
17. Automated Strategy adapter using the exact same execution engine.
```

Do not start ML/CNN strategy research before replay and execution semantics are trustworthy.

## 16. Short summary

```text
MASTER = generic FutureView Replay platform.

Package:
futureview_replay

CLI:
futureview-replay

MES:
first configured product only.

Raw source of truth:
Cloudflare R2, not Git/LFS.

Raw R2 verification:
89 files / 52,183,820 bytes.

Local test:
R2 fetch -> prepare -> export -> server smoke = PASS.

Replay:
5m authoritative cursor, 1m retained for future fills,
no-lookahead, actual-contract prices, ET display / UTC storage.

Production:
run 34646767115 is still in progress at this handoff update.
Verify it first.

Next major feature after production verification:
multi-product catalog, then shared realistic trading/execution engine.
```

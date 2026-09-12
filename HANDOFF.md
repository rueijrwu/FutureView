# FutureView Replay Handoff

Last updated: 2026-09-11
Primary branch: `master`
Current head before this handoff update: `e0ac9300e4ad7c853876afa206eb0408e70283a4`

FutureView is now a generic historical market replay/backtest platform. `MES` is the first configured product, not the engine identity.

## 1. Current repository structure

```text
src/futureview_replay/
tests/
cloudflare/
site/
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

## 2. Product/data model

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

Raw source of truth is Cloudflare R2 bucket:

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

Verified migration snapshot:

```text
files: 89
total bytes: 52,183,820
R2 manifest SHA-256:
a90b528a1f4d9da4b886bb46581d8b570f65e279108a97cf668708b873e1f47b
```

Do not re-add raw DBN files to Git/LFS.

## 3. Local fetch / prepare

Install:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
```

`fetch-raw` no longer shells out to `npx wrangler`. It now downloads R2 objects directly from Python using the Cloudflare REST API.

Required environment:

```bash
export CLOUDFLARE_API_TOKEN=...
export CLOUDFLARE_ACCOUNT_ID=...
```

`R2_ACCOUNT_ID` is also accepted as the account-id fallback.

Example:

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

Local cache/runtime directories must remain uncommitted.

## 4. Data pipeline

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

The 5m aggregation is:

```text
open   = first
high   = max
low    = min
close  = last
volume = sum
```

A small candle with nonzero volume is valid when all trades in that 5m interval occur at the same or nearby tick prices. This was specifically observed/questioned for early low-liquidity periods of contracts such as `MESH1`; do not assume it is an aggregation bug without checking actual OHLC.

## 5. Replay semantics / invariants

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
12. Replay start accepts product + time; users do not preselect an actual contract.
13. Contract selection uses only the preceding completed CME session's volume.
14. The resolver may hold the active contract or roll once to the next listed quarterly contract; it never rolls backward or skips a contract.

Current speeds:

```text
1x 5x 10x 25x 50x 100x Max
```

## 6. Production architecture

The public frontend is Cloudflare Pages:

```text
https://futureview.pages.dev/
```

The backend is the Cloudflare Worker:

```text
https://futureview.rueijrwu.workers.dev/
```

The Worker URL is backend infrastructure, not the intended user-facing site.

Architecture:

```text
Cloudflare Pages (`site/`)
        |
        | HTTPS / WebSocket
        v
Cloudflare Worker `futureview`
        |
        +-- Durable Object ReplaySession
        +-- R2
        +-- D1
```

Responsibilities:

```text
Pages/site/
  current Replay UI only
  no requirement to preserve the old static dashboard

Worker
  /api/health
  /api/contracts
  /api/replay/range
  replay-session creation
  causal actual-contract resolution
  WebSocket routing
  CORS for https://futureview.pages.dev

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
```

Do not attempt to migrate to `futureview.rueijrwu.dev`; `rueijrwu.dev` is not currently a Cloudflare-managed/active zone. Custom-domain experiments were reverted.

## 7. Deployment workflows

Production Worker deployment is intentionally separated from replay-data publishing.

Current workflows:

```text
.github/workflows/replay-python.yml
.github/workflows/replay-cloudflare-check.yml
.github/workflows/replay-cloudflare-deploy.yml
.github/workflows/replay-data-publish.yml
.github/workflows/replay-pages-deploy.yml
```

### Worker deploy

`.github/workflows/replay-cloudflare-deploy.yml`

Normal Worker deploy no longer does:

```text
fetch all MES raw
prepare full dataset
cloud-export full dataset
upload all replay shards
```

It now only handles Worker/D1 deployment. This reduced a normal deploy from >10 minutes to about 35 seconds in the first verified run.

Verified successful Worker deploy after decoupling:

```text
run: 34647997566
commit: 581b936755c4b5dba23724b868e6d23c309b92ae
status: SUCCESS
```

Latest Worker deploy adding Pages CORS:

```text
run: 34650853125
commit: 746132ed9caf28c5abf13a764ee2c95943812406
status: SUCCESS
```

### Replay data publish

`.github/workflows/replay-data-publish.yml`

Full replay-data rebuild/publish is separate from application deployment. Cloud manifest version 3 includes a causal contract-selection calendar generated from the actual 5m bars.

`cloudflare/publish-r2.sh` now uses bounded parallel uploads (default 12 concurrent) and uploads `manifest.json` last so readers do not observe a manifest before all shards are present.

A future improvement is deterministic gzip + shard SHA-256 manifest + true incremental publish. Do not implement hash-based skipping until export determinism/content identity is explicit.

### Pages deploy

`.github/workflows/replay-pages-deploy.yml`

This explicitly deploys `site/` to Cloudflare Pages project:

```text
project: futureview
production branch: master
public URL: https://futureview.pages.dev/
```

First explicit Pages deploy:

```text
run: 34651057136
commit: 8c3b29b8b45c79d2fa52e5b486a1131502957123
status: SUCCESS
```

The workflow successfully completed both:

```text
Ensure FutureView Pages project exists   PASS
Deploy replay frontend to Pages          PASS
```

The public URL still needs a browser-level smoke verification after this handoff update; do not infer UI/WebSocket correctness solely from workflow success.

## 8. Frontend state

The active Pages frontend is in:

```text
site/index.html
site/style.css
site/app.js
site/chart-tools.js
```

It is the new Replay UI, not the old dashboard.

Current browser feature set:

```text
product (currently MES)
ET replay start time
warmup bar count
automatic actual-contract selection
candlestick chart
volume histogram
OHLCV crosshair legend
SMA 20 / SMA 50
CME-session VWAP
magnet crosshair
horizontal price lines with undo/clear
zoom in/out, fit, latest
linear/log price scale
Restart
Next
Play
Pause
1x / 5x / 10x / 25x / 50x / 100x / Max
current contract
current cursor
current replay state
```

The browser sends `product`, `start`, and `warmup`; it does not send a contract. The Worker resolves the contract from the version-3 selection calendar and returns the contract plus the causal selection reason.

`site/app.js` currently calls the backend Worker origin directly:

```text
https://futureview.rueijrwu.workers.dev
```

Worker responses include CORS for:

```text
https://futureview.pages.dev
```

WebSocket sessions also connect to the Worker origin.

KLineCharts is visualization only. It is not the simulation engine.

Rich chart tools (SMA20/50, VWAP, and TradingView-style drawing tools — trend line, ray, horizontal/vertical line, rectangle, circle, fibonacci retracement, parallel channel, text) are implemented in `chart-tools.js` on top of KLineCharts' built-in indicator/overlay APIs. Indicators consume only the warmup and bars already released to the browser, preserving the no-lookahead boundary.

## 9. Replay cloud namespace

The Python/platform identity is generic now, but production replay storage still uses the legacy compatibility prefix:

```text
mes-replay/v1
```

This is intentionally temporary.

Recommended later migration:

```text
replay/v1/<PRODUCT>/...
```

Do the namespace migration deliberately with compatibility handling.

## 10. Not implemented yet

Do not assume any of the following exist:

```text
multi-product catalog UI
continuous futures visualization
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

## 11. Recommended next actions

First verify the automatic-contract deployment:

```text
1. Open https://futureview.pages.dev/ and confirm the new Replay UI is served.
2. Verify the UI asks for product + ET start time, with no contract selector.
3. Start replays before and after a historical rollover and verify the returned actual contract and `contract_selection` reason.
4. Test WebSocket Next/Play/Pause.
5. Re-check ET start time, 18:00 ET session boundary, and chart time.
6. Verify direct Worker /api/health still returns healthy state.
```

Then improve contract UX:

```text
7. Consider a clearly defined `liquid_start` / recommended replay start, while preserving full actual-contract history.
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
15. Apply the resolved calendar during long-running replay and implement real rollover fills.
16. Session/trade/equity persistence.
17. Automated Strategy adapter using the exact same execution engine.
```

Do not start ML/CNN strategy research before replay and execution semantics are trustworthy.

## 12. Recent commits of interest

```text
8cd8516  ci: decouple replay data publish from production deploy
cb140e4  ci: parallelize replay shard publishing
3f92d1a  ci: add dedicated replay data publish workflow
581b936  ci: narrow production deploy triggers
15fc13e  fix: fetch R2 raw data without npx wrangler
d0edf47  test: cover direct R2 raw fetch helpers
0ca1b7f  ci: remove Node dependency from replay Python checks
8239bcf  revert: keep existing workers.dev deployment
fa7bfee  deploy: restore FutureView Pages frontend
26d5bbf  deploy: restore FutureView Pages styling
81cad04  deploy: use Pages frontend for replay UI
746132e  deploy: allow Pages frontend to call replay API
8c3b29b  deploy: publish replay frontend to FutureView Pages
```

## 13. Short summary

```text
MASTER = generic FutureView Replay platform.

Frontend/public URL:
https://futureview.pages.dev/

Backend Worker:
https://futureview.rueijrwu.workers.dev/

Package:
futureview_replay

CLI:
futureview-replay

MES:
first configured product only.

Raw source of truth:
Cloudflare R2, not Git/LFS.

fetch-raw:
Python direct Cloudflare R2 REST; no npx/wrangler subprocess.

Replay:
5m authoritative cursor, 1m retained for future fills,
no-lookahead, actual-contract prices, ET display / UTC storage.

Contract selection:
product + ET time input; prior completed CME-session volume;
hold or roll once to the next quarterly contract; no manual preselection.

Deploy:
Worker deploy, replay-data publish, and Pages deploy are separate workflows.

Latest Pages deployment:
run 34651057136 = SUCCESS.

Next immediate task:
verify https://futureview.pages.dev/ end-to-end, including automatic contract resolution, API, and WebSocket replay.
```

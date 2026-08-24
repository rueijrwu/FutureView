# FutureView

FutureView is a point-in-time U.S. equity research platform for systematic screening, ranking, portfolio research, and backtesting.

## Current phase

FutureView is in a **manual testing phase**.

- Development is Codespaces-first and JavaScript-only.
- Cloudflare Cron/scheduled execution is disabled.
- Production updates are manual until the research pipeline is validated end to end.
- D1 and R2 remain the production data contracts.
- GitHub Actions handles CI, deployment, and manual recovery.
- Automated brokerage order execution is out of scope.

## Architecture

```text
GitHub Codespaces
  ├─ local D1 / local R2
  ├─ production snapshot sync (read-only)
  ├─ JS tests / replay / backtest development
  └─ React/Vite development
          ↓
GitHub
  ├─ source control
  ├─ CI
  ├─ deployment
  └─ manual feature-state recovery
          ↓
Cloudflare
  ├─ Worker API
  ├─ Workflows (manually initiated during testing)
  ├─ D1 relational/index data
  └─ R2 market/state/artifact storage
          ↑
       Massive
```

One canonical JavaScript strategy engine is shared by ranking, replay validation, and backtesting. `worker/strategy-config.js` is the strategy configuration source of truth.

## Data responsibilities

### D1

D1 stores compact, queryable state:

- instruments
- dated common-stock universe membership
- ranking runs and ranking history
- strategy versions
- workflow metadata
- backtest metadata

### R2

R2 stores bulk and reproducible artifacts:

```text
prices/daily-json/date=YYYY-MM-DD/bars.json
reference/tickers/date=YYYY-MM-DD/common-stocks.json
state/rolling/v1/date=YYYY-MM-DD/shard=00..31.json
features/daily/date=YYYY-MM-DD/shard=00..31.json
rankings/date=YYYY-MM-DD/ranking.json
rankings/date=YYYY-MM-DD/top50.json
state/ranking/v1/date=YYYY-MM-DD/shard=00..31.json
validation/js-replay/date=YYYY-MM-DD/...
backtests/run=<id>/result.json
dashboard/latest.json
metadata/latest-*.json
```

Latest pointers are promoted only after the corresponding date-scoped artifacts are complete.

## Stock universe

The stock screener ranks active U.S. common stocks classified by Massive as `type=CS`.

ETFs and other instruments may remain in retained market data but are not eligible for the stock Top 50. SPY remains available to the feature engine as the current relative-strength benchmark.

## Ranking model

The current `momentum-v2` model targets sustainable leadership over roughly 3 weeks to 3 months:

```text
StockScore =
  25% RS20
+ 20% RS60
+ 20% Trend
+ 15% Breakout
+ 10% Volume
+ 10% Persistence
- ExtensionPenalty
```

Hard filters include:

- price > $10
- 20-session average dollar volume > $50M
- close > SMA50 > SMA200
- positive SMA50 slope
- positive relative strength versus SPY
- close no more than 3 ATR above SMA20

The extension penalty begins at 1.5 ATR and reaches a maximum penalty of 0.12 at the 3-ATR hard cap. Missing historical ranks are represented as `NEW`, not zero.

## Backtest baseline

The JS backtest uses the same strategy data contract as production ranking. Baseline assumptions:

- Top-10 breakout candidates
- maximum 10 positions
- equal notional allocation
- 15-session minimum hold
- 60-session maximum hold
- SMA10 exit after the minimum hold
- signals formed at close execute at the next session open

The next-open rule prevents same-session look-ahead.

## API

Current Worker read routes:

- `GET /api/health`
- `GET /api/rankings/latest`
- `GET /api/rankings/history`
- `GET /api/rankings/date/YYYY-MM-DD`
- `GET /api/symbols/:symbol/rankings`
- `GET /api/ingest/status`
- `GET /api/universe/status`
- `GET /api/state/status`
- `GET /api/ranking-state/status`
- `GET /api/replay/status`
- `GET /api/backtests/latest`

Current manual admin route:

- `POST /api/admin/refresh-universe`

Additional daily processing remains intentionally manual/deferred during the testing phase rather than being driven by Cron.

## Codespaces development

Create a GitHub Codespace and run:

```bash
npm run local:setup
npm run local:sync
npm run local:dev
```

`local:setup` initializes local D1, installs frontend dependencies, runs migrations, syntax checks, regression tests, lint, and build.

`local:sync` reads production D1/R2 through the restricted Cloudflare token and writes a snapshot only into local Wrangler state. Production is never modified by this command.

Before pushing changes:

```bash
npm run local:check
```

See [`docs/CODESPACES.md`](docs/CODESPACES.md) for the development runbook.

## Recovery

Feature-state recovery is manual and lives outside the normal runtime:

- **Recover Feature State (Repair)** validates and re-promotes an existing trustworthy 32-shard state.
- **Recover Feature State (Full Rebuild)** rebuilds rolling state from Massive using GitHub Actions and Node.js.

See [`docs/FEATURE_STATE_RECOVERY.md`](docs/FEATURE_STATE_RECOVERY.md).

## Repository layout

- `worker/` — Worker API, canonical strategy runtime, Workflows, replay, backtest
- `migrations/` — ordered D1 migrations
- `tools/local/` — Codespaces/local setup and read-only production snapshot sync
- `tools/recovery/` — manual feature-state recovery utilities
- `tests-js/` — JavaScript regression tests
- `view/` — React/Vite frontend development tree
- `site/` — currently deployed static assets
- `docs/` — operational runbooks only
- `wrangler.jsonc` — Cloudflare bindings; no Cron triggers during testing

## Safety rules

- JavaScript only; do not reintroduce Python runtime paths.
- Never hardcode API keys, account IDs, tokens, or D1 database UUIDs.
- D1 schema changes require ordered migrations.
- Write dated R2 artifacts before promoting latest pointers.
- Keep replay/backtest point-in-time and free of look-ahead.
- Do not make Codespaces development credentials capable of writing production data unless explicitly redesigned.

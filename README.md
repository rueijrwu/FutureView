# FutureView

FutureView is a point-in-time U.S. equity research platform for systematic screening, ranking, portfolio research, and backtesting.

## Core principles

- One canonical JavaScript strategy engine is shared by production ranking, replay validation, and backtesting.
- Cloudflare owns production scheduling and execution.
- D1 is the relational query/index layer.
- R2 stores bulk market data and reproducible research artifacts.
- Massive supplies market and reference data.
- GitHub is source control, CI, and deployment only.
- Routine market updates never create Git commits.
- Automated order execution is intentionally out of scope.

## Production flow

```text
Cloudflare Worker Cron
  ↓
Massive common-stock universe refresh
  ↓
Massive grouped-daily OHLCV ingest
  ↓
FeatureBootstrapWorkflow (fresh environment only)
  or
IncrementalFeatureWorkflow
  ↓
canonical JS ranking core
  ↓
D1 ranking index + R2 ranking/state snapshots
  ↓
latest pointer promotion
  ↓
JS replay validation
```

A weekly Worker cron starts the JS backtest Workflow over production ranking snapshots.

## Storage responsibilities

### D1

- instruments and common-stock universe membership
- universe snapshot index
- ranking run metadata
- ranking entries and rank history
- strategy versions
- workflow/backtest metadata

### R2

- daily OHLCV JSON
- rolling feature-state shards
- daily feature shards
- full ranking and Top-50 snapshots
- ranking-state shards
- replay validation artifacts
- backtest results
- dashboard presentation payloads

## Screener

The ranking universe is active U.S. common stocks (`type=CS`) from Massive. ETFs remain outside the stock Top-50 ranking and can later support market-regime research.

The current ranking model combines:

- 20-session relative strength
- 60-session relative strength
- trend quality
- breakout/proximity strength
- volume confirmation
- 20-session Top-50 persistence
- ATR-based extension penalty

Hard filters include minimum price/liquidity, `close > SMA50 > SMA200`, positive SMA50 slope, positive relative strength, and a 3-ATR extension ceiling.

The canonical strategy configuration lives in `worker/strategy-config.js`.

## Backtest baseline

The JS backtest uses production ranking snapshots and next-session-open execution so signals formed at a session close cannot trade at that same close. The initial baseline uses Top-10 breakout candidates, up to 10 positions, 15–60 session holding windows, and an SMA10 exit rule. Backtest assumptions are separately versioned from ranking rules.

## API

Current Worker routes include:

- `GET /api/health`
- `GET /api/rankings/latest`
- `GET /api/rankings/history`
- `GET /api/rankings/date/YYYY-MM-DD`
- `GET /api/symbols/:symbol/rankings`
- `GET /api/ingest/status`
- `GET /api/universe/status`
- `GET /api/state/status`
- `GET /api/bootstrap/status`
- `GET /api/ranking-state/status`
- `GET /api/replay/status`
- `GET /api/backtests/latest`

## Repository layout

- `worker/` — canonical JS runtime, strategy, Workflows, API, replay, backtest
- `migrations/` — D1 migrations
- `site/` — deployed static assets consumed through the Worker API
- `view/` — React/Vite frontend development tree
- `tests-js/` — JavaScript regression tests
- `docs/` — design and roadmap documentation
- `wrangler.jsonc` — Cloudflare Worker/Workflow/Cron configuration

## Deployment

`.github/workflows/deploy-worker.yml` resolves or creates the `futureview` D1 database, applies all D1 migrations, generates the runtime D1 binding, and deploys the Worker/Workflows. The D1 database ID is not hardcoded in the repository.

`.github/workflows/ci.yml` runs JavaScript syntax checks, regression tests, D1 migration validation, and frontend lint/build checks.

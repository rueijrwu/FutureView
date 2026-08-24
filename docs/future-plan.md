# Future Plan

## Target architecture

FutureView is a Cloudflare-native, JavaScript-only research platform. GitHub is limited to source control, documentation, JavaScript CI, and deployment. Cloudflare owns production scheduling, Massive ingestion, feature computation, ranking, replay validation, backtesting, persistence, API delivery, and the deployed web application.

```text
GitHub
  └─ source + CI + deployment
          ↓
Cloudflare Worker Cron
  ├─ weekday: universe → ingest → features → ranking → replay
  └─ Sunday: JS backtest
          ↓
Cloudflare Workflows
  ├─ FeatureBootstrapWorkflow
  ├─ IncrementalFeatureWorkflow
  ├─ RankingReplayWorkflow
  └─ BacktestWorkflow
          ↓
      D1 + R2
          ↓
      Worker API
```

FutureView has one canonical JavaScript strategy engine. Live ranking, replay, and backtest paths must reuse the same ranking/configuration modules.

## D1 + R2 responsibilities

### D1 — relational/query layer

Current schema includes:

- `instruments`
- `universe_snapshots`
- `universe_membership`
- `ranking_runs`
- `ranking_entries`
- `strategy_versions`
- `workflow_runs`
- `backtest_runs`

D1 is used for structured discovery, rank history, instrument/universe metadata, strategy versions, and backtest/run indexes.

### R2 — analytical artifact layer

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

Large market, feature, state, replay, and backtest payloads stay in R2. D1 stores compact searchable indexes pointing to them.

## Production pipeline

Weekday Cron:

```text
Massive ticker reference
  ↓
JS common-stock universe refresh
  ↓
D1 instruments/universe + R2 dated universe snapshot
  ↓
Massive grouped-daily ingest
  ↓
feature state exists?
  ├─ no  → FeatureBootstrapWorkflow → 211 historical sessions → rolling state
  └─ yes → IncrementalFeatureWorkflow
              ↓
          daily feature shards
              ↓
          canonical JS ranking core
              ↓
          date-scoped ranking + ranking-state artifacts
              ↓
          D1 ranking index / strategy version
              ↓
          promote latest pointers
              ↓
          RankingReplayWorkflow
```

The bootstrap path allows a fresh deployment to create its rolling feature state without another runtime. It uses historical Massive grouped-daily sessions, partitions them into the same 32 deterministic symbol shards, and then automatically starts the normal incremental pipeline.

Latest pointers are promoted only after complete date-scoped feature/ranking artifacts and required D1 writes succeed.

## Canonical ranking engine

`worker/strategy-config.js` is the configuration source of truth. The current strategy version is `momentum-v2`.

Ranking components:

- RS20: 25%
- RS60: 20%
- trend: 20%
- breakout/proximity: 15%
- volume: 10%
- persistence: 10%
- ATR extension penalty

Hard filters include price/liquidity, `close > SMA50 > SMA200`, positive SMA50 slope, positive RS20/RS60, and a 3-ATR extension ceiling.

Ranking keys are quantized for deterministic ordering and tied scores use symbol-ascending ordering. Missing numeric inputs are rejected rather than coerced to zero.

## JS replay validation

After a completed production ranking, a child RankingReplayWorkflow automatically recomputes the same date using the canonical JS engine.

Validation checks:

- candidate coverage
- numeric scoring fields within tolerance
- exact ordered Top50

Artifacts are written under `validation/js-replay/`, with `metadata/latest-js-replay.json` exposing the latest status. No cross-language comparison is used.

## JS backtest

A Sunday Worker Cron starts `BacktestWorkflow` over the latest 126 production ranking sessions when available.

Baseline execution assumptions:

- Top-10 breakout candidates
- maximum 10 positions
- equal notional allocation
- 15-session minimum hold
- 60-session maximum hold
- SMA10 exit after the minimum hold
- signals formed at close execute at the **next trading session open**

The next-open rule prevents same-session look-ahead. Detailed results go to R2; run status and summary metadata go to D1.

## API

Current D1-first / R2-backed routes include:

```text
/api/health
/api/rankings/latest
/api/rankings/history
/api/rankings/date/YYYY-MM-DD
/api/symbols/:symbol/rankings
/api/ingest/status
/api/universe/status
/api/state/status
/api/bootstrap/status
/api/ranking-state/status
/api/replay/status
/api/backtests/latest
```

## Deployment and database provisioning

Deployment is automated by GitHub Actions:

1. resolve an existing D1 database named `futureview`, or create it;
2. generate the Worker D1 binding without hardcoding the database UUID;
3. apply ordered migrations in `migrations/`;
4. deploy Worker, Workflows, static assets, and Cron triggers.

CI validates Worker JavaScript syntax, JS regression tests, every D1 migration from an empty SQLite database, and frontend lint/build.

## Completed migration milestones

1. Cloudflare Worker API + R2 binding. **Completed.**
2. Cloudflare Massive daily ingestion. **Completed.**
3. JS incremental feature/state Workflow. **Completed.**
4. JS production ranking + ranking-state publisher. **Implemented.**
5. Remove non-JS runtime/package/test paths. **Completed.**
6. JS-only CI. **Completed.**
7. JS Massive common-stock universe refresh. **Implemented.**
8. D1 schema, migrations, and automatic provisioning. **Implemented.**
9. D1 instrument/universe persistence. **Implemented.**
10. D1 ranking metadata/index. **Implemented.**
11. D1-first historical ranking/symbol APIs with R2 fallback. **Implemented.**
12. JS-only replay/regression validation. **Implemented.**
13. JS-only backtest core + Workflow + weekly trigger. **Implemented.**
14. Fresh-environment JS feature-state bootstrap. **Implemented.**

`Implemented` means code is on `master`; production success must still be confirmed by the corresponding Cloudflare/GitHub execution logs before being marked validated.

## Next research/product milestones

1. Production validation of D1 provisioning, migrations, bootstrap, daily ranking, replay, and weekly backtest.
2. Add ETF market-regime engine and D1/R2 regime storage.
3. Add portfolio/watchlist D1 tables and research APIs.
4. Add richer backtest analytics, transaction-cost/slippage assumptions, and parameterized research runs.
5. Add symbol detail views and historical date selection to the frontend.
6. Remove the legacy committed static dashboard fallback once dynamic API delivery is confirmed stable.

## Steady state

```text
GitHub
  = source + JS CI + deployment

Cloudflare Worker / Workflows
  = all research and production execution

D1
  = relational metadata, history, indexes, application state

R2
  = market data and large reproducible research artifacts

Daily
  = Cron → Massive → JS features → JS ranking → D1/R2 → JS replay

Weekly
  = Cron → JS backtest → D1 summary + R2 result

Browser
  = Worker API → D1 and/or R2
```

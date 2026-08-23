# Future Plan

## Formal system architecture

FutureView adopts a Cloudflare-native, database-first dynamic-web architecture. GitHub is limited to source control, code review, documentation, CI, and deployment triggers. Production scheduling, market-data ingestion, persistent research state, API delivery, and the interactive web application belong on Cloudflare.

```text
GitHub
  ├─ source code
  ├─ strategy/configuration
  ├─ tests and CI
  └─ deployment history
        │
        │ code changes only
        ↓
Cloudflare production platform
  ├─ Scheduled Worker / Workflow
  │      ↓
  │    Massive
  │      ↓
  │    daily market-data update
  │      ↓
  │    incremental research-state update
  │      ↓
  ├─ R2
  │    ├─ raw prices
  │    ├─ rolling feature state
  │    ├─ daily feature shards
  │    ├─ rankings
  │    ├─ regime
  │    └─ presentation JSON
  │
  ├─ Worker API
  │      ↓
  └─ Dynamic frontend
```

Routine market-data, ranking, regime, or portfolio-state changes must not create Git commits and must not require a frontend redeployment.

### Current production split

Cloudflare owns daily Massive ingestion. The scheduled Worker writes normalized daily JSON to R2 under:

```text
prices/daily-json/date=YYYY-MM-DD/bars.json
metadata/latest-cloudflare-ingest.json
```

A Cloudflare Workflow is now the next production stage. It runs after ingestion, reads the versioned rolling state plus the new daily bar set, updates 32 state shards, and writes the corresponding feature cross-section:

```text
state/rolling/v1/date=YYYY-MM-DD/shard=00..31.json
features/daily/date=YYYY-MM-DD/shard=00..31.json
metadata/latest-feature-state.json
metadata/latest-incremental-features.json
```

The Workflow uses staged writes and updates `metadata/latest-feature-state.json` only after every shard succeeds. A partial Workflow failure therefore cannot publish a half-updated production state.

The existing historical Parquet archive remains in R2 and continues to support the batch research engine. GitHub Actions temporarily retains the Daily Scanner as a reference/fallback path while Cloudflare incremental output is validated against the canonical Python implementation.

Current production timing:

```text
23:30 UTC  Cloudflare Worker: Massive daily ingestion
23:40 UTC  Cloudflare Workflow: incremental feature/state update
23:45 UTC  GitHub Daily Scanner: temporary batch reference/fallback
```

### Deployment boundary

A Cloudflare deployment is required only when application or research-engine code changes. Routine new sessions and derived research-state updates stay entirely inside Cloudflare/R2.

## Production research engine

The Python/Polars batch engine remains the canonical research and backtest implementation. The incremental engine must preserve feature parity with it before it is allowed to replace the batch production scanner.

Incremental state contract v1 maintains only finite rolling windows needed for the current strategy:

- close history for SMA5/10/20/50/200 and return20/60;
- high history for prior 20/50-session breakout levels;
- volume history for average volume and volume ratio;
- true-range history for ATR14;
- SMA50 history for the 10-session slope.

The daily update model is:

```text
previous 32 state shards
        +
new Cloudflare OHLCV
        ↓
partition bars by deterministic symbol shard
        ↓
32 durable Workflow update steps
        ↓
new state shards + daily feature shards
        ↓
atomic metadata-pointer promotion
```

The historical batch engine remains necessary for reproducible backtesting, validation, strategy changes, and full recomputation when methodology changes.

## R2 data responsibilities

```text
prices/
  daily/date=YYYY-MM-DD/bars.parquet      # historical archive
  daily-json/date=YYYY-MM-DD/bars.json    # Cloudflare production ingestion

state/
  rolling/v1/...                          # versioned incremental rolling state

features/
  daily/date=YYYY-MM-DD/shard=00..31.json

rankings/
  date=YYYY-MM-DD/ranking.parquet
  date=YYYY-MM-DD/top50.parquet

dashboard/
  latest.json

metadata/
  latest-cloudflare-ingest.json
  latest-feature-state.json
  latest-incremental-features.json
  latest-ranking.json

reference/
  tickers/...

regime/
  date=YYYY-MM-DD/regime.json
```

## ETF market-regime analysis

ETF market data remains part of retained raw OHLCV history, but ETFs are excluded from the stock screener and Top-50 ranking. A later market-regime module will estimate an allowed tactical-capital ceiling rather than generate stock candidates.

Actual tactical allocation remains the minimum of market risk capacity, available high-quality setups, and portfolio risk limits.

## Dynamic web application

The web application is a read-oriented interactive research interface over precomputed R2 outputs. Planned capabilities include latest and historical rankings, ticker detail views, rank trajectories, filters, historical date selection, ETF regime views, and later portfolio/backtest interfaces.

## Migration sequence

1. Worker `/api/health`. **Completed.**
2. R2 binding and `/api/rankings/latest`. **Completed.**
3. Frontend prefers API over committed static ranking data. **Completed.**
4. Stop committing daily dashboard snapshots to `master`. **Completed.**
5. Validate Worker production delivery, then remove the legacy static JSON fallback. **Pending.**
6. Move daily Massive ingestion to Cloudflare Cron. **Completed.**
7. Store normalized daily bars and ingestion metadata directly in R2. **Completed.**
8. Make the scanner consume Cloudflare-produced daily data while retaining historical Parquet. **Completed.**
9. Remove daily Massive ingestion from GitHub Actions; keep scanner-only temporarily. **Completed.**
10. Define and persist incremental rolling-state contract with batch parity tests. **Completed.**
11. Run incremental feature/state updates in a scheduled Cloudflare Workflow. **Implemented; production validation pending.**
12. Add incremental cross-sectional ranking/persistence and compare against batch ranking.
13. Remove GitHub Actions production scanner once parity is established; retain CI/tests/lint/deployment only.
14. Expand Worker API to historical rankings, symbol views, ETF regime data, portfolio research, and backtest results.
15. Optionally consolidate static frontend delivery into Workers Static Assets.

## Target steady state

```text
GitHub
  = version control + CI

Cloudflare
  = production scheduler + runtime + R2 + API + dynamic web

Daily market update
  = Cloudflare scheduled execution → Massive → R2 → incremental ranking/state update

User request
  = Browser → Worker API → R2
```

Routine daily operation must require no Git commit and no site redeployment. Only promoted code or configuration changes should create a new application deployment.

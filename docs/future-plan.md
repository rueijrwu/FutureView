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
  │    research-state update
  │      ↓
  ├─ R2
  │    ├─ raw prices
  │    ├─ reference metadata
  │    ├─ feature state
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

Cloudflare now owns daily Massive ingestion. The scheduled Worker writes normalized daily JSON to R2 under:

```text
prices/daily-json/date=YYYY-MM-DD/bars.json
metadata/latest-cloudflare-ingest.json
```

The existing historical Parquet archive remains in R2 and continues to support the batch research engine. The scanner merges historical Parquet with newer Cloudflare JSON sessions, preferring Cloudflare data when the same symbol/date exists in both sources.

GitHub Actions is temporarily scanner-only. It no longer performs daily Massive ingestion. This is an intermediate step before moving the scanner itself to Cloudflare.

### Deployment boundary

A Cloudflare deployment is required only when application or research-engine code changes, for example:

- HTML, CSS, or JavaScript UI changes;
- Worker API code or routing changes;
- scanner / feature-engine implementation changes;
- strategy configuration changes intentionally promoted to production;
- application-level static assets.

A deployment is not required for routine production data changes such as a new trading session, a new Top-50 ranking, daily feature-state updates, future ETF regime values, or portfolio outputs.

## Production research engine

The research engine remains the single source of truth for trading logic. The web layer must never independently recompute SMA, ATR, relative strength, persistence, ranking scores, market regime, or portfolio signals.

The current batch implementation uses Python, Polars, PyArrow, historical Parquet files, and Cloudflare-produced daily JSON. This remains the reference implementation for reproducible research and backtesting.

The production path should evolve toward an incremental state model:

```text
previous feature state
        +
new daily OHLCV
        ↓
incremental rolling update
        ↓
latest feature state
        ↓
stock ranking / regime
        ↓
R2 published outputs
```

Examples of incrementally maintainable state include rolling SMA windows, ATR state, 20/60-day reference closes, high/low windows, dollar-volume windows, ranking persistence, and market-regime inputs.

The historical batch engine remains necessary for reproducible backtesting, validation, strategy changes, and full recomputation when methodology changes.

## R2 data responsibilities

```text
prices/
  daily/date=YYYY-MM-DD/bars.parquet      # historical archive
  daily-json/date=YYYY-MM-DD/bars.json    # Cloudflare production ingestion

state/
  latest/features.parquet
  latest/rolling-state.parquet

rankings/
  date=YYYY-MM-DD/ranking.parquet
  date=YYYY-MM-DD/top50.parquet

dashboard/
  latest.json

metadata/
  latest-cloudflare-ingest.json
  latest-market-data.json
  latest-ranking.json

reference/
  tickers/...

regime/
  date=YYYY-MM-DD/regime.json
```

Large Parquet datasets support research and backtests. Compact JSON objects support production ingestion and low-latency API/web delivery.

## ETF market-regime analysis

ETF market data remains part of retained raw OHLCV history, but ETFs are excluded from the stock screener and Top-50 ranking.

A later market-regime module will use SPY, QQQ, IWM, DIA, sector ETFs, HYG/LQD, TLT, GLD, and related ratios to estimate an allowed tactical-capital ceiling rather than generate stock candidates.

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
8. Make the scanner consume Cloudflare-produced daily data while retaining historical Parquet. **Completed in current cutover.**
9. Remove daily Massive ingestion from GitHub Actions; keep scanner-only temporarily. **Completed in current cutover.**
10. Introduce incremental production feature/ranking state. **Next major step.**
11. Move production scanner into Cloudflare Workflow.
12. Remove GitHub Actions production scanner entirely; GitHub Actions remains for CI/tests/lint/deployment only.
13. Expand Worker API to historical rankings, symbol views, ETF regime data, portfolio research, and backtest results.
14. Optionally consolidate static frontend delivery into Workers Static Assets.

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

# Future Plan

## Formal system architecture

FutureView adopts a Cloudflare-native, database-first dynamic-web architecture. GitHub is deliberately limited to source control, code review, documentation, CI, and deployment triggers. Production scheduling, market-data ingestion, research-state updates, API delivery, and the interactive web application belong on Cloudflare.

The long-term operating principle is:

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

GitHub must not act as the production scheduler or as a transport layer for daily market data. Routine market-data, ranking, regime, or portfolio-state changes must not create Git commits and must not trigger a frontend deployment.

### Responsibility boundary

GitHub owns:

- Python, JavaScript, Worker, and frontend source code;
- `strategy.yaml` and other strategy configuration;
- tests, Ruff, and CI checks;
- documentation and architecture history;
- controlled deployment of production code when code changes.

Cloudflare owns:

- scheduled production execution;
- Massive API ingestion;
- persistent R2 storage;
- published research state;
- Worker API endpoints;
- dynamic frontend delivery;
- retries, monitoring, and later multi-step production workflows.

R2 is the persistent source of truth for market data and published research outputs. Git is the source of truth for code and configuration only.

### Deployment boundary

A Cloudflare deployment is required only when application or research-engine code changes, for example:

- HTML, CSS, or JavaScript UI changes;
- Worker API code or routing changes;
- scanner / feature-engine implementation changes;
- strategy configuration changes that are intentionally promoted to production;
- application-level static assets.

A deployment is not required for routine production data changes, including:

- a new trading session;
- a newly calculated Top-50 ranking;
- daily incremental feature-state updates;
- future ETF market-regime values;
- future portfolio or backtest outputs.

Those changes remain entirely inside Cloudflare and become visible through the Worker API.

## Production research engine

The research engine remains the single source of truth for trading logic. The web layer must never independently recompute SMA, ATR, relative strength, persistence, ranking scores, market regime, or portfolio signals.

The current batch implementation uses Python, Polars, PyArrow, and historical Parquet files. This remains the reference implementation for research and backtesting.

The production path should gradually evolve toward an incremental state model so the daily Cloudflare job does not need to reload and recalculate the full 300+ session history for every symbol.

Target daily update model:

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

Suggested long-term R2 layout:

```text
prices/
  daily/date=YYYY-MM-DD/bars.parquet

state/
  latest/features.parquet
  latest/rolling-state.parquet

rankings/
  date=YYYY-MM-DD/ranking.parquet
  date=YYYY-MM-DD/top50.parquet

dashboard/
  latest.json

metadata/
  latest-market-data.json
  latest-ranking.json

reference/
  tickers/...

regime/
  date=YYYY-MM-DD/regime.json
```

Large Parquet datasets support research and backtests. Compact JSON objects support low-latency API and web delivery.

## ETF market-regime analysis

ETF market data remains part of the retained raw OHLCV history, but ETFs are excluded from the current stock screener and Top-50 ranking.

A later market-regime module will use a selected ETF set to estimate risk capacity and guide the portfolio reservoir rather than generate stock candidates. Candidate inputs include:

- broad-market trend and breadth proxies such as SPY, QQQ, IWM, and DIA;
- cyclical-versus-defensive sector leadership;
- risk-appetite ratios such as IWM/SPY and XLY/XLP;
- credit-risk proxies such as HYG/LQD;
- duration and defensive assets such as TLT and GLD;
- volatility, extension, and trend-state measures derived from ETF OHLCV.

The regime output should determine an **allowed tactical-capital ceiling**, not a required invested percentage. Actual tactical allocation remains the minimum of market risk capacity, available high-quality setups, and portfolio risk limits.

```text
retained ETF OHLCV
        ↓
ETF features / relative ratios / regime signals
        ↓
Market Regime Score
        ↓
allowed tactical-capital ceiling + reservoir cash posture
```

This ETF regime layer is intentionally separate from the common-stock ranking model.

## Dynamic web application

The web application is a read-oriented interactive research interface over precomputed R2 outputs.

Planned capabilities include:

- latest and historical Top-50 rankings without redeploying the site;
- ticker search and symbol detail views;
- sortable and filterable ranking tables;
- 5/10/20-day rank trajectories and persistence;
- breakout, sector, and leader-state filters;
- historical date selection;
- ETF market-regime and capital-level views;
- later portfolio and backtest research interfaces.

## Migration sequence

1. Add a minimal Worker API skeleton with `/api/health`. **Completed.**
2. Add the R2 binding and `/api/rankings/latest`. **Completed in code.**
3. Make the frontend prefer the API over committed static ranking data. **Completed in code.**
4. Stop committing daily dashboard snapshots to `master`. **Completed in the current migration.**
5. Validate Worker production delivery, then remove the legacy static JSON fallback so the dashboard is fully database-driven.
6. Move lightweight daily Massive ingestion from GitHub Actions to a Cloudflare Cron-triggered Worker or Workflow.
7. Store normalized daily bars and update market-data metadata directly in R2 from Cloudflare.
8. Introduce an incremental production feature/ranking state so daily calculation processes only the new session plus required rolling state.
9. Move the production scanner into a Cloudflare Workflow once its resource profile is appropriate for the Worker runtime.
10. Remove the GitHub Actions production ingest/scanner workflow entirely. GitHub Actions remains for CI, tests, linting, and optional deployment automation only.
11. Expand the Worker API to historical rankings, symbol views, ETF regime data, portfolio research, and backtest results.
12. Optionally consolidate static frontend delivery into Workers Static Assets so a single Cloudflare application serves both `/api/*` and the frontend.

## Target steady state

The final steady state is:

```text
GitHub
  = version control + CI

Cloudflare
  = production scheduler + runtime + R2 + API + dynamic web

Daily market update
  = Cloudflare scheduled execution → Massive → R2 → ranking/state update

User request
  = Browser → Worker API → R2
```

Routine daily operation must require no Git commit and no site redeployment. Only promoted code or configuration changes should create a new application deployment.

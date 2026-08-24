# Future Plan

## Formal system architecture

FutureView is a Cloudflare-native, JavaScript-only research platform. GitHub is limited to source control, code review, documentation, JavaScript CI, and deployment. Production scheduling, Massive ingestion, feature computation, ranking, state transitions, persistence, API delivery, and the interactive web application all run on Cloudflare.

Python is not part of the target architecture and is not retained as a production, validation, research, or fallback engine.

```text
GitHub
  ├─ JavaScript / TypeScript source
  ├─ strategy configuration
  ├─ tests and CI
  └─ deployment history
        │
        │ code changes only
        ↓
Cloudflare production platform
  ├─ Scheduled Worker
  │      ↓
  │    Massive
  │      ↓
  │    daily market-data ingest
  │      ↓
  ├─ Workflows
  │    ├─ incremental features
  │    ├─ production ranking
  │    ├─ ranking-state transition
  │    ├─ universe refresh
  │    ├─ regime analysis
  │    └─ backtest / replay jobs
  │
  ├─ D1
  │    ├─ instruments / universe metadata
  │    ├─ ranking and Top50 indexes
  │    ├─ strategy versions
  │    ├─ job / workflow status
  │    ├─ portfolio / watchlist state
  │    └─ backtest metadata
  │
  ├─ R2
  │    ├─ raw and normalized market data
  │    ├─ rolling feature state
  │    ├─ daily feature shards
  │    ├─ ranking snapshots
  │    ├─ large replay / backtest artifacts
  │    └─ presentation snapshots
  │
  ├─ Worker API
  │      ↓
  └─ Dynamic frontend
```

Routine market-data, feature, ranking, regime, portfolio, or backtest-state changes must not create Git commits and must not require frontend redeployment.

## Storage architecture: D1 + R2

FutureView uses D1 and R2 for different workloads rather than forcing all data into one store.

### D1 responsibilities

D1 is the queryable relational control plane. It stores compact structured records that need indexes, filtering, joins, history lookup, or transactional updates.

Planned D1 domains:

```text
instruments
  symbol
  name
  type
  exchange
  active
  common_stock_eligible
  updated_at

universe_snapshots
  date
  symbol
  eligible
  reason

ranking_runs
  date
  candidate_count
  top50_count
  strategy_version
  r2_ranking_key
  r2_top50_key
  status
  created_at

ranking_index
  date
  symbol
  rank
  stock_score
  rank_change_5d
  rank_change_20d

strategy_versions
  version
  configuration_json
  activated_at

workflow_runs
  workflow_type
  trading_date
  instance_id
  status
  started_at
  completed_at
  error

portfolio / watchlist
  compact user-facing research state

backtest_runs
  run_id
  strategy_version
  date_range
  status
  summary metrics
  r2_artifact_prefix
```

D1 should not become the storage location for full historical OHLCV, large feature matrices, or large backtest traces.

### R2 responsibilities

R2 is the bulk analytical data plane. It stores immutable or append-oriented artifacts that are naturally partitioned by date, version, or shard.

```text
prices/
  daily-json/date=YYYY-MM-DD/bars.json

state/
  rolling/v1/date=YYYY-MM-DD/shard=00..31.json
  ranking/v1/date=YYYY-MM-DD/shard=00..31.json

features/
  daily/date=YYYY-MM-DD/shard=00..31.json

rankings/
  date=YYYY-MM-DD/ranking.json
  date=YYYY-MM-DD/top50.json
  date=YYYY-MM-DD/metadata.json

regime/
  date=YYYY-MM-DD/regime.json

backtests/
  run=<id>/...

replay/
  run=<id>/...

dashboard/
  latest.json

metadata/
  latest-cloudflare-ingest.json
  latest-feature-state.json
  latest-incremental-features.json
  latest-ranking-state.json
  latest-ranking.json
  latest-top50.json
```

The long-term API should use D1 to discover and query records, then follow R2 keys when a large artifact is required.

## Current JS production pipeline

Cloudflare owns daily Massive ingestion. The scheduled Worker writes normalized daily JSON to R2:

```text
prices/daily-json/date=YYYY-MM-DD/bars.json
metadata/latest-cloudflare-ingest.json
```

The incremental feature Workflow reads the rolling feature state plus the new daily bars, updates 32 deterministic symbol shards, and writes the new cross-section:

```text
state/rolling/v1/date=YYYY-MM-DD/shard=00..31.json
features/daily/date=YYYY-MM-DD/shard=00..31.json
```

The same Workflow then executes the JavaScript production ranking engine and writes:

```text
rankings/date=YYYY-MM-DD/ranking.json
rankings/date=YYYY-MM-DD/top50.json
rankings/date=YYYY-MM-DD/metadata.json
state/ranking/v1/date=YYYY-MM-DD/shard=00..31.json
state/ranking/v1/date=YYYY-MM-DD/metadata.json
```

Only after all date-scoped feature, ranking, and ranking-state artifacts succeed are the production latest pointers promoted:

```text
metadata/latest-feature-state.json
metadata/latest-incremental-features.json
metadata/latest-ranking-state.json
metadata/latest-ranking.json
metadata/latest-top50.json
dashboard/latest.json
```

A partial run therefore must not publish a half-updated production snapshot.

## Canonical research engine

The JavaScript engine is the single canonical implementation for live execution, replay, validation, and future backtesting.

There is no cross-language parity requirement. Correctness is established through JavaScript tests and strategy invariants, including:

- deterministic hard filters;
- deterministic percentile and ranking behavior;
- explicit tie-breaking rules;
- persistence-state transitions;
- extension-penalty behavior;
- exact state-contract versioning;
- no look-ahead in replay/backtest paths;
- idempotent retries;
- promotion only after complete writes;
- stable Top50 selection for identical inputs.

The same core modules should be reused by production, historical replay, and backtests so there is only one implementation of each strategy rule.

## Incremental state contract

Feature state v1 maintains only the finite rolling windows needed by the current strategy:

- close history for SMA5/10/20/50/200 and return20/60;
- high history for prior 20/50-session breakout levels;
- volume history for average volume and volume ratio;
- true-range history for ATR14;
- SMA50 history for the 10-session slope.

Ranking state v1 maintains:

- recent preliminary Top50 membership for persistence;
- recent final ranks for 5D and 20D rank changes.

Daily execution:

```text
previous feature state
        +
new Massive OHLCV
        ↓
JS incremental features
        ↓
JS cross-sectional ranking
        +
previous ranking state
        ↓
new ranking + Top50 + ranking state
        ↓
D1 index / run metadata update
        ↓
latest-pointer promotion
```

## Universe management

The common-stock universe must also become JavaScript/Cloudflare-owned.

The target universe flow is:

```text
Massive ticker reference data
        ↓
Cloudflare JS universe refresh
        ↓
classification / active / common-stock filters
        ↓
D1 instruments + universe snapshot
        ↓
R2 universe snapshot for reproducibility
        ↓
production ranking
```

D1 becomes the normal query surface for instrument eligibility. R2 retains dated universe snapshots so any historical ranking or backtest can reproduce the exact eligible set for that date.

ETFs remain in retained market data but are excluded from the common-stock Top50 universe.

## ETF market-regime analysis

A later JavaScript market-regime module will use broad-market, sector, credit, duration, and defensive/risk-on ETFs to estimate an allowed tactical-capital ceiling rather than generate stock candidates.

Potential inputs include SPY, QQQ, IWM, DIA, sector ETFs, TLT, HYG, LQD, GLD, QQQ/SPY, IWM/SPY, XLY/XLP, and HYG/LQD.

Actual tactical allocation remains:

```text
min(
  regime_cap,
  setup_opportunity,
  portfolio_risk_limit
)
```

## Dynamic web application

The Worker API should increasingly query D1 for structured discovery and R2 for large result payloads.

Examples:

```text
/api/rankings/latest
  D1 latest ranking run
  → R2 Top50 artifact

/api/rankings?date=YYYY-MM-DD
  D1 ranking index / run lookup
  → R2 ranking snapshot if full payload is requested

/api/symbol/:symbol
  D1 instrument + ranking history
  → R2 feature / price artifacts when needed

/api/backtests/:id
  D1 run metadata / summary
  → R2 detailed output
```

Planned interfaces include latest and historical rankings, ticker detail, rank trajectories, filters, ETF regime views, watchlists, portfolio research, and backtests.

## Deployment boundary

A Cloudflare deployment is required only when code, schema, or strategy configuration changes.

Routine daily execution stays entirely in Cloudflare:

```text
Cron
→ Massive
→ Worker / Workflow
→ D1 + R2
→ Worker API
→ browser
```

No routine daily Git commit or site redeployment is permitted.

## Migration sequence

1. Worker API and R2 binding. **Completed.**
2. Cloudflare Massive daily ingestion. **Completed.**
3. JavaScript incremental feature/state Workflow. **Completed.**
4. JavaScript production ranking and ranking-state publisher. **Implemented; production validation pending.**
5. Remove Python production, validation, tests, and package dependencies. **Completed.**
6. Convert CI to JavaScript-only. **Completed.**
7. Implement JavaScript common-stock universe refresh from Massive. **Next.**
8. Create D1 database, schema, and migrations.
9. Persist instruments and dated universe membership in D1; retain reproducible universe snapshots in R2.
10. Persist ranking-run metadata and compact ranking index in D1 while retaining full ranking artifacts in R2.
11. Make Worker API D1-first for discovery/history and R2-backed for large payloads.
12. Add JavaScript-only replay/regression tests that exercise the same canonical feature/ranking modules.
13. Build JavaScript-only historical backtest execution using the same strategy core.
14. Add ETF regime engine and persist regime metadata in D1 plus detailed snapshots in R2.
15. Add portfolio/watchlist tables and research APIs in D1.
16. Add backtest-run metadata in D1 and detailed result artifacts in R2.
17. Remove legacy static dashboard fallback after dynamic delivery is fully validated.
18. Optionally consolidate frontend delivery into Workers Static Assets / the main Worker deployment.

## Target steady state

```text
GitHub
  = source control + JavaScript CI + deployment

Cloudflare Worker / Workflows
  = all production and research execution

D1
  = relational metadata + indexes + queryable application state

R2
  = market data + feature/state artifacts + ranking snapshots + large analytical outputs

Daily market update
  = Cron → Massive → JS features → JS ranking/state → D1 + R2 → promote latest

Historical research
  = JS replay/backtest → D1 run metadata + R2 artifacts

User request
  = Browser → Worker API → D1 and/or R2
```

FutureView should have one canonical JavaScript strategy engine, one Cloudflare runtime architecture, and no Python dependency.
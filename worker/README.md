# FutureView Cloudflare Runtime

`worker/` is the canonical FutureView execution layer. Production ranking, replay validation, state updates, database indexing, and backtesting are implemented in JavaScript and run on Cloudflare Workers/Workflows.

## Runtime modules

- `index.js` — Worker API, Massive ingest, Cron routing
- `universe.js` — active U.S. common-stock universe refresh
- `feature-bootstrap-workflow.js` — fresh-environment rolling-state bootstrap
- `incremental-workflow.js` — daily feature/state update and production ranking chain
- `ranking-core.js` — canonical cross-sectional ranking engine
- `production-ranking.js` — R2 artifacts, D1 index writes, latest promotion
- `ranking-replay.js` / `ranking-replay-workflow.js` — JS self-replay validation
- `backtest-core.js` / `backtest-workflow.js` — event-driven JS backtest
- `strategy-config.js` — canonical strategy and backtest configuration
- `d1.js` / `d1-read.js` — D1 persistence and API read models

## Storage contract

D1 stores queryable relational indexes and metadata. R2 stores bulk OHLCV, feature/state shards, ranking snapshots, validation output, and backtest artifacts.

Latest pointers are promoted only after their date-scoped production artifacts and required D1 writes succeed.

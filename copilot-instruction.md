# FutureView Development Instructions

FutureView is a Cloudflare-native U.S. equity research platform. The production and research runtime is JavaScript only.

## Architecture

- **Runtime:** Cloudflare Workers and Workflows
- **Language:** modern JavaScript / ES modules
- **Relational database:** Cloudflare D1
- **Bulk object storage:** Cloudflare R2
- **Market data:** Massive
- **Frontend:** Worker-served static assets plus React/Vite development tree
- **CI/deployment:** GitHub Actions

## Canonical-engine rule

There must be one canonical implementation of strategy logic. Live ranking, historical replay, and backtesting must reuse the same JavaScript ranking/configuration modules rather than reimplement formulas in another runtime.

`worker/strategy-config.js` is the strategy configuration source of truth. Strategy changes must be versioned and reflected in D1 strategy metadata.

## Data responsibilities

Use D1 for queryable relational state, indexes, dates, instruments, rank history, strategy versions, and backtest metadata. Use R2 for OHLCV, feature/state shards, complete ranking snapshots, replay artifacts, and large backtest outputs.

Do not store routine market updates in Git or require frontend redeployment for data changes.

## Production safety

- Write date-scoped artifacts before promoting `latest-*` pointers.
- Do not promote partial feature/ranking state.
- Keep Workflow steps retry-safe and idempotent.
- Prevent look-ahead in replay/backtest code; signals formed at a close must not fill at that same close.
- Keep common-stock screening restricted to Massive `type=CS`; retain ETF work for the separate market-regime layer.
- Never hardcode credentials, API keys, account IDs, or D1 database UUIDs.
- D1 schema changes require ordered migrations under `migrations/`.

## Quality checks

- `npm run check:worker`
- `npm test`
- validate all D1 migrations from an empty SQLite database
- lint/build the frontend

Add JavaScript regression tests whenever ranking, state progression, execution timing, persistence, or backtest semantics change.

## Scope

FutureView is a research and decision-support system. Automated brokerage order execution is out of scope unless explicitly redesigned as a separate, reviewed subsystem.

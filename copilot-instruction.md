# FutureView Development Instructions

FutureView is a JavaScript-only U.S. equity research platform. The current operating mode is a **manual testing phase**.

## Architecture

- **Development:** GitHub Codespaces / Linux
- **Language:** modern JavaScript / ES modules
- **Production API/runtime:** Cloudflare Worker + Workflows
- **Relational database:** Cloudflare D1
- **Bulk object storage:** Cloudflare R2
- **Market data:** Massive
- **Frontend:** Worker-served static assets plus React/Vite development tree
- **CI/deployment/recovery:** GitHub Actions
- **Scheduling:** disabled during testing; do not add Cron/scheduled execution unless the project explicitly leaves the manual testing phase

## Canonical-engine rule

There must be one canonical implementation of strategy logic. Live ranking, historical replay, and backtesting must reuse the same JavaScript ranking/configuration modules rather than reimplement formulas elsewhere.

`worker/strategy-config.js` is the strategy configuration source of truth. Strategy changes must be versioned and reflected in D1 strategy metadata.

## Data responsibilities

Use D1 for queryable relational state, indexes, dates, instruments, rank history, strategy versions, and backtest metadata. Use R2 for OHLCV, feature/state shards, complete ranking snapshots, replay artifacts, and large backtest outputs.

Local development must preserve the same D1 schema and R2 object contracts as production. `npm run local:sync` may read production data through restricted credentials, but all sync writes must remain local.

Do not store routine market updates in Git or require frontend redeployment for data changes.

## Production safety

- No Cloudflare Cron or scheduled Worker entrypoint during the testing phase.
- Production data changes are manual and explicit.
- Write date-scoped artifacts before promoting `latest-*` pointers.
- Do not promote partial feature/ranking state.
- Keep Workflow steps retry-safe and idempotent.
- Prevent look-ahead in replay/backtest code; signals formed at a close must not fill at that same close.
- Keep common-stock screening restricted to Massive `type=CS`; ETFs stay outside the stock Top 50.
- Never hardcode credentials, API keys, account IDs, or D1 database UUIDs.
- D1 schema changes require ordered migrations under `migrations/`.
- Do not reintroduce Python runtime, recovery, replay, scanner, or test paths.

## Quality checks

Preferred full setup/validation:

```bash
npm run local:setup
```

Before pushing:

```bash
npm run local:check
```

Add JavaScript regression tests whenever ranking, state progression, execution timing, persistence, or backtest semantics change.

## Scope

FutureView is a research and decision-support system. Automated brokerage order execution is out of scope unless explicitly redesigned as a separate reviewed subsystem.

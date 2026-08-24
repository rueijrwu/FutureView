# FutureView Codespaces

FutureView uses GitHub Codespaces as the primary development and research environment.

## Deployment approval policy

Cloudflare is the final production host/runtime, not the default development runtime.

During development and testing:

- use GitHub Codespaces for implementation, historical research, backtests, API checks, and frontend review
- do not deploy to Cloudflare or invoke production workflows unless the user explicitly approves deployment
- code existing on `master` is not deployment approval
- `npm run local:sync` may read production snapshots through restricted credentials, but development writes stay local

```text
GitHub / Codespaces = develop and test
Cloudflare           = deploy only after explicit user approval
```

Small explicitly approved Cloudflare validation deployments are allowed for adapter/API smoke testing. They should validate contracts only and must not trigger large production workflows.

## Local-first architecture

Research data is local-filesystem first:

```text
.local-data/
  objects/
    prices/daily-json/
    metadata/
    backtests/
    ...
  d1/

.local-backtest/
  sessions/
  checkpoint.json
```

The canonical historical market-data contract used by local research is:

```text
.local-data/objects/prices/daily-json/date=YYYY-MM-DD/bars.json
```

Legacy mirrored R2 parquet history under `prices/daily/` is an archive/source. The historical recovery utility materializes it into the canonical JSON contract once. Daily Cloudflare ingestion already writes the same `prices/daily-json/.../bars.json` contract, so historical bootstrap and daily updates converge on one format.

The strategy/research core does not depend on R2 or D1 directly. Storage adapters expose the same logical contracts, keeping feature, ranking, backtest, and audit logic portable.

## Persistent local data

The workspace keeps ignored local directories:

```text
.local-data/       canonical local research data plus read-only R2/D1 mirror
.local-backtest/   derived feature/ranking sessions and checkpoint
.local-sync/       production mirror manifest
.local-state/      Wrangler state for optional Cloudflare adapter tests
```

Historical data already downloaded or computed should be reused. Normal daily work appends only new completed sessions.

## Setup and validation

For a new/rebuilt Codespace:

```bash
npm run local:setup
npm run local:history:setup
```

Before pushing changes:

```bash
npm run local:check
```

## Read-only production mirror

```bash
npm run local:sync
```

This incrementally mirrors all production R2 objects and a read-only D1 application-table snapshot into `.local-data/`. It performs no production writes.

Use a full mirror rebuild only when deliberately recovering local storage:

```bash
npm run local:sync:full
```

## One-time historical bootstrap / disaster recovery

Historical acquisition is intentionally separate from backtesting.

```bash
npm run local:history
```

Default target is 337 completed sessions (211 warm-up + 126 backtest sessions) through the latest completed feature session.

The recovery tool is resumable and follows this order:

```text
existing canonical daily-json
→ materialize mirrored R2 parquet history
→ only if still short, fetch missing older sessions from Massive
```

Massive recovery uses grouped daily data, 13-second pacing, 429/5xx retry/backoff, and writes every successful session immediately. If the process is interrupted, rerunning resumes from already persisted history.

Useful variants:

```bash
npm run local:history -- --sessions=400
npm run local:history -- --end=2026-08-21
npm run local:history -- --mode=materialize
```

`--mode=materialize` never calls Massive; it only converts already mirrored parquet sessions into the canonical daily-json contract.

## Daily update after historical bootstrap

Once history is complete, normal local updates are:

```bash
npm run local:update
```

This performs:

```text
production R2/D1 read-only incremental mirror
→ materialize any newly mirrored daily data into canonical local history
```

The normal daily path does not run a historical recovery loop. Production daily ingestion is expected to add only the newest completed session, so Massive rate limits are not a normal research concern.

## Historical local backtest

```bash
npm run local:backtest
```

`local:backtest` is now a pure consumer of canonical local daily history. It does not call Massive.

The first run uses 211 local warm-up sessions, builds canonical JS features/rankings, caches derived sessions under `.local-backtest/`, runs the requested backtest window, and writes the result under `.local-data/objects/backtests/` plus `metadata/latest-backtest.json`.

Later runs reuse the checkpoint and process only newly available local sessions.

Use a clean derived-state rebuild only when strategy/universe consistency requires it:

```bash
npm run local:backtest -- --rebuild
```

The historical replay currently applies the synced common-stock universe across the historical window, so interpret results with survivorship-bias caution until point-in-time universes are added.

## Local API

Daily local development uses the Node filesystem API:

```bash
npm run local:dev
```

It listens on port `8787` and serves the same API paths used by the Cloudflare Worker.

## Frontend

Run Vite in another terminal:

```bash
npm run dev --prefix view -- --host 0.0.0.0
```

Vite listens on `5173` and proxies `/api/*` to `127.0.0.1:8787`.

## Cloudflare adapter/API smoke tests

Wrangler local adapter testing remains available:

```bash
npm run local:cloudflare
```

After an explicitly approved Cloudflare validation deployment, run the deployed read-only API smoke test:

```bash
npm run cloudflare:smoke -- --base-url=https://<deployment-host>
```

or:

```bash
FUTUREVIEW_API_BASE_URL=https://<deployment-host> npm run cloudflare:smoke
```

The deployed smoke test verifies:

```text
/api/health             → Cloudflare Worker runtime, R2 binding, D1 binding
/api/universe/status    → R2-backed API read contract
/api/rankings/history   → D1-backed API read contract
```

It performs no production writes and invokes no workflows. This is the default post-deploy adapter/API validation before considering any larger production execution.

## Data contract

Local and Cloudflare paths must preserve:

- the same strategy core JavaScript
- the same object keys and JSON payload contracts
- the same ranking/backtest semantics
- D1 schema compatibility where D1 is used

Storage backend changes must not create a second strategy implementation.

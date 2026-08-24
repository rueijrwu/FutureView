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

## Local-first architecture

Research data is local-filesystem first:

```text
.local-data/
  objects/
    metadata/
    backtests/
    ...

.local-backtest/
  bars/
  sessions/
  checkpoint.json
```

The strategy/research core does not depend on R2 or D1 directly. Storage adapters expose the same JSON contract:

```text
getJson(key)
putJson(key, value)
exists(key)
```

Current adapters:

- `tools/local/fs-store.mjs` — Codespaces filesystem adapter
- `worker/json-store.js` — Cloudflare R2 adapter

This keeps feature, ranking, backtest, and audit logic portable. Cloudflare can be smoke-tested later with the same object keys and JSON contracts without making Cloudflare the daily research runtime.

## Persistent local caches

The workspace keeps several ignored local directories:

```text
.local-data/       canonical local research objects
.local-backtest/   immutable bars, per-session artifacts, checkpoint
.local-sync/       read-only production snapshot cache / manifest
.local-state/      Wrangler D1/R2 state for optional Cloudflare adapter tests
```

Reconnects to the same Codespace reuse these directories as long as the workspace still exists.

Historical data already downloaded or computed should be reused. Normal work should append only new sessions.

## Setup and validation

Use full setup only for a new/rebuilt Codespace, dependency/config changes, or local environment repair:

```bash
npm run local:setup
```

Before pushing changes:

```bash
npm run local:check
```

## Read-only snapshot sync

```bash
npm run local:sync
```

This remains the bridge for production-shaped reference data such as the common-stock universe and latest metadata. It is incremental and does not constitute deployment approval.

Use a full sync only when the local sync state is deliberately being rebuilt:

```bash
npm run local:sync:full
```

## Historical local backtest

```bash
npm run local:backtest
```

The first run bootstraps the required historical bars, builds canonical JS features/rankings, caches every completed session, runs the backtest, and writes the latest result to `.local-data/objects/metadata/latest-backtest.json` plus its referenced result object.

Later runs reuse `.local-backtest/` and append only sessions newer than the checkpoint.

Use a deliberate clean rebuild only when strategy/universe consistency requires it:

```bash
npm run local:backtest -- --rebuild
```

The historical bootstrap currently applies the synced common-stock universe across the replay window, so results must be interpreted with survivorship-bias caution until point-in-time universes are added.

## Local API

Daily local development uses the Node filesystem API, not Wrangler:

```bash
npm run local:dev
```

It listens on port `8787` and serves the same API paths used by the Cloudflare Worker, including:

```bash
curl http://localhost:8787/api/health
curl http://localhost:8787/api/universe/status
curl http://localhost:8787/api/rankings/latest
curl http://localhost:8787/api/backtests/latest
curl http://localhost:8787/api/backtests/audit
```

Expected health identity for daily local development:

```json
{
  "storage": "filesystem",
  "runtime": "node-local-js"
}
```

## Frontend

Run Vite in another terminal:

```bash
npm run dev --prefix view -- --host 0.0.0.0
```

Vite listens on `5173` and proxies `/api/*` to `127.0.0.1:8787`.

Backtest page:

```text
http://localhost:5173/backtest
```

## Optional Cloudflare adapter smoke test

Wrangler is retained only for small integration/contract checks:

```bash
npm run local:cloudflare
```

This uses `.local-state/` and the actual Worker/R2/D1 bindings locally. It is not the default research path.

A future explicitly approved Cloudflare deployment should validate a small fixture through the same API/storage contracts before any larger production workflow is enabled.

## Data contract

Local and Cloudflare paths must preserve:

- the same strategy core JavaScript
- the same object keys and JSON payload contracts
- the same ranking/backtest semantics
- D1 schema compatibility where D1 is used

Storage backend changes must not create a second strategy implementation.

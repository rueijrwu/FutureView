# FutureView Codespaces

FutureView uses GitHub Codespaces as the preferred cloud development environment.

## Start

1. Open the repository on GitHub.
2. Select **Code → Codespaces → Create codespace on master** (or create one from a feature branch).
3. Wait for the dev container to finish creating. `npm run local:setup` runs automatically via `postCreateCommand`.

## Develop

Start the local Cloudflare-compatible Worker runtime:

```bash
npm run local:dev
```

Wrangler listens on port `8787`; Codespaces will offer the forwarded URL automatically.

For frontend-only development:

```bash
npm run dev --prefix view -- --host 0.0.0.0
```

Vite listens on port `5173` and Codespaces will offer its forwarded URL.

## Sync a production snapshot into local development

If the local D1/R2 state is empty, copy a read-only production snapshot into local Wrangler storage:

```bash
npm run local:sync
```

Required Codespaces environment variables/secrets:

```text
CLOUDFLARE_API_TOKEN
R2_ACCOUNT_ID
```

The token should have production **D1 Read** and **R2 Read** access only. `local:sync` never performs a remote write. All writes use Wrangler `--local` storage.

The sync copies the latest production R2 pointers and referenced objects needed for development, including the common-stock universe, canonical feature state, latest ranking/dashboard data when available, ranking state, ingest metadata, replay metadata, and latest backtest result when available.

For D1 it copies a compact development history: the most recent 20 ranking runs, Top50 ranking entries for those runs, and their corresponding universe snapshots. Before importing this D1 snapshot, it clears the **local-only** `ranking_entries`, `ranking_runs`, and `universe_snapshots` tables so repeated syncs form a clean production baseline. Production D1 is never modified.

Recommended workflow:

```bash
npm run local:setup
npm run local:sync
npm run local:dev
```

After starting the Worker, verify:

```bash
curl http://localhost:8787/api/health
curl http://localhost:8787/api/universe/status
curl http://localhost:8787/api/state/status
curl http://localhost:8787/api/rankings/latest
```

## Validation

Before pushing a branch:

```bash
npm run local:check
```

This runs Worker/recovery/local script syntax checks, JS tests, frontend lint, and frontend build.

## Secrets

The local setup creates `.dev.vars` if it does not exist. Do not commit it. Add local-only secrets there when needed, for example:

```text
MASSIVE_API_KEY=...
```

For Codespaces, prefer repository/org Codespaces secrets when access to real external services is required; do not hard-code secrets in the repository.

## Data contract

Local development must keep the same production contracts used by Cloudflare:

- D1 schema comes from `migrations/`.
- R2 object keys and JSON contracts match production.
- Ranking/feature/backtest core logic remains shared JavaScript.

Production deployment remains separate from Codespaces development.

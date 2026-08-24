# FutureView Codespaces

FutureView uses GitHub Codespaces as the preferred development environment during the manual testing phase.

## Deployment approval policy

Cloudflare is the **final production host/runtime**, not the default development or testing environment.

During development and testing:

- use GitHub and GitHub Codespaces for implementation, testing, validation, and frontend review
- use local Wrangler D1/R2 state and the local Worker for runtime checks
- do **not** deploy to Cloudflare, invoke Cloudflare production workflows, or use Cloudflare production runtime for feature validation unless the user explicitly confirms that deployment should happen
- code existing on `master` does not imply that it should be deployed
- a Cloudflare deployment is a separate, explicit step that requires user confirmation

The only normal pre-deployment Cloudflare access is the existing **read-only production snapshot sync** used by `npm run local:sync`. That command may read production D1/R2 data through the restricted token, but all development writes and tests remain local.

In short:

```text
GitHub / Codespaces = develop and test
Cloudflare           = deploy only after explicit user approval
```

## Start

1. Open the repository on GitHub.
2. Select **Code → Codespaces → Create codespace on master** (or use a feature branch).
3. Wait for the dev container to finish. `npm run local:setup` runs automatically through `postCreateCommand`.

## Required Codespaces secrets

Use repository/org Codespaces secrets rather than committing credentials:

- `MASSIVE_API_KEY`
- `CLOUDFLARE_API_TOKEN` — restricted development/read-only token
- `R2_ACCOUNT_ID`

Do not place production secrets in tracked files.

## Local validation

Run the complete setup/validation path when needed:

```bash
npm run local:setup
```

This:

- validates Node/npm
- creates local Wrangler configuration
- installs frontend dependencies
- applies local D1 migrations
- runs Worker/recovery/local script syntax checks
- runs JS regression tests
- runs frontend lint/build

Before pushing changes:

```bash
npm run local:check
```

## Sync a production snapshot

To develop against current production-shaped data without writing production:

```bash
npm run local:sync
```

The sync command reads production R2/D1 through the restricted Cloudflare token and writes only to local Wrangler state. It replaces the local ranking snapshot tables with the selected production snapshot so local API responses are reproducible.

Production writes are intentionally not part of Codespaces development.

Read-only snapshot sync does **not** constitute deployment approval and must not be treated as permission to run or modify Cloudflare production runtime.

## Run the local Worker

```bash
npm run local:dev
```

Wrangler listens on port `8787`; Codespaces forwards the port automatically.

Useful checks:

```bash
curl http://localhost:8787/api/health
curl http://localhost:8787/api/universe/status
curl http://localhost:8787/api/state/status
curl http://localhost:8787/api/rankings/latest
```

For frontend-only development:

```bash
npm run dev --prefix view -- --host 0.0.0.0
```

Vite listens on port `5173`.

## Manual testing phase

Cloudflare Cron and the Worker `scheduled()` entrypoint are disabled. Do not use `/cdn-cgi/local/scheduled` or add scheduled triggers during this phase.

Production updates are explicit/manual until the pipeline is validated and the project deliberately enables automation again.

No Cloudflare deployment or production-runtime validation should be performed merely because a feature is ready locally. Wait for explicit user confirmation to deploy.

## Data contract

Local development must keep the same contracts as production:

- D1 schema comes from `migrations/`.
- R2 object keys and JSON formats match production.
- Ranking/feature/replay/backtest logic remains shared JavaScript.

Local convenience code must not create a second strategy implementation.

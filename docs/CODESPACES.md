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

## Validation

Before pushing a branch:

```bash
npm run local:check
```

This runs Worker/recovery script syntax checks, JS tests, frontend lint, and frontend build.

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

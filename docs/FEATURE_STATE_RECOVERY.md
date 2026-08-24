# Feature-state recovery

FutureView keeps recovery outside the normal Worker runtime. Both recovery modes are manual GitHub Actions and only promote `metadata/latest-feature-state.json` after all 32 shards have been prepared successfully.

## 1. Recover Feature State (Repair)

Use this when a complete rolling state already exists in R2 and only needs validation/re-promotion.

GitHub Actions workflow: **Recover Feature State (Repair)**

Inputs:
- `source_date`: state date in `YYYY-MM-DD`.
- `source_prefix`: optional R2 prefix containing `shard=00.json` through `shard=31.json`. Leave blank for `state/rolling/v1/date=<source_date>`.
- `confirm`: must be exactly `PROMOTE`.

The workflow downloads all 32 shards, validates the rolling windows and SPY, rewrites canonical date-scoped shards, and promotes the latest pointer last.

Result metadata uses:
- `producer = cloudflare-js-bootstrap`
- `seed_source = github-actions-state-repair`

## 2. Recover Feature State (Full Rebuild)

Use this when no trustworthy rolling state exists.

GitHub Actions workflow: **Recover Feature State (Full Rebuild)**

Inputs:
- `target_date`: trading date to rebuild through in `YYYY-MM-DD`.
- `confirm`: must be exactly `REBUILD`.

Required GitHub secrets:
- `CLOUDFLARE_API_TOKEN`
- `R2_ACCOUNT_ID`
- `MASSIVE_API_KEY`

The workflow downloads the latest common-stock universe from R2, requests 211 valid grouped-daily sessions from Massive ending on `target_date`, rebuilds the rolling state with Node.js, writes 32 date-scoped shards, validates SPY, and promotes the latest pointer last.

Result metadata uses:
- `producer = cloudflare-js-bootstrap`
- `seed_source = github-actions-full-rebuild`

## Safety rules

- Neither recovery workflow triggers ranking or incremental processing directly.
- Both workflows share one recovery concurrency group so they cannot run simultaneously.
- The latest feature-state pointer is written only after shard creation succeeds.
- Do not use the retired Cloudflare historical bootstrap workflow; it exceeded Worker invocation limits in production.
- During the testing phase, any follow-up ingest/incremental processing is started manually after recovery validation.

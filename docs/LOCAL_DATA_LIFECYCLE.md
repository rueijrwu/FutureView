# FutureView Local Data Lifecycle

This document is the canonical script map for local data, historical recovery, backtesting, and Cloudflare adapter checks.

## Daily local development

```bash
npm run local:update
npm run local:backtest
npm run local:dev
```

`local:update` performs the normal incremental path:

1. read-only mirror from production R2/D1 into `.local-data/`
2. materialize any newly mirrored daily market data into the canonical local JSON contract
3. do not fetch historical gaps from Massive

`local:backtest` reads only local canonical daily history. It never calls Massive.

## One-time / disaster historical recovery

Use only when local/R2 history is missing or when rebuilding a research workspace:

```bash
npm run recovery:history
```

The recovery command:

1. reuses existing mirrored `prices/daily` Parquet first
2. materializes it into `prices/daily-json/date=YYYY-MM-DD/bars.json`
3. fetches only missing historical sessions from Massive
4. respects the Basic-plan request pacing and retry/backoff behavior
5. writes each recovered session immediately so the process is resumable

Historical recovery is not part of the daily path.

## Publish recovered history to Cloudflare

Optional production adapter validation / recovery publication:

```bash
npm run recovery:history:publish:smoke
npm run recovery:history:publish
```

The smoke command publishes one recovered session and verifies R2 + D1 read-back. The full command publishes the complete recovery-only set. These commands write production data and therefore require explicit approval before use.

## Read-only production mirror

```bash
npm run local:sync
npm run local:data:report
```

`local:sync` mirrors production R2 and D1 read-only into `.local-data/`.

`local:data:report` reports local object/session counts, date ranges, and sizes.

Use `local:sync:full` only to deliberately rebuild the entire local mirror.

## Validation and adapter smoke tests

```bash
npm run local:check
npm run cloudflare:smoke -- --base-url=https://...
```

`cloudflare:smoke` is read-only and verifies deployed Worker/R2/D1 API contracts.

`local:cloudflare` remains available only for optional Wrangler-local adapter testing; it is not part of daily development.

## Retained recovery tools

The following files are intentionally retained because they are used by recovery workflows or future disaster recovery:

- `tools/recovery/full-rebuild.mjs`
- `tools/recovery/state-repair.mjs`
- `tools/recovery/publish-history.mjs`

## Removed / deprecated paths

Do not reintroduce:

- Python `history.py`
- Python `requirements.txt`
- `local:history:setup`
- backtests that call Massive directly
- Wrangler local R2/D1 as the normal research data path

Canonical local market-data contract:

```text
.local-data/objects/prices/daily-json/date=YYYY-MM-DD/bars.json
```

Canonical separation:

```text
daily:    local:update -> local:backtest
recovery: recovery:history -> optional recovery:history:publish
```

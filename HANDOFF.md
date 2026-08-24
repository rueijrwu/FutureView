# FutureView Handoff

This file is the concise handoff for continuing FutureView in a new chat. Treat it as the current source of project context unless the repository code or newer runtime logs prove otherwise.

# 1. Trading Strategy

## Objective

FutureView is a point-in-time U.S. equity research platform for systematic screening, ranking, portfolio research, and backtesting. The intended holding horizon is roughly **3 weeks to 3 months**. It is a research and decision-support system; automated brokerage order execution is out of scope.

## Universe

Rank **active U.S. common stocks only** from Massive ticker reference metadata (`type=CS`). ETFs remain available in raw historical data but do not enter the stock Top 50. SPY remains available as the benchmark for relative-strength calculations.

Core universe filters:

- price > $10
- 20-session average dollar volume > approximately $50M
- close > SMA50 > SMA200
- SMA50 slope > 0
- usually close > SMA20
- RS20 > SPY
- RS60/63 > SPY
- near or breaking the 20- to 50-session high
- extension `(close - SMA20) / ATR14 < 3`

## Ranking model

Canonical strategy version: `momentum-v2`.

Configuration source of truth: `worker/strategy-config.js`.

Score v2:

```text
Score =
  0.25 * RS20
+ 0.20 * RS60
+ 0.20 * Trend
+ 0.15 * Breakout
+ 0.10 * Volume
+ 0.10 * Persistence
- ExtensionPenalty
```

Extension penalty:

```text
scaled = clip((ExtensionATR - 1.5) / 1.5, 0, 1)
ExtensionPenalty = 0.12 * scaled^2
```

The 3-ATR ceiling remains a hard eligibility cap.

Important ranking behavior:

- ranking is deterministic
- numeric ranking keys are quantized to 12 decimals
- exact score ties use symbol-ascending order
- missing numeric inputs are rejected, not coerced to zero
- PersistenceScore uses the most recent 20 market sessions
- missing historical ranks display as `NEW`, not `0`

## Top 50 interpretation

- ranks 1-10: active trade/call candidates
- ranks 11-25: emerging leaders
- ranks 26-50: breadth, sector rotation, and rank-trajectory context

Track historical ranks for current, prior session, 5D, 10D, and 20D where available.

Useful qualitative labels:

- `Leader Stable`
- `Rising`

## Portfolio / capital framework

Capital is conceptually divided into:

1. emergency reserve: 10-30% NAV, with a 10% floor
2. core/reservoir capital
3. tactical momentum capital, normally up to about two-thirds of investable capital

Longer-term allocation should eventually use:

```text
allocation = min(regime_cap, setup_opportunity, portfolio_risk_limit)
```

Planned market-regime inputs include SPY, QQQ, IWM, DIA, sector ETFs, TLT, HYG, LQD, GLD, QQQ/SPY, IWM/SPY, XLY/XLP, and HYG/LQD. ETF regime research is not yet the stock-ranking engine.

## Backtest baseline

Canonical config is in `worker/strategy-config.js` under `BACKTEST_CONFIG_V1`.

Current baseline assumptions:

- initial capital: $100,000
- maximum positions: 10
- entry rank <= 10
- breakout20 required
- equal-notional allocation
- minimum hold: 15 sessions
- maximum hold: 60 sessions
- exit below SMA10 after minimum hold
- signals formed at a close execute at the **next session open**
- remaining open positions are liquidated at the final known close
- no transaction costs or slippage yet

The next-open rule is critical and prevents same-session look-ahead.

## Strategy principles that should not be changed casually

- one canonical implementation of ranking logic must be reused by live ranking, replay, and backtest
- JavaScript only; do not reintroduce Python as a comparator, fallback, scanner, replay engine, or backtest implementation
- keep the stock Top 50 separate from ETF regime analysis
- maintain point-in-time semantics and avoid look-ahead
- production success must be proven by logs; do not infer it from code existing on `master`

# 2. Code / System

## Repository and runtime

Repository: `rueijrwu/FutureView`

Default branch: `master`

Canonical language/runtime: **JavaScript / Node only**.

Current architecture:

```text
GitHub Codespaces
  -> local setup / local D1 / local R2 / local Worker
  -> local validation
  -> GitHub commit / CI
  -> Cloudflare deploy when desired

Cloudflare production
  -> Worker API
  -> D1 relational/query layer
  -> R2 object/artifact layer
  -> Cloudflare Workflows available for manual execution
```

Testing-phase policy as of 2026-08-24:

- **no Cloudflare Cron scheduling**
- **no scheduled Worker handler**
- all data refresh / processing is manual during testing
- do not add Cron back unless explicitly decided later

The previous weekday and Sunday schedules were intentionally removed because the current testing phase uses manual updates and Cloudflare Free scheduling is not being relied on.

## Codespaces development

Preferred development environment: GitHub Codespaces.

The repository contains `.devcontainer/devcontainer.json` with Node 24 and forwarded ports 8787 and 5173.

Typical flow:

```bash
git pull
npm run local:setup
npm run local:sync
npm run local:dev
```

Validation:

```bash
npm run local:check
```

`local:setup` currently:

- checks Node >= 22 (Node 24 recommended)
- preserves/creates `.dev.vars`
- regenerates `.wrangler.local.json` from `wrangler.jsonc`
- installs frontend dependencies
- applies local D1 migrations
- runs syntax/tests/frontend lint/build

Important: after `wrangler.jsonc` changes, rerun `npm run local:setup` so `.wrangler.local.json` is regenerated. This was required after removing Cron triggers.

Validated Codespaces result on 2026-08-24:

- Node 24.18.0
- npm 11.16.0
- D1 migrations applied
- Worker syntax checks passed
- JS tests: 6/6 passed
- frontend ESLint passed
- frontend production build passed
- `npm run local:setup` ended with `[local:setup] READY`
- `npm run local:dev` successfully started local Worker
- local health endpoint returned:

```json
{"service":"futureview-api","status":"ok","database":"d1-bound","storage":"r2","runtime":"cloudflare-js"}
```

Frontend dependency audit currently reports 17 vulnerabilities (2 low, 2 moderate, 12 high, 1 critical). Do not run `npm audit fix --force` casually; audit separately to avoid unnecessary dependency regressions.

## Local production snapshot sync

Command:

```bash
npm run local:sync
```

Purpose: copy a **read-only production snapshot** into local Wrangler D1/R2 so development can use real data without writing production.

Design rule:

```text
production D1/R2 = read only
local D1/R2      = writable
```

The script is `tools/local/sync.mjs`.

It syncs the production pointers/artifacts needed for local work, including the current universe, canonical feature state and shards, ranking/dashboard artifacts, and a recent D1 ranking snapshot/history set.

It may reset the corresponding local ranking snapshot tables to produce a clean local baseline. It must not perform production `put`, `update`, or `delete` operations.

Required Codespaces environment variables include:

- `CLOUDFLARE_API_TOKEN`
- `R2_ACCOUNT_ID`
- `MASSIVE_API_KEY` when Massive access is needed

Do not paste secrets into chat or commit them. `.dev.vars`, `.wrangler/`, `.wrangler.local.json`, and `.local-sync/` are ignored.

## Cloudflare production storage

D1 migrations:

- `migrations/0001_initial.sql`
- `migrations/0002_strategy_version.sql`

D1 tables:

- `instruments`
- `universe_snapshots`
- `universe_membership`
- `ranking_runs`
- `ranking_entries`
- `workflow_runs`
- `strategy_versions`
- `backtest_runs`

D1 is for queryable relational/index data.

R2 is for large reproducible artifacts such as:

```text
prices/daily-json/date=YYYY-MM-DD/bars.json
reference/tickers/date=YYYY-MM-DD/common-stocks.json
state/rolling/v1/date=YYYY-MM-DD/shard=00..31.json
features/daily/date=YYYY-MM-DD/shard=00..31.json
rankings/date=YYYY-MM-DD/ranking.json
rankings/date=YYYY-MM-DD/top50.json
state/ranking/v1/date=YYYY-MM-DD/shard=00..31.json
validation/js-replay/date=YYYY-MM-DD/...
backtests/run=<id>/result.json
dashboard/latest.json
metadata/latest-*.json
```

Current production Worker URL:

```text
https://futureview.rueijrwu.workers.dev
```

Previously validated production health:

```text
service  = futureview-api
status   = ok
database = d1-bound
storage  = r2
runtime  = cloudflare-js
```

## Canonical production data already validated

Common-stock universe was manually refreshed and production-validated:

```text
as_of    = 2026-08-23
count    = 5322
source   = massive
producer = cloudflare-js
```

Canonical feature-state seed was successfully established by legacy-state adoption before the adoption workflow was retired:

```text
version        = 1
as_of          = 2026-08-21
shard_count    = 32
symbol_count   = 10848
prefix         = state/rolling/v1/date=2026-08-21
producer       = cloudflare-js-bootstrap
seed_source    = legacy-state-adoption
benchmark      = SPY
```

Historical migration parity evidence also passed for 2026-08-20:

```text
cloudflare_count      = 10396
compared_symbol_count = 10396
missing_symbol_count  = 0
unexpected_symbol_count = 0
mismatch_count        = 0
max_abs_error         = 7.62939453125e-06
coverage_status       = pass
parity_status         = pass
status                = pass
```

This is migration evidence only, not a Python runtime dependency.

## Cloudflare Workflows still in the runtime

The intended workflow bindings are:

- `futureview-incremental-features`
- `futureview-ranking-replay`
- `futureview-backtest`

These remain available but are **not scheduled during testing**.

`worker/incremental-workflow.js` performs rolling feature updates and then production ranking. `worker/ranking-replay-workflow.js` validates replay using the canonical JS ranking engine. `worker/backtest-workflow.js` runs the JS backtest.

The retired Cloudflare historical bootstrap/adoption runtime was removed. Do not restore it.

Retired/deleted runtime concepts:

- `FeatureBootstrapWorkflow`
- `StateAdoptionWorkflow`
- `/api/admin/bootstrap-features`
- `/api/admin/adopt-feature-state`
- Cron-based weekday processing
- Cron-based Sunday backtest

## Recovery paths

Recovery is intentionally separate from normal runtime and lives in manual GitHub Actions.

### State Repair

Tool:

```text
tools/recovery/state-repair.mjs
```

Workflow:

```text
.github/workflows/recover-state-repair.yml
```

Use when an existing complete rolling state needs validation/re-promotion.

### Full Rebuild

Tool:

```text
tools/recovery/full-rebuild.mjs
```

Workflow:

```text
.github/workflows/recover-full-rebuild.yml
```

Uses Massive historical grouped-daily sessions and rebuilds 32 deterministic shards.

Required GitHub secrets are already known to exist:

- `CLOUDFLARE_API_TOKEN`
- `R2_ACCOUNT_ID`
- `MASSIVE_API_KEY`

Do not ask again whether `MASSIVE_API_KEY` exists in GitHub/Cloudflare unless an actual tool/runtime error proves otherwise.

Recovery runbook: `docs/FEATURE_STATE_RECOVERY.md`.

## API routes

Current read routes include:

```text
/api/health
/api/rankings/latest
/api/rankings/history
/api/rankings/date/YYYY-MM-DD
/api/symbols/:symbol/rankings
/api/ingest/status
/api/universe/status
/api/state/status
/api/ranking-state/status
/api/replay/status
/api/backtests/latest
```

Current manual admin route retained:

```text
POST /api/admin/refresh-universe
```

It uses bearer `ADMIN_TOKEN`.

Important gap for the next chat: after Cron removal, a complete manual command/endpoint for the whole daily path

```text
ingest -> incremental features -> ranking -> replay
```

has **not yet been added**. This was deliberately deferred. When work resumes, this is likely the next useful runtime task. Prefer a clear manual admin action or explicit local command rather than reintroducing Cron.

## Frontend

- `site/` is the Worker-served deployed static asset tree and still contains the current static fallback/dashboard assets.
- `view/` is the React/Vite development frontend.
- do not remove the static fallback until dynamic API-backed frontend delivery has been validated stable.

## Repository docs after cleanup

Documentation was consolidated on 2026-08-24.

Root `README.md` now contains the stable architecture, strategy, universe, score, backtest, local-development, and testing-phase policy.

Independent runbooks retained:

- `docs/CODESPACES.md`
- `docs/FEATURE_STATE_RECOVERY.md`
- `docs/README.md` as a small index

Deleted as redundant/stale after consolidation:

- `docs/future-plan.md`
- `docs/scoring-v2.md`
- `docs/screener-universe.md`

The deploy workflow also had its obsolete repeated deletion of already-retired Cloudflare workflows removed.

## Recent important commits

Useful recent commits from this development session:

```text
e75a1f1fa43e55b321a9dca5637de8c6ddac3665  fix backtest test field name
3b82ad604543ff8a42d4c505a5f9688bebf5ab4f  local sync/docs state before cleanup
951db7c508fe059b16708f46ddf27c3ae2d837f4  documentation/dead-code cleanup series endpoint
```

There were several cleanup commits between `3b82ad...` and `951db7...`; inspect Git history if exact per-file provenance matters.

## Validation scoreboard

Confirmed/validated:

- Codespaces local setup and Worker startup
- local D1 migrations
- 6/6 current JS tests
- frontend lint/build
- local Worker health
- production Worker health (previously validated)
- JS common-stock universe production publication
- canonical 2026-08-21 rolling feature-state seed
- historical migration parity evidence

Still requires runtime evidence before claiming success:

- first complete manual daily ingest -> incremental -> ranking -> replay after the new manual-only testing policy
- D1 ranking writes/current strategy on that new run
- latest ranking pointer produced by that new run
- replay result for that new run
- manual backtest execution after schedule removal
- runtime success of the newer recovery workflows if no explicit successful run log has been supplied

## Potential technical issues to keep in mind

- incremental workflow may encounter Cloudflare subrequest limits when writing many R2 objects in a single step
- rolling-state membership drift / new IPO admission still needs a long-term policy
- instruments absent from the newest universe may remain `active=1`; dated universe membership remains the authoritative point-in-time set
- D1 universe membership grows by roughly one row per symbol per dated universe snapshot
- backtest still has no transaction-cost/slippage model
- static dashboard fallback remains intentionally
- ETF/regime layer is future work

## Next-chat operating rules

When continuing this project:

- prefer direct repository inspection before assuming code state
- use GitHub connector for repository reads/writes
- do not reintroduce Python
- do not reintroduce Cloudflare Cron during the testing phase
- do not claim CI/deploy/runtime success without logs or tool evidence
- when user says to execute a clear repository change, do it rather than repeatedly asking for confirmation
- keep production writes separated from local development; local sync should read production and write local only
- preserve one canonical JavaScript strategy engine across production ranking, replay, and backtest

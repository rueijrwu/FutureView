# FutureView Handoff

This is the current handoff for continuing FutureView. Prefer repository code and newer runtime logs if they conflict with this file.

Last updated: 2026-08-24.

## 1. Project Direction

FutureView is a U.S. equity research and backtesting system for a **right-side trend-following swing strategy** with an intended holding horizon of roughly **15-60 trading sessions / 3 weeks-3 months**.

Current priority is **research-core implementation and empirical validation**. Frontend visualization is intentionally deferred until the strategy and audit layers are mature.

Production brokerage execution is out of scope.

## 2. Hard Operating Rules

Development/testing:

```text
GitHub + Codespaces = primary development environment
.local-data          = canonical local research store
Cloudflare R2/D1     = production archive/adapters
Massive              = ingestion/recovery source
```

Production policy:

- merging to `master` is not deployment approval
- do not deploy or invoke broad production workflows without explicit approval
- production success must be proven by runtime/log evidence
- normal Cloudflare credentials should remain read-only
- temporary R2/D1 write permission may be enabled only for explicit maintenance/smoke work, then returned to read-only

No Cron/scheduled production processing is currently relied on during testing.

## 3. Canonical Local Data Architecture

Canonical market history:

```text
.local-data/objects/prices/daily-json/date=YYYY-MM-DD/bars.json
```

Historical bootstrap/recovery and daily operation are separate.

### One-time / disaster recovery

```text
npm run recovery:history
```

Behavior:

- materializes mirrored R2 Parquet into canonical daily JSON
- uses Massive only when local/R2 history is insufficient
- Massive requests are paced at ~13 seconds
- retries 429/5xx with backoff
- recovered sessions are written immediately

Cloudflare recovery publishing:

```text
npm run recovery:history:publish:smoke
npm run recovery:history:publish
```

The smoke path was runtime-validated end-to-end:

```text
local recovery JSON
-> R2 write
-> R2 read-back/checksum
-> D1 market_data_sessions write
-> D1 read-back
```

Result: **passed for 1 recovery session**.

### Normal daily local path

```text
npm run local:update
```

This mirrors current production data and materializes any new local history. It does **not** rerun historical recovery.

Design principle:

```text
Massive  = ingestion/recovery source only
R2       = production archive
local    = development/research archive
backtest = pure consumer of canonical local history
```

## 4. Historical Data Status

Historical bootstrap is complete.

Runtime evidence:

```text
sessions: 337
range: 2025-04-21 -> 2026-08-21
canonical history: .local-data/objects/prices/daily-json/
Massive recovery requests: 50
```

The prior production R2 archive contained 289 daily Parquet sessions from 2025-06-30 through 2026-08-21. Recovery filled the older gap needed for the 211-session warmup + 126-session backtest window.

Do not spend more development time restructuring historical ingestion unless a real recovery failure appears.

## 5. Production Snapshot Mirror

```text
npm run local:sync
```

Current mirror behavior:

- production R2 is read-only during normal development
- complete R2 inventory is mirrored incrementally into `.local-data/objects/`
- D1 application tables are mirrored through read-only queries into `.local-data/d1/`
- R2 binary objects are copied as raw bytes
- manifest/checkpoint logic avoids repeat downloads

Runtime-validated snapshot:

```text
R2 objects: 2605
D1 application tables: 8
D1 rows: 10645
universe as_of: 2026-08-23
feature state as_of: 2026-08-21
```

D1 application tables mirrored:

- instruments
- universe_snapshots
- universe_membership
- ranking_runs
- ranking_entries
- workflow_runs
- strategy_versions
- backtest_runs

Production now also has the `market_data_sessions` migration/index used by recovery publishing and daily ingest.

## 6. Local Backtest Pipeline

```text
npm run local:backtest -- --rebuild
```

Backtest now consumes canonical local history only. It does not call Massive.

Feature/ranking replay artifacts are cached under `.local-backtest/`; repeat runs reuse historical computation when possible.

Latest proven run:

```text
id: local-2026-02-23-2026-08-21-126
strategy: momentum-v2
status: complete
period: 2026-02-23 -> 2026-08-21
sessions: 126
result: .local-data/objects/backtests/run=local-2026-02-23-2026-08-21-126/result.json
```

### Latest empirical baseline

Portfolio:

```text
initial capital: $100,000
final equity: $100,930
total return: 0.93%
max drawdown: -24.55%
```

Trades:

```text
trades: 75
wins: 39
losses: 36
win rate: 52.00%
95% CI: 40.87% -> 62.93%
break-even win rate: 50.85%
win-rate edge: 1.15%
average return: 0.30%
average win: 12.99%
average loss: -13.44%
payoff ratio: 0.97
profit factor: 1.02
average hold: 16.5 sessions
median hold: 15 sessions
```

Important ranking observation:

```text
rank 1-3: 51 trades, avg return -1.99%, PF 0.74
rank 4-6: 19 trades, avg return +4.77%, PF 2.74
rank 7-10: 5 trades, avg return +6.77%, PF 2.77
```

Do not over-interpret ranks 7-10 because sample size is only 5. The stronger conclusion is that current rank 1-3 selection quality is poor and likely overweights overly hot/extended names.

Holding-period observation:

```text
1-15 sessions: 48 trades, win rate 35.42%, median -3.89%
16-30 sessions: 25 trades, win rate 80.00%, median +4.25%
31-45 sessions: 2 trades, win rate 100%, median +65.79%
```

This baseline has almost no economic edge and unacceptable drawdown. It is infrastructure/research evidence, not a validated production strategy.

## 7. Current Strategy Baseline vs Target

Canonical implemented strategy is still:

```text
momentum-v2
```

Current backtest assumptions:

- initial capital $100k
- max 10 positions
- entry rank <= 10
- breakout20 required
- equal notional
- minimum hold 15 sessions
- maximum hold 60 sessions
- exit below SMA10 after minimum hold
- next-session-open execution
- final-close liquidation
- no costs/slippage

Target strategy is described in `STRATEGY.md` and should evolve into a new version rather than endlessly tuning v2 weights.

Next implementation target:

```text
strategy-v3
= right-side entry quality
+ initial stop / risk control
+ Top 50 -> strongest 3 sectors -> top 3 stocks/sector
+ max 9 positions
+ MAE/MFE instrumentation
```

Pyramiding and options should come **after** the initial-entry and risk-control layer is empirically improved.

## 8. Strategy Principles

Do not casually change these:

- active U.S. common stocks only for the stock universe
- SPY remains benchmark for relative strength
- 15-60 session target horizon
- right-side confirmation, not bottom fishing
- prefer 5/10/20 bullish trend structure and rising intermediate averages
- liquidity and volume confirmation are separate concepts
- avoid excessive ATR extension
- Top 50 opportunity set
- strongest 3 sectors
- up to 3 qualified stocks per sector
- maximum 9 offensive stock positions
- offensive sleeve <= 60% NAV
- every entry must have predefined exit logic
- stops/risk controls may only tighten
- never average down
- add only to profitable positions after new confirmation
- calls/options are an acceleration layer at first confirmed add, not part of initial baseline

## 9. Audit Instrumentation Status

Validated by current trade ledger:

- overall trade win rate
- initial-entry outcomes
- entry-rank buckets
- holding-period buckets

Not yet instrumented:

- Top-3 sector filter
- Add #1
- Add #2
- option acceleration
- MAE/MFE

The first v3 work should add MAE/MFE and selection context before option modeling.

## 10. Local Development Commands

Validation:

```bash
npm run local:check
```

Latest runtime proof:

- worker syntax checks passed
- JS tests: 8/8 passed
- frontend lint passed
- frontend production build passed

Daily data refresh:

```bash
npm run local:update
```

Backtest:

```bash
npm run local:backtest
npm run local:backtest -- --rebuild
```

Local app:

```bash
npm run local:dev
```

`local:dev` is now one command that starts both:

```text
API:      localhost:8787
Frontend: localhost:5173
```

The Vite frontend proxies `/api/*` to the local API.

## 11. `/backtest` UI Policy

Frontend visualization is deferred.

Current `/backtest` is intentionally a **plain-text research log**, not a dashboard.

Features:

- left-aligned terminal/log presentation
- deterministic formatted audit output
- `Copy log` button copies the complete text for posting back into chat/issues
- no cards/charts/tables/rich visualization for now

Keep this simple until strategy-v3 research is stable.

## 12. Key Files

Core strategy/research:

```text
worker/feature-core.js
worker/ranking-core.js
worker/backtest-core.js
worker/backtest-audit.js
worker/strategy-config.js
tools/local/backtest.mjs
```

Local storage/data:

```text
tools/local/fs-store.mjs
tools/local/sync.mjs
tools/local/history.mjs
tools/local/data-report.mjs
tools/local/api.mjs
```

Recovery / Cloudflare validation:

```text
tools/recovery/publish-history.mjs
tools/recovery/full-rebuild.mjs
tools/recovery/state-repair.mjs
migrations/0003_market_data_sessions.sql
```

Frontend research log:

```text
view/src/pages/Backtest.tsx
view/src/pages/Backtest.css
```

Operational lifecycle:

```text
docs/LOCAL_DATA_LIFECYCLE.md
```

## 13. Next Work

Do not return to frontend visualization yet.

Proceed in this order:

1. implement strategy-v3 initial-entry qualification
2. implement initial stop / risk control that can only tighten
3. implement sector metadata + Top-3-sector / Top-3-stock selection
4. cap offensive portfolio at 9 stocks
5. record MAE/MFE and setup/sector context in the trade ledger
6. rerun the same 126-session baseline and compare against momentum-v2
7. only after initial-entry/risk quality improves, implement Add #1 and Add #2
8. options acceleration last
9. rich frontend visualization last

Primary v3 success targets should initially emphasize risk quality, especially:

```text
max drawdown: materially below -24.55%
average loss: materially smaller than -13.44%
profit factor / expectancy: clearly above the near-flat v2 baseline
```

Do not optimize for win rate alone.

# FutureView Handoff

This is the current handoff for continuing FutureView. Prefer repository code and newer runtime logs if they conflict with this file.

Last updated: 2026-08-24.

## 1. Project Direction

FutureView is a U.S. equity research and backtesting system for a **right-side trend-following swing strategy** with an intended holding horizon of roughly **15-60 trading sessions / 3 weeks-3 months**.

Current priority is **research-core implementation and empirical validation**. Frontend visualization, pyramiding, and options remain secondary until initial-entry quality, sector selection, and risk control are empirically improved.

Production brokerage execution is out of scope.

## 2. Hard Operating Rules

Development/testing:

```text
GitHub + Codespaces = primary development environment
.local-data          = canonical local research store
Cloudflare R2/D1     = production archive/adapters
Massive              = ingestion/recovery/reference-data source
```

Production policy:

- merging to `master` is not deployment approval
- do not deploy or invoke broad production workflows without explicit approval
- production success must be proven by runtime/log evidence
- normal Cloudflare credentials should remain read-only
- temporary R2/D1 write permission may be enabled only for explicit maintenance/smoke work, then returned to read-only
- research enrichment workflows must not silently become production writes

No Cron/scheduled production processing is relied on during strategy testing.

## 3. Canonical Local Data Architecture

Canonical market history:

```text
.local-data/objects/prices/daily-json/date=YYYY-MM-DD/bars.json
```

Historical bootstrap/recovery:

```bash
npm run recovery:history
```

Normal daily local update:

```bash
npm run local:update
```

Design principle:

```text
Massive  = ingestion/recovery/reference-data source
R2       = production archive
local    = development/research archive
backtest = pure consumer of canonical local history
```

Historical recovery behavior:

- materializes mirrored R2 Parquet into canonical daily JSON
- uses Massive only when local/R2 history is insufficient
- request pacing/backoff protects against 429/5xx
- recovered sessions are written immediately

Cloudflare recovery publishing exists but is separate from normal local research.

## 4. Historical Data Status

Historical bootstrap is complete.

Runtime evidence:

```text
sessions: 337
range: 2025-04-21 -> 2026-08-21
canonical history: .local-data/objects/prices/daily-json/
Massive recovery requests: 50
```

The older gap required for the 211-session warmup + 126-session backtest window has been filled. Do not spend more development time restructuring historical ingestion unless a real recovery failure appears.

## 5. Production Snapshot Mirror

```bash
npm run local:sync
```

Current mirror behavior:

- production R2 is read-only during normal development
- R2 inventory is mirrored incrementally into `.local-data/objects/`
- D1 application tables are mirrored through read-only queries into `.local-data/d1/`
- manifest/checkpoint logic avoids repeat downloads

Latest known snapshot:

```text
universe as_of: 2026-08-23
feature state as_of: 2026-08-21
```

Important survivorship note:

The current historical backtest replays the synced current common-stock universe across the historical window. This is a known survivorship-bias limitation. Keep it unchanged during controlled v3 comparisons unless point-in-time universe is itself the variable being tested.

## 6. Current Backtest / Strategy Implementation

Current strategy identifier in code:

```text
rightside-v3
```

Current backtest configuration already includes part of the v3 entry layer:

```text
initial capital: $100,000
max positions: 9
entry rank max: 50
breakout20 required
close > SMA5 > SMA10 > SMA20 required
SMA5 > SMA10 > SMA20 required
minimum volume ratio20: 0.8
maximum entry ExtensionATR: 2.5
minimum hold: 15 sessions
maximum hold: 60 sessions
exit below SMA10 after minimum hold
```

However, v3 is **not complete**. Sector selection, initial-stop logic, and MAE/MFE are still incomplete/not validated.

Current ranking core still has legacy structure from v2. Do not interpret the strategy name alone as proof that the full v3 design is implemented.

## 7. Historical Empirical Baseline

The stable comparison baseline remains the prior 126-session run:

```text
id: local-2026-02-23-2026-08-21-126
period: 2026-02-23 -> 2026-08-21
sessions: 126
initial capital: $100,000
final equity: $100,930
total return: +0.93%
max drawdown: -24.55%
trades: 75
win rate: 52.00%
average return: +0.30%
average win: +12.99%
average loss: -13.44%
payoff ratio: 0.97
profit factor: 1.02
average hold: 16.5 sessions
```

Entry-rank evidence:

```text
rank 1-3: 51 trades, avg return -1.99%, PF 0.74
rank 4-6: 19 trades, avg return +4.77%, PF 2.74
rank 7-10: 5 trades, avg return +6.77%, PF 2.77 (tiny n)
```

Holding-period evidence:

```text
1-15 sessions: 48 trades, win rate 35.42%, median -3.89%
16-30 sessions: 25 trades, win rate 80.00%, median +4.25%
31-45 sessions: 2 trades, win rate 100%, median +65.79% (tiny n)
```

Interpretation:

- baseline economic edge is near zero
- drawdown is unacceptable
- rank 1-3 quality is poor despite receiving most trades
- many trades fail early; survivors can trend strongly
- v3 should prioritize entry quality and early risk control rather than win-rate optimization

## 8. Rejected Sector-Correlation Experiment

A controlled local experiment tested sector-aware RS by assigning each stock to the one of 11 sector ETFs with the highest trailing-60-session daily-return correlation.

Run:

```text
id: local-sector-rs-correlation-v1-2026-02-23-2026-08-21-126
strategy: rightside-v3
period: 2026-02-23 -> 2026-08-21
trades: 70
```

Result:

```text
final equity: $60,243
total return: -39.76%
max drawdown: -45.75%
win rate: 35.71%
average return: -6.20%
average win: +6.75%
average loss: -13.39%
payoff ratio: 0.50
profit factor: 0.27
rank 1-3 PF: 0.21
```

Decision:

```text
REJECT correlation-based sector assignment.
```

Reason: trailing return correlation is a return-cluster classification, not a company-sector classification. The assigned ETF can drift by market regime and destroy the intended meaning of stock-vs-sector leadership.

PR #13 (`feat/sector-aware-rs`) was closed and must not be merged/revived as the sector model.

## 9. Sector Metadata Research: Current Work

Active research branch:

```text
feat/sector-metadata-enrichment
```

Draft PR:

```text
#14 research: point-in-time sector metadata enrichment
```

Massive ticker overview supports point-in-time reference queries and supplies:

```text
sic_code
sic_description
company description
list_date
other ticker reference metadata
```

Local command:

```bash
npm run local:sector:enrich -- --as-of=2026-02-23 ...
```

Cache:

```text
.local-data/reference/ticker-overview/as-of=2026-02-23/symbols/*.json
.local-data/reference/ticker-overview/as-of=2026-02-23/manifest.json
```

Smoke validation:

```text
AAPL  3571 ELECTRONIC COMPUTERS
MSFT  7372 SERVICES-PREPACKAGED SOFTWARE
NVDA  3674 SEMICONDUCTORS & RELATED DEVICES
JPM   6021 NATIONAL COMMERCIAL BANKS
LLY   2834 PHARMACEUTICAL PREPARATIONS
XOM   2911 PETROLEUM REFINING
```

100-symbol follow-up plus prior smoke produced:

```text
cached: 105 / 5322
with SIC: 90
SIC coverage of cached: 85.7%
failed requests: 0
```

Missing classification has two forms:

- `unavailable_as_of` for symbols not available on the historical date
- `status=ok` but no SIC from Massive

Do not invent sector labels for missing SIC.

The tool also supports ranking-focused enrichment:

```bash
npm run local:sector:enrich -- \
  --as-of=2026-02-23 \
  --ranking-scope=ranked
```

This should be preferred for research coverage because only symbols that actually enter the ranking candidate set can affect the backtest.

## 10. GitHub Actions Enrichment

Manual Codespace enrichment is too slow because Massive request pacing, not local CPU, is the bottleneck.

A research-only GitHub Actions workflow has been added on `feat/sector-metadata-enrichment` to run SIC enrichment unattended.

Design:

```text
current universe
-> deterministic shards
-> one shard at a time
-> Massive point-in-time ticker overview
-> GitHub Actions artifact
```

Important constraints:

- keep one shard active at a time to avoid multiplying load against one Massive API key
- artifacts are research outputs only
- no D1/R2 production writes
- no deployment approval implied

## 11. Sector / Relative-Strength Design Going Forward

SPY remains the broad-market benchmark.

The intended hierarchy is:

```text
Market: SPY
Sector: actual auditable sector ETF
Stock: individual security
```

Once SIC-to-sector mapping is validated:

```text
MarketRS = stock return - SPY return
SectorRS = stock return - actual-sector ETF return
Sector strength = sector ETF return - SPY return
```

Do not use price correlation to infer sector.

Initial controlled sector-RS experiment should preserve total RS weight while only changing benchmark structure, e.g.:

```text
10% MarketRS20
10% MarketRS60
15% SectorRS20
10% SectorRS60
```

This weighting remains a research hypothesis, not a permanent strategy rule.

## 12. Strategy Principles

Do not casually change these:

- active U.S. common stocks only
- SPY remains market benchmark
- actual/auditable sector classification only
- 15-60 session target horizon
- right-side confirmation, not bottom fishing
- prefer bullish 5/10/20 structure and rising intermediate averages
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
- options acceleration only after stock-layer edge is validated

## 13. Audit Instrumentation Status

Validated by current trade ledger:

- overall trade win rate
- initial-entry outcomes
- entry-rank buckets
- holding-period buckets

Not yet instrumented:

- actual Top-3 sector filter
- Add #1
- Add #2
- option acceleration
- MAE/MFE

## 14. Key Commands

```bash
npm run local:check
npm run local:update
npm run local:backtest
npm run local:backtest -- --rebuild
npm run local:sector:enrich -- --as-of=2026-02-23 --ranking-scope=ranked
npm run local:dev
```

## 15. Key Files

Core strategy/research:

```text
worker/feature-core.js
worker/ranking-core.js
worker/backtest-core.js
worker/backtest-audit.js
worker/strategy-config.js
tools/local/backtest.mjs
```

Sector/reference research:

```text
tools/local/sector-enrich.mjs
.github/workflows/research-sector-enrichment.yml
```

Local storage/data:

```text
tools/local/fs-store.mjs
tools/local/sync.mjs
tools/local/history.mjs
tools/local/data-report.mjs
tools/local/api.mjs
```

Frontend remains a plain-text research log until strategy evidence is stronger.

## 16. Next Work

Proceed in this order:

1. complete point-in-time SIC metadata collection for the research-relevant stock set
2. measure SIC coverage specifically for ranked / Top-50 symbols
3. build an explicit, deterministic, testable SIC -> FutureView 11-sector mapping
4. audit ambiguous/missing mappings; do not guess
5. map sectors to the 11 sector ETFs
6. rerun controlled actual-sector-RS ablation against the same 126-session baseline
7. only if sector RS adds evidence, implement sector-strength ranking and Top-3-sector / Top-3-stock selection
8. implement initial stop / structural risk logic that can only tighten
9. add MAE/MFE and setup/sector context to trade ledger
10. rerun the same 126-session baseline
11. pyramiding only after initial-entry/risk quality improves
12. options acceleration after pyramiding evidence
13. rich frontend visualization last

Primary v3 success targets:

```text
max drawdown materially below -24.55%
average loss materially smaller than -13.44%
profit factor clearly above 1.02
expectancy clearly above +0.30%/trade
rank 1-3 quality materially better than PF 0.74
```

Do not optimize for win rate alone.

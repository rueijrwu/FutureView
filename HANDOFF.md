# FutureView — Current Research Handoff

Last rewritten: 2026-09-11
Branch: `intraday-futures-reset`

This branch is a research reset focused on MES intraday price-volume research and the infrastructure needed to support reliable backtests and later live trading.

The previous TSLA daily Strategy-1 / Layer1 / Layer2 research line is frozen as historical work. Do not silently carry its labels, targets, windows, memory rules, or model architecture into this branch.

---

# 0. Current objective

The immediate goal is not to define a trading setup or train a model.

The immediate goal is to build a reliable foundation for:

```text
MES historical data acquisition
-> canonical 5-minute price/volume bars
-> reproducible backtest feed
-> later live feed / execution integration
```

Research decisions should be deferred until the data and replay path are trustworthy.

---

# 1. Locked current scope

```text
Instrument: MES
Primary research bar: 5-minute
Information family: price + volume only
```

Price means OHLC where available. Volume is bar volume.

No order book, options flow, macro data, news, sentiment, fundamentals, or alternative data should be introduced unless explicitly approved later.

Do not assume RTH-only, ETH-only, long-only, short-only, fixed holding horizons, VWAP setups, opening-range rules, MFE/MAE targets, or any model architecture at this stage.

Those are experiment variables, not current baseline assumptions.

---

# 2. Data-first policy

Before strategy research, establish a provider-neutral historical bar layer.

Canonical bar schema:

```text
timestamp
symbol
open
high
low
close
volume
```

Requirements:

```text
UTC timestamps
chronological order
no duplicate timestamps per symbol
no null OHLCV rows
non-negative volume
provider-specific details hidden behind a common interface
```

The strategy/backtest layer should consume this canonical schema rather than provider-specific responses.

---

# 3. Current implementation status

A provider-neutral market-data layer has been added under:

```text
src/futureview/market_data/
```

Current components:

```text
provider.py  -> HistoricalBarProvider protocol + canonical schema
yahoo.py     -> Yahoo/yfinance historical provider
cli.py       -> command-line downloader
```

Current free bootstrap symbol:

```text
MES=F
```

Current downloader command:

```text
futureview-download-bars \
  --symbol 'MES=F' \
  --interval 5m \
  --start YYYY-MM-DD \
  --end YYYY-MM-DD
```

Yahoo is a bootstrap/prototyping source only. Its available intraday history depth is controlled by Yahoo and may be shorter than requested.

The architecture must remain open to later Databento / IBKR / other providers without changing downstream bar consumers.

---

# 4. Workflow / validation policy

A GitHub Actions smoke workflow exists at:

```text
.github/workflows/mes-5m-data-smoke.yml
```

It should run automatically on pushes to `intraday-futures-reset` that change the MES market-data implementation, tests, project config, workflow, or this handoff.

The smoke workflow must:

```text
install dependencies
run market-data unit tests
download recent MES=F 5-minute bars
validate canonical schema
validate timestamp ordering / uniqueness
validate OHLCV completeness
validate non-negative volume
print MES_5M_OK summary
upload log + sample dataset artifact
```

The first immediate verification task is to confirm that this workflow successfully downloads real recent MES 5-minute data from Yahoo.

---

# 5. Backtest architecture direction

After data download is verified, the next infrastructure milestone is a minimal replay/backtest core.

The important design rule is:

```text
historical feed and later live feed should expose the same bar semantics
```

The first backtest core should stay small and provider-independent. Candidate primitives include:

```text
BarFeed
Bar
Strategy
Order
Fill
Position
Portfolio
BrokerSimulator
```

Do not add strategy-specific logic into the data provider.

Do not optimize PnL or train models before replay correctness and execution timing semantics are defined.

---

# 6. Timing / leakage rule

For completed 5-minute bars, close and volume become available only when the bar completes.

Therefore any later backtest must explicitly define when a signal generated from bar `t` may place or fill an order.

Do not silently allow same-bar lookahead fills.

Execution semantics, session boundaries, roll handling, continuous-contract construction, slippage, commissions, and order types remain separate design decisions that must be explicitly recorded before becoming baseline behavior.

---

# 7. Futures-specific items not yet locked

The following remain open and should not be assumed yet:

```text
continuous MES vs individual contracts
roll rule
back-adjustment rule
RTH vs full Globex session
historical source beyond Yahoo bootstrap
raw storage resolution below 5-minute
commission/slippage model
live broker / execution provider
```

These should be resolved as infrastructure needs require them.

---

# 8. Frozen old research line

The following belong to the old TSLA daily project and are not active definitions here:

```text
TSLA target instrument
daily bars
Strategy-1 MA5/MA10/MA20 entry
5D/10D retrospective extrema
60D campaign horizon
W30 complete-path windows
U / B / C / Q labels
H / N / L states
90D daily normalized P/V input
30D Layer2 training lookback
15D retrain cadence
legacy memory=150
old CNN / quantile / BCE architecture
```

Preserve old results for historical reference only.

---

# 9. Immediate next action

```text
1. Trigger MES 5m Data Smoke on GitHub Actions.
2. Confirm real MES=F 5-minute bars download successfully.
3. Inspect row count, first/last timestamp, and artifact.
4. Only after that, begin the minimal historical replay/backtest core.
```

Do not start model training or technical-setup research before these infrastructure steps are complete.

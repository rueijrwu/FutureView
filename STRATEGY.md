# FutureView Core Trading Strategy

## Purpose

FutureView's offensive strategy is a **right-side trend-following swing strategy** designed for a holding period of roughly **3 weeks to 3 months / 15-60 trading sessions**.

Core principle:

> Trade with the trend. Do not fight the market.

The strategy does not predict bottoms or tops. A stock must prove strength through trend structure, breakout behavior, participation, sector context, and risk quality before capital is committed.

The offensive sleeve must not exceed **60% of total portfolio capital**.

## Strategy Constitution

1. Trade with the trend.
2. Enter only after right-side confirmation.
3. Add only to winning positions. Never average down.
4. Avoid excessive extension and exhaustion.
5. Every entry must have a predefined exit plan.
6. Risk controls may only tighten after entry.
7. Let strong trends continue rather than selling simply because price reaches a new high.
8. Prefer strong sectors, but sector context must be based on auditable classification rather than price-pattern guessing.
9. Use stock-specific structural/volatility-aware risk when appropriate, but never loosen risk after the fact.
10. Research quality is determined empirically by backtest evidence, not by intuition or ranking position alone.
11. Keep stock ranking, sector selection, and portfolio construction as separate layers.
12. Use point-in-time data only for historical validation.

The ranking model should answer:

> Which stocks currently show the strongest evidence of a high-quality, risk-controlled right-side setup for a 3- to 12-week move?

It should not simply rank the stocks that have risen the most recently.

## Trading Horizon and Moving-Average Roles

```text
SMA5   = short-term momentum warning
SMA10  = short-term trend control
SMA20  = core swing-trend structure
SMA50  = broader background trend
```

Preferred bullish structure:

```text
Price > SMA5 > SMA10 > SMA20
Slope(SMA10) > 0
Slope(SMA20) > 0
```

SMA50 should generally be flat-to-rising or positively aligned with the trade.

Trend stages:

```text
Emerging
Price > SMA20
SMA5 crosses/holds above SMA10
SMA10 flattening or rising

Confirmed
Price > SMA5 > SMA10 > SMA20
SMA10 rising
SMA20 rising

Breakout
Confirmed structure
+ pivot/prior-high/20D/50D breakout
+ preferably meaningful volume confirmation
```

## Universe, Liquidity, and Volume

Rank active U.S. common stocks only.

Baseline tradability requirements:

```text
price > $10
20D average dollar volume > approximately $50M
```

Liquidity and volume confirmation are separate:

```text
Liquidity = can the stock be traded consistently?
RVOL      = is the current breakout supported by participation?
```

Relative volume baseline:

```text
RVOL = current volume / 20D average volume
```

A breakout on elevated participation is stronger evidence than the same breakout on weak volume.

## Base / Consolidation Quality

Prefer constructive bases before acceleration:

```text
2-6 week consolidation
-> volatility contracts
-> volume becomes quieter/stable
-> 5/10/20 structure improves
-> breakout through pivot/prior high
-> volume expands
```

Avoid vertically extended, chaotic entries even when raw momentum is strong.

## Setup-Quality Ranking Philosophy

The ranking engine should emphasize setup quality rather than recent return alone.

Longer-term research hypothesis:

```text
SetupScore =
    25% Trend Structure
  + 20% Breakout / Pivot Quality
  + 20% Volume Quality
  + 15% Base / Volatility Contraction
  + 10% Relative Strength
  + 10% Trend Persistence
  - Risk / Extension Penalties
```

These weights are hypotheses, not permanent constants.

Relative strength should remain **supporting evidence**, not the dominant scoring component.

## Relative Strength Framework

Use two distinct benchmark questions.

### Broad-market leadership

```text
MarketRS20 = Return20(stock) - Return20(SPY)
MarketRS60 = Return60(stock) - Return60(SPY)
```

Question answered:

> Is this stock outperforming the broad U.S. market?

SPY remains the broad-market benchmark.

### Sector leadership

Once actual point-in-time sector mapping is available:

```text
SectorRS20 = Return20(stock) - Return20(actual sector ETF)
SectorRS60 = Return60(stock) - Return60(actual sector ETF)
```

Question answered:

> Is this stock outperforming its own sector context?

Sector strength itself is a separate measure:

```text
SectorMarketRS = Return(sector ETF) - Return(SPY)
```

This distinction must be preserved:

```text
stock vs SPY        = market leadership
stock vs sector ETF = stock leadership inside sector
sector ETF vs SPY   = sector leadership inside market
```

## Sector Classification Policy

Sector membership must come from an **auditable company classification source**.

Current research path:

```text
Massive point-in-time ticker overview
-> SIC code / SIC description
-> explicit FutureView sector mapping
-> sector ETF
```

Do not use trailing price correlation to infer a company's sector.

Do not silently guess sector for missing/ambiguous SIC. Missing classification must remain explicit and be audited.

The intended first ETF mapping is the 11 U.S. sector ETF framework:

```text
Materials               -> XLB
Communication Services  -> XLC
Energy                  -> XLE
Financials              -> XLF
Industrials             -> XLI
Information Technology  -> XLK
Consumer Staples        -> XLP
Real Estate             -> XLRE
Utilities               -> XLU
Health Care             -> XLV
Consumer Discretionary  -> XLY
```

ETF mapping is a research benchmark proxy; robustness against broader sector ETF families can be tested later.

## Rejected Sector-Correlation Experiment

A controlled experiment assigned each stock to the sector ETF with the highest trailing-60-session daily-return correlation and then used that ETF for SectorRS.

Result over the same 126-session test window:

```text
id: local-sector-rs-correlation-v1-2026-02-23-2026-08-21-126
trades: 70
total return: -39.76%
max drawdown: -45.75%
win rate: 35.71%
average return: -6.20%
profit factor: 0.27
rank 1-3 profit factor: 0.21
```

Decision:

```text
REJECT correlation-based sector assignment.
```

Interpretation:

- correlation clusters price behavior, not economic sector
- a stock can correlate most strongly with the wrong ETF for a temporary regime
- benchmark identity can drift through time
- the resulting SectorRS loses its intended meaning
- the experiment materially worsened rank 1-3 quality rather than fixing it

Do not revive this method by tuning its weights.

## Controlled Actual-Sector RS Test

After sector metadata is validated, the first actual-sector RS experiment should change only the RS benchmark structure while leaving entry/exit rules unchanged.

A useful controlled hypothesis is:

```text
10% MarketRS20
10% MarketRS60
15% SectorRS20
10% SectorRS60
```

This preserves the prior total 45% RS contribution for the purpose of an isolated A/B test.

However, this **45% RS composition is not the desired final strategy architecture**. If actual-sector RS proves useful, the final setup-quality model should reduce RS to a supporting role consistent with the broader SetupScore philosophy.

## Top-50 -> Sector -> Final Portfolio

Stock ranking and portfolio selection are separate layers.

```text
Qualified U.S. common stocks
-> setup-quality ranking
-> Top 50 opportunity set
-> attach actual sector metadata
-> rank sector strength
-> strongest 3 sectors
-> top 3 qualified stocks per sector
-> maximum 9 offensive stocks
```

Do not force nine positions if valid setups are unavailable.

### Sector-strength research inputs

Potential components:

- Top-50 representation
- median/aggregate setup quality
- sector ETF relative strength versus SPY
- breakout breadth
- volume participation across leaders

Initial research hypothesis:

```text
SectorScore =
    35% Top-50 Representation
  + 25% Median Setup Quality
  + 20% Sector ETF Relative Strength vs SPY
  + 10% Breakout Breadth
  + 10% Volume Participation
```

These weights must be audited historically.

Sector strength should influence portfolio selection, not substitute for stock-level setup quality.

## Entry Logic

Initial entry should normally require:

- bullish 5/10/20 structure or a clear transition into it
- improving/rising SMA10 and SMA20
- sufficient and stable liquidity
- acceptable ATR extension
- valid right-side trigger
- complete predefined exit logic before execution

Valid triggers may include:

1. reclaim of SMA5/SMA10 after constructive pullback
2. breakout from local consolidation/pivot
3. breakout through prior high
4. 20D or 50D breakout
5. strong gap-up with meaningful volume confirmation

A gap alone is not enough.

## Predefined Exit Plan

No position may be opened without a complete exit plan.

A stock trade plan should define, as applicable:

```text
entry_price
position_size
initial_stop
warning_ma
first_exit_ma
final_exit_ma
custom_structural_stop
profit_take_condition
extension/exhaustion condition
add_1_trigger
add_2_trigger
```

After entry:

```text
allowed:   stop 100 -> 105 -> 112
forbidden: stop 100 -> 95 because the trade is losing
```

Stops and structural exits may only move in the direction of reduced risk.

## Extension and Risk

Use ATR-based extension as a core measure:

```text
ExtensionATR = (Price - SMA20) / ATR14
```

A stock can remain a strong trend while still being a poor new entry if too extended.

Penalize or reject:

- excessive ATR extension
- very large gap risk
- abnormal volatility
- late parabolic acceleration

The current empirical evidence indicates that entry quality and early loss control matter more than simply increasing the weight of momentum/relative strength.

## Pyramiding

Positions are built in stages only after the thesis proves itself.

```text
Initial entry
-> Add #1 after new strength confirmation
-> Add #2 after another valid confirmation
```

Research baseline:

```text
Initial   40%
Add #1    35%
Add #2    25%
```

An add should normally require:

```text
existing position profitable
+ trend structure intact
+ new technical confirmation
+ extension still acceptable
```

Never average down.

Pyramiding is not the immediate next implementation priority. Initial-entry quality, sector selection, and risk control must improve first.

## Options Acceleration

Calls/options are an acceleration layer, not the baseline entry mechanism.

Planned use:

- only after first confirmed add / acceleration event
- evaluated separately from stock P&L
- realistic option execution assumptions required

Do not implement or optimize the option layer before stock-selection and stock-risk quality are validated.

## Progressive Exit Logic

Baseline concept:

```text
SMA5 loss   -> warning / optional small reduction
SMA10 loss  -> meaningful reduction
SMA20 loss  -> major structural reduction
runner      -> stock-specific trailing/structural stop
```

Possible research baseline:

```text
lose SMA5  -> reduce ~10-20% if weakness is meaningful
lose SMA10 -> reduce ~30-40%
lose SMA20 -> reduce ~40-60%
```

Exact thresholds are hypotheses and must be tested.

A stock-specific plan may use observable volatility/structure available at entry, but those rules cannot later be loosened merely to avoid realizing a loss.

## Supporting Indicators

Priority indicators:

- ATR / ATR%
- RVOL
- relative strength versus SPY and actual sector
- trend persistence / ADX-type confirmation
- volatility contraction / base quality

RSI/MACD/Stochastic may be secondary research tools but should not dominate the core engine because they overlap strongly with price momentum already represented elsewhere.

# Historical Empirical Baseline

The stable historical comparison run remains:

```text
id: local-2026-02-23-2026-08-21-126
period: 2026-02-23 -> 2026-08-21
sessions: 126
trades: 75
```

Portfolio:

```text
initial capital: $100,000
final equity: $100,930
total return: +0.93%
max drawdown: -24.55%
```

Trade quality:

```text
wins: 39
losses: 36
win rate: 52.00%
average return: +0.30%
average win: +12.99%
average loss: -13.44%
payoff ratio: 0.97
profit factor: 1.02
average hold: 16.5 sessions
median hold: 15 sessions
```

Interpretation:

- baseline has almost no economic edge
- total return is tiny relative to drawdown
- average loss is slightly larger than average win
- ranking quality is not monotonic with rank
- the baseline is research infrastructure evidence, not a validated strategy

## Ranking-Bucket Finding

```text
rank 1-3
51 trades
avg return -1.99%
profit factor 0.74

rank 4-6
19 trades
avg return +4.77%
profit factor 2.74

rank 7-10
5 trades
avg return +6.77%
profit factor 2.77
```

The rank 7-10 sample is too small for a strong conclusion.

The important evidence is that **rank 1-3 selection quality is poor** despite receiving most of the trades. This suggests the score can over-reward hot/extended or poorly timed names.

Do not respond by simply retuning legacy ranking weights. Change the entry/selection/risk structure and validate each change independently.

## Holding-Period Finding

```text
1-15 sessions
48 trades
win rate 35.42%
median return -3.89%

16-30 sessions
25 trades
win rate 80.00%
median return +4.25%

31-45 sessions
2 trades
win rate 100.00%
median return +65.79%
```

Interpretation:

- many early/short-duration trades fail
- positions that survive initial weakness and develop into sustained trends perform much better
- initial risk must be controlled tightly
- larger exposure should be earned by subsequent confirmation

# Current Implementation Status

Current strategy identifier in code:

```text
rightside-v3
```

The implementation currently includes part of the v3 entry layer and max-9 portfolio cap, but the full strategy described here is not yet validated.

Still incomplete/not validated:

- actual sector metadata mapping
- actual-sector RS
- sector-strength ranking
- Top-3-sector / Top-3-stock selection
- initial structural stop model
- MAE/MFE instrumentation
- pyramiding
- option acceleration

Treat `rightside-v3` as an implementation workstream, not proof that all v3 rules are active.

# Backtest Audit Priorities

Every backtest should report at least:

```text
win rate
average win
average loss
median trade return
payoff ratio
profit factor
maximum adverse excursion (MAE)
maximum favorable excursion (MFE)
average holding period
max drawdown
```

Current trade ledger already validates:

- complete-trade win rate
- initial-entry outcomes
- entry-rank buckets
- holding-period buckets

Not yet instrumented:

- Top-3-sector selection
- Add #1
- Add #2
- option acceleration
- MAE/MFE

## Research Comparisons Required

Priority comparisons:

1. SPY-only RS vs actual-sector-aware RS
2. Top-3-sector / Top-3-stock selection vs Top-9 without sector filtering
3. 5/10/20 structure only vs structure + breakout vs structure + breakout + RVOL
4. initial stop/risk model variants
5. MAE/MFE by setup type and entry rank
6. Add #1 incremental edge
7. Add #2 incremental edge
8. option acceleration only after stock-layer edge exists

No pyramiding percentage, option rule, or detailed ranking weight should be optimized before these baseline comparisons exist.

# Strategy-v3 Implementation Target

Target scope:

```text
strategy-v3
= right-side entry qualification
+ 5/10/20 trend alignment / transition logic
+ breakout and volume confirmation
+ extension control
+ point-in-time actual sector metadata
+ market and sector-relative strength
+ sector-strength selection
+ predefined initial stop
+ stop only tightens
+ Top 50 opportunity set
+ strongest 3 sectors
+ top 3 qualified stocks per sector
+ max 9 positions
+ MAE/MFE instrumentation
```

Implementation order:

1. finish point-in-time SIC metadata collection for research-relevant symbols
2. measure ranked/Top-50 SIC coverage
3. build explicit and testable SIC -> 11-sector mapping
4. audit ambiguous/missing sector mappings
5. rerun actual-sector-RS ablation against SPY-only baseline
6. implement sector-strength and Top-3-sector / Top-3-stock selection only if evidence supports it
7. implement initial stop / structural risk model
8. add MAE/MFE + setup/sector fields in trade ledger
9. rerun the same 126-session period
10. add pyramiding only if initial-entry/risk metrics improve
11. option acceleration after pyramiding evidence
12. rich frontend visualization last

## Initial v3 Success Criteria

Do not optimize for win rate alone.

Primary targets:

```text
max drawdown materially below -24.55%
average loss materially smaller than -13.44%
profit factor clearly above 1.02
expectancy clearly above +0.30%/trade
rank 1-3 profit factor materially above 0.74
```

Win rate must always be interpreted together with payoff ratio, expectancy, and drawdown.

# Future Plan

## CNN Meta-Controller Research

A future research layer may use a CNN or related sequence model as a **meta-controller**, not as a replacement for the deterministic trading strategy and not as a direct black-box buy/sell predictor.

The deterministic strategy constitution remains authoritative. The model may only adjust parameters inside predefined safe ranges.

Potential model outputs:

```text
1. dynamic ranking weights
2. dynamic entry criteria / thresholds
3. dynamic add criteria
4. dynamic add sizing
```

Example architecture:

```text
deterministic strategy rules
-> hard safety constraints
-> CNN / sequence meta-controller
-> bounded weights / thresholds / add sizing
-> ranking + portfolio selection
```

The model must never override hard strategy constraints, including:

```text
- never average down
- offensive sleeve <= 60% NAV
- maximum 9 stocks
- stops may only tighten
- next-session execution / no same-session look-ahead
- point-in-time data only
```

Preferred research order:

```text
1. CNN dynamic add criteria / sizing
2. CNN dynamic entry thresholds
3. CNN dynamic ranking weights
```

Dynamic ranking weights are deliberately last because they create the greatest overfitting risk.

Training and validation must be strictly point-in-time and walk-forward. Random train/test splits are not acceptable for strategy validation.

This research begins only after deterministic v3 establishes a clean baseline with entry, stop, actual sector selection, MAE/MFE, and add-event instrumentation.

# Offensive Capital Constraint

Total offensive allocation:

```text
<= 60% of total portfolio NAV
```

Maximum offensive stock count:

```text
3 sectors x 3 stocks = 9 stocks maximum
```

If nine fully built equal positions eventually consume the full offensive sleeve:

```text
60% / 9 ~= 6.67% NAV per full position
```

Using the research tranche baseline:

```text
Initial   ~= 2.67% NAV
Add #1    ~= 2.33% NAV
Add #2    ~= 1.67% NAV
Full      ~= 6.67% NAV
```

Do not force unused capacity into lower-quality setups.

# Summary

```text
Find liquid stocks with improving multi-week trend structure
-> prefer constructive bases and contraction
-> rank by setup quality
-> retain Top 50
-> attach auditable point-in-time sector metadata
-> evaluate market and sector-relative strength
-> identify strongest sectors only if empirical evidence supports the layer
-> select up to 3 qualified stocks per selected sector
-> maximum 9 offensive positions
-> define complete risk/exit plan before entry
-> wait for right-side confirmation
-> avoid excessive extension
-> enter with controlled initial risk
-> add only after the trade proves itself
-> never average down
-> only tighten risk
-> let strong trends continue
-> reduce progressively as predefined structure breaks
```

Guiding principle:

> **Trade with the trend. Use auditable sector context. Define the exit before entry. Add to strength. Never average down. Never loosen risk. Avoid exhaustion. Exit as the trend breaks.**

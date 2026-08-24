# FutureView Core Trading Strategy

## Purpose

FutureView's offensive strategy is a **right-side trend-following swing strategy** designed for a holding period of roughly **3 weeks to 3 months / 15-60 trading sessions**.

Core principle:

> Trade with the trend. Do not fight the market.

The strategy does not predict bottoms or tops. A stock must prove strength through trend structure, breakout behavior, volume, and risk quality before capital is committed.

This document describes the offensive trading logic. Defensive capital, reserve capital, and broad allocation policy are separate layers.

The offensive sleeve must not exceed **60% of total portfolio capital**.

## Strategy Constitution

1. Trade with the trend.
2. Enter only after right-side confirmation.
3. Add only to winning positions. Never average down.
4. Avoid excessive extension and exhaustion.
5. Every entry must have a predefined exit plan.
6. Risk controls may only tighten after entry.
7. Let strong trends continue rather than selling simply because price reaches a new high.
8. Prefer the strongest sectors rather than mechanically spreading capital across weak groups.
9. Use stock-specific structural/volatility-aware risk when appropriate, but never loosen risk after the fact.
10. Research quality is determined empirically by backtest evidence, not by intuition or ranking position alone.

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

The strategy should recognize trend stages:

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

Research hypothesis:

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

Relative strength versus SPY and the relevant sector remains supporting evidence, but should not dominate setup quality.

## Top-50 -> Sector -> Final Portfolio

Stock ranking and portfolio selection are separate layers.

```text
Qualified U.S. common stocks
-> setup-quality ranking
-> Top 50 opportunity set
-> group by sector
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
- sector relative strength versus SPY
- breakout breadth
- volume participation across leaders

Initial research hypothesis:

```text
SectorScore =
    35% Top-50 Representation
  + 25% Median Setup Quality
  + 20% Relative Strength vs SPY
  + 10% Breakout Breadth
  + 10% Volume Participation
```

These weights must be audited historically.

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
allowed: stop 100 -> 105 -> 112
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

Pyramiding is **not** the immediate next implementation priority. Initial-entry quality and risk control must improve first.

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
- relative strength versus SPY / sector
- trend persistence / ADX-type confirmation
- volatility contraction / base quality

RSI/MACD/Stochastic may be secondary research tools but should not dominate the core engine because they overlap strongly with price momentum already represented elsewhere.

# Current Empirical Baseline: momentum-v2

The implemented canonical strategy is still `momentum-v2`. The latest complete local backtest is the empirical baseline against which strategy-v3 should be compared.

Run:

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
total return: 0.93%
max drawdown: -24.55%
```

Trade quality:

```text
wins: 39
losses: 36
win rate: 52.00%
95% CI: 40.87% -> 62.93%
break-even win rate: 50.85%
win-rate edge: 1.15%
average return: 0.30%
median return: 0.82%
average win: 12.99%
average loss: -13.44%
payoff ratio: 0.97
profit factor: 1.02
average hold: 16.5 sessions
median hold: 15 sessions
```

Interpretation:

- the baseline has almost no economic edge
- total return is tiny relative to the drawdown
- average loss is larger than average win
- win rate is only slightly above observed break-even
- confidence interval is wide enough that the observed win rate should not be treated as a stable edge

## Ranking-Bucket Finding

```text
rank 1-3
51 trades
win rate 50.98%
avg return -1.99%
profit factor 0.74

rank 4-6
19 trades
win rate 52.63%
avg return +4.77%
profit factor 2.74

rank 7-10
5 trades
win rate 60.00%
avg return +6.77%
profit factor 2.77
```

The rank 7-10 sample is too small for a strong conclusion.

The important evidence is that current **rank 1-3 selection quality is poor** despite receiving most of the trades. This suggests the current score may overweight names that are already too hot/extended or otherwise poorly timed for entry.

Do not respond by simply retuning `momentum-v2` weights. The next version should change the selection/entry/risk model more structurally.

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

- most early/short-duration trades fail
- positions that survive initial weakness and develop into sustained trends perform much better
- this supports the intended right-side philosophy: initial risk must be controlled tightly, and larger exposure should be earned by subsequent confirmation

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

1. Top-3-sector / Top-3-stock selection vs Top-9 without sector filtering
2. 5/10/20 structure only vs structure + breakout vs structure + breakout + RVOL
3. initial stop/risk model variants
4. MAE/MFE by setup type and entry rank
5. Add #1 incremental edge
6. Add #2 incremental edge
7. option acceleration only after stock-layer edge exists

No pyramiding percentage, option rule, or detailed ranking weight should be optimized before these baseline comparisons exist.

# Strategy-v3 Implementation Target

The next strategy version should focus on **initial-entry quality and loss control**, not frontend visualization and not options.

Target scope:

```text
strategy-v3
= right-side entry qualification
+ 5/10/20 trend alignment / transition logic
+ breakout and volume confirmation
+ extension control
+ predefined initial stop
+ stop only tightens
+ Top 50 opportunity set
+ strongest 3 sectors
+ top 3 qualified stocks per sector
+ max 9 positions
+ MAE/MFE instrumentation
```

Implementation order:

1. initial-entry qualification
2. initial stop / structural risk model
3. sector metadata and sector-strength layer
4. max-9 final selection
5. MAE/MFE + setup/sector fields in trade ledger
6. rerun same 126-session period and compare to momentum-v2
7. add pyramiding only if initial-entry/risk metrics improve
8. option acceleration after pyramiding evidence
9. rich frontend visualization last

## Initial v3 Success Criteria

Do not optimize for win rate alone.

First targets should emphasize risk-adjusted improvement:

```text
max drawdown materially below -24.55%
average loss materially smaller than -13.44%
profit factor clearly above 1.02
expectancy clearly above 0.30%/trade
```

Win rate should remain paired with payoff ratio and drawdown.

# Future Plan

## CNN Meta-Controller Research

A future research layer may use a CNN or related sequence model as a **meta-controller**, not as a replacement for the deterministic trading strategy and not as a direct black-box buy/sell predictor.

The deterministic strategy constitution remains authoritative. The model may only adjust parameters inside predefined safe ranges.

Potential model outputs:

```text
1. dynamic ranking weights
   - Trend Structure weight
   - Breakout / Pivot weight
   - Volume Quality weight
   - Base / Contraction weight
   - Relative Strength weight
   - Persistence weight

2. dynamic entry criteria / thresholds
   - minimum RVOL
   - maximum allowed ExtensionATR
   - breakout strictness
   - minimum base quality
   - minimum sector strength
   - minimum SetupScore

3. dynamic add criteria
   - Add #1 confidence threshold
   - Add #2 confidence threshold
   - required RVOL / breakout quality for each add
   - allowed extension for each add

4. dynamic add sizing
   - Add #1 size multiplier
   - Add #2 size multiplier
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

The preferred research order is:

```text
1. CNN dynamic add criteria / sizing
2. CNN dynamic entry thresholds
3. CNN dynamic ranking weights
```

Dynamic ranking weights are deliberately last because they create the greatest overfitting risk.

Evaluation must compare deterministic and adaptive variants independently:

```text
strategy-v3-fixed
vs
strategy-v3 + CNN dynamic adds
vs
strategy-v3 + CNN dynamic criteria
vs
strategy-v3 + CNN dynamic weights
```

Primary evaluation metrics:

```text
profit factor
expectancy
max drawdown
average loss
win rate
turnover
Add #1 profit factor / expectancy
Add #2 profit factor / expectancy
```

Training and validation must be strictly point-in-time and walk-forward. Random train/test splits are not acceptable for strategy validation because they can leak market-regime information across time.

This research should begin only after deterministic strategy-v3 establishes a clean baseline with entry, stop, sector selection, MAE/MFE, and add-event instrumentation.

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
-> identify strongest 3 sectors
-> select up to 3 qualified stocks per sector
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

> **Trade with the trend. Follow the strongest sectors. Define the exit before entry. Add to strength. Never average down. Never loosen risk. Avoid exhaustion. Exit as the trend breaks.**

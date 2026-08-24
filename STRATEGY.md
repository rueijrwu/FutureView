# FutureView Core Trading Strategy

## Purpose

FutureView's offensive strategy is a **right-side trend-following swing strategy** designed for a holding period of roughly **3 weeks to 3 months**.

The core principle is simple:

> Trade with the trend. Do not fight the market.

The strategy does not try to predict bottoms or tops. A stock must first prove strength through price structure, trend, breakout behavior, and volume confirmation before capital is committed.

This document describes the trading logic itself. Defensive allocation, cash management, and other non-offensive capital are intentionally out of scope here.

The offensive sleeve must not exceed **60% of total portfolio capital**.

---

## Strategy Constitution

The core rules are:

1. **Trade with the trend.**
2. **Enter only after price confirms strength.**
3. **Add only to winning positions. Never average down.**
4. **Avoid chasing excessive extension.**
5. **Reduce exposure progressively as trend structure deteriorates.**
6. **Let strong trends continue instead of taking profit simply because a stock reaches a new high.**
7. **Use stock-specific risk and profit-management levels when volatility or structure requires it.**
8. **Concentrate offensive capital in the strongest market sectors rather than spreading capital mechanically across weak groups.**
9. **Every position must have its exit conditions defined at the time of entry. No stock or option position may be opened without a complete exit plan.**
10. **After entry, risk controls may only be tightened. Stops, moving-average exits, or structural exit thresholds must never be loosened to tolerate a losing trade.**

The ranking model should therefore answer:

> Which stocks currently show the strongest evidence of a high-quality, risk-controlled right-side setup for a 3- to 12-week move?

It should not simply answer which stocks have risen the most recently.

---

## Trading Horizon

Target holding period:

```text
15 to 60 trading sessions
approximately 3 weeks to 3 months
```

The moving averages have different roles within this horizon:

```text
SMA5   = short-term momentum warning
SMA10  = short-term trend control
SMA20  = core swing-trend structure
SMA50  = background trend filter
```

SMA5 should not dominate the strategy because normal noise within a multi-week trend can cross the 5-day moving average repeatedly.

---

## Universe and Liquidity

The strategy ranks active U.S. common stocks only.

A stock must first pass basic tradability requirements, including:

- price above the minimum liquidity threshold used by FutureView
- sufficient 20-session average dollar volume
- sufficiently stable trading volume

Liquidity and volume confirmation are separate concepts.

### Liquidity

Liquidity answers:

> Can this stock be traded consistently without depending on an isolated high-volume day?

The current baseline is approximately:

```text
20D average dollar volume > $50M
```

### Volume confirmation

Volume confirmation answers:

> Is the current breakout or acceleration supported by real participation?

Relative volume should be tracked using a measure such as:

```text
RVOL = current volume / 20D average volume
```

A breakout accompanied by clearly elevated RVOL is stronger evidence than a breakout on ordinary or weak volume.

---

## Trend Structure

The preferred established bullish structure is:

```text
Price > SMA5 > SMA10 > SMA20
```

with rising short- and intermediate-term averages, especially:

```text
Slope(SMA10) > 0
Slope(SMA20) > 0
```

SMA50 provides the broader background trend and should generally be flat-to-rising or positively aligned with the trade.

A stock does not need to begin with perfect moving-average alignment. The strategy should recognize stages of trend development.

### Emerging

Early improvement, suitable mainly for monitoring:

```text
Price > SMA20
SMA5 crosses or moves above SMA10
SMA10 is flattening or rising
```

### Confirmed

Primary offensive candidate:

```text
Price > SMA5 > SMA10 > SMA20
SMA10 rising
SMA20 rising
```

### Breakout

Confirmed structure plus a meaningful right-side trigger:

```text
prior high / pivot breakout
or 20D / 50D high breakout
or high-quality gap-up with volume confirmation
```

---

## Base and Consolidation Quality

The strategy should favor stocks that build a constructive base before advancing.

A high-quality setup often looks like:

```text
2-6 week consolidation
        ↓
price volatility contracts
        ↓
volume becomes quieter or stable
        ↓
5/10/20-day trend structure improves
        ↓
breakout through pivot or prior high
        ↓
volume expands
```

This is preferable to chasing a stock that has already become highly volatile and vertically extended.

Base quality and volatility contraction should therefore be important ranking inputs.

---

## Ranking Philosophy

The ranking engine should primarily evaluate **setup quality**, not historical return alone.

The ranking should emphasize five questions:

### 1. Trend existence

Does a bullish trend actually exist?

### 2. Trend strength

Is the trend strong enough to justify offensive exposure?

### 3. Trend confirmation

Is the move confirmed by breakout behavior, volume, and price structure?

### 4. Trend maturity

Is the stock early/healthy in the move, or already excessively extended?

### 5. Tradeability

Is liquidity, volatility, and risk structure appropriate for a multi-week position?

A useful research starting point is:

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

These weights are **research hypotheses**, not permanent strategy constants.

Relative strength versus SPY and the relevant sector should remain useful supporting evidence, but the strategy should not reduce to simply ranking the stocks with the strongest recent returns.

---

## Top-50, Sector Rotation, and Final Stock Selection

The stock ranking and the final portfolio-selection process are separate layers.

FutureView should first rank the qualified stock universe by SetupScore and retain the **Top 50** as the active opportunity set.

The offensive portfolio is then selected through a sector-strength layer:

```text
Qualified U.S. common stocks
        ↓
Setup-quality ranking
        ↓
Top 50 stocks
        ↓
Group Top 50 by sector
        ↓
Rank sector strength
        ↓
Select strongest 3 sectors
        ↓
Select top 3 qualified stocks in each sector
        ↓
Maximum 9 offensive stocks
```

The purpose is to follow both **stock trend** and **sector trend**. A strong individual stock in a broadly weak sector should generally receive less preference than a similarly strong stock participating in broad sector leadership.

### Sector strength

Sector ranking should measure broad participation rather than letting a single exceptional stock define the entire sector.

Useful inputs include:

- representation of the sector within the Top 50
- median or aggregate SetupScore of Top-50 members in the sector
- sector relative strength versus SPY
- sector breakout breadth
- volume participation across leading stocks

An initial research hypothesis is:

```text
SectorScore =
    35% Top-50 Representation
  + 25% Median Setup Quality
  + 20% Relative Strength vs SPY
  + 10% Breakout Breadth
  + 10% Volume Participation
```

These weights must be audited historically and are not permanent constants.

### Final stock selection

Within each of the three strongest sectors, select the **three highest-ranked stocks that still satisfy the entry-quality requirements**.

The target maximum is:

```text
3 sectors × 3 stocks = 9 stocks
```

However, the strategy should **not force exactly nine positions**.

If a selected sector has fewer than three genuinely qualified setups, only the qualified stocks should be used. For example:

```text
Sector A: 3 qualified stocks
Sector B: 3 qualified stocks
Sector C: 1 qualified stock
Total:    7 offensive positions
```

Unused capacity remains uncommitted rather than being filled with lower-quality trades.

This preserves the core principle:

> If the market does not provide a valid setup, do not manufacture one.

---

## Entry Logic

The strategy uses **right-side confirmation** rather than bottom fishing.

An initial entry should normally require:

- bullish 5/10/20-day price structure or a clear transition into it
- improving/rising SMA10 and SMA20
- sufficient and stable liquidity
- acceptable extension from the underlying trend
- a valid technical trigger
- a complete pre-defined exit plan recorded before or at execution

Valid triggers can include:

1. reclaim of SMA5/SMA10 after a constructive pullback
2. breakout from a local consolidation or pivot
3. breakout through a prior high
4. 20-day or 50-day breakout
5. strong gap-up with meaningful volume confirmation

A gap alone is not a sufficient reason to buy.

No entry is valid unless the exit logic is already known.

---

## Pre-Defined Exit Plan Requirement

Every stock and option position must have its exit plan defined **before or at the moment of entry**.

The purpose is to prevent discretionary drift after a trade moves against the thesis.

A valid plan should define, as applicable:

```text
entry_price
position_size

warning_ma
first_exit_ma
final_exit_ma

custom_structural_stop
profit_take_condition
ath_or_extension_condition

add_1_trigger
add_2_trigger
```

For options, the plan should additionally define:

```text
contracts
strike
expiration

first_contract_exit_condition
remaining_contract_exit_condition
full_option_exit_condition
stock_conversion_condition
```

The plan must be based on observable technical structure available at entry, not on a future discretionary decision.

### Risk controls may only tighten

After a trade is opened, exit conditions may be updated only when the change **reduces risk or locks in additional profit**.

Allowed:

```text
initial stop = 100
price advances
stop -> 105 -> 112
```

Not allowed:

```text
initial stop = 100
price weakens toward 100
stop -> 95
```

The same rule applies to moving-average exits and structural stops.

> Stops can move in the direction of reduced risk, never in the direction of increased risk.

A trade must never be given more room merely because the position is losing or because the trader hopes the trend will recover.

---

## Avoiding Excessive Extension

Following a trend does not mean chasing every strong stock at any price.

The strategy should distinguish between:

```text
healthy strength
```

and:

```text
late-stage / excessive extension
```

ATR-based extension should be used as a core risk measure, for example:

```text
ExtensionATR = (Price - SMA20) / ATR14
```

A stock that is many ATR above SMA20 may still have a strong trend but may be a poor new entry.

The ranking system should therefore penalize excessive extension, very large gap risk, and abnormal volatility.

---

## Pyramiding and Position Building

Positions are built in stages.

The key rule is:

> Add only when the stock continues to prove the thesis.

Never average down simply because price declines.

A position may be built in up to three tranches:

```text
Initial entry
    ↓
Add #1 after new strength confirmation
    ↓
Add #2 after another valid confirmation
```

A useful baseline for research is:

```text
Initial   40%
Add #1    35%
Add #2    25%
```

The exact proportions should be audited rather than treated as permanent constants.

Possible add triggers include:

- breakout through a new pivot or prior high
- fresh consolidation followed by another breakout
- high-quality gap-up with strong volume
- renewed upside acceleration while the existing position is already profitable

An add should normally require:

```text
existing position profitable
+ bullish trend structure intact
+ new technical confirmation
+ extension still acceptable
```

Simply making another daily high is not enough by itself.

Every add is a new capital commitment and must also have its own exit logic defined before execution.

---

## New Highs and Profit Taking

A new high is generally **evidence in favor of the trend**, not automatically a reason to sell.

Therefore the strategy should not use a simple rule such as:

```text
new high -> sell 30%
```

Instead, partial profit-taking at new highs should be conditional on evidence of possible exhaustion, such as:

- extreme ATR extension
- parabolic acceleration
- unusually large gap or range expansion
- very high RVOL after an already extended run
- stock-specific resistance or risk conditions

Any such profit-taking rule must already be defined in the trade plan at entry or at the time of a later add.

The guiding principle is:

> Follow strength, but do not chase exhaustion.

---

## Progressive Exit Logic

The strategy exits progressively as trend structure weakens.

A baseline framework is:

```text
SMA5 loss   -> warning / optional small reduction
SMA10 loss  -> meaningful reduction
SMA20 loss  -> major structural reduction
remaining position -> stock-specific trailing or structural stop
```

The initial research baseline can use staged reductions similar to:

```text
lose SMA5   -> reduce about 10-20% when weakness is meaningful
lose SMA10  -> reduce about 30-40%
lose SMA20  -> reduce about 40-60%
runner      -> manage with stock-specific structural stop
```

The exact percentages should be validated by historical testing.

A close below an average should not necessarily be treated identically in every stock. Volume, volatility, price structure, and the location of recent pivots should be considered **when the exit plan is established**.

These factors may justify different predefined exit lines for different stocks, but they must not be used after the fact to postpone an already-triggered exit.

---

## Stock-Specific Trade Plan

Each active position may define its own risk-management levels at entry.

A trade plan may contain:

```text
initial_entry
add_1_trigger
add_2_trigger

sma5_warning
sma10_exit_level
sma20_exit_level

custom_structural_stop
profit_extension_threshold
trailing_stop
```

This is important because stocks have different volatility profiles. A rule appropriate for a low-volatility large-cap stock may be too tight for a higher-beta momentum stock.

The system should support systematic defaults while still allowing a stock-specific plan based on observable technical structure.

After entry, the plan may only be changed in a direction that reduces risk or locks in gains. It cannot be relaxed to avoid taking a loss.

---

## Important Supporting Indicators

The following indicators align well with this strategy:

### ATR / ATR%

Use for:

- extension control
- comparing volatility across stocks
- stock-specific stops
- identifying exhaustion risk

### Relative Volume (RVOL)

Use for:

- breakout confirmation
- gap validation
- detecting unusually strong participation

### Relative Strength versus SPY / Sector

Use for:

- confirming that the stock is outperforming its market context
- distinguishing true leadership from a broad market move

### Trend Persistence / ADX

Use primarily as supporting confirmation that price is trending rather than oscillating randomly.

### Volatility Contraction / Base Quality

Use for identifying cleaner right-side setups before breakout and avoiding late, chaotic entries.

Indicators such as RSI, MACD, and Stochastic may be useful for secondary analysis but should not dominate the core ranking because they substantially overlap with price momentum and trend information already represented by the strategy.

---

## Backtest Audit Priority: Win Rate

The current strategy's win rate is **unknown until measured**. The first backtest objective is therefore to establish the empirical hit rate of the strategy before optimizing weights, leverage, or return.

Win rate must be measured at multiple layers rather than reported as one portfolio-level number.

### 1. Complete-trade win rate

For every completed stock trade:

```text
win = realized net trade P&L > 0
loss = realized net trade P&L <= 0
```

Report the percentage of profitable completed trades.

### 2. Initial-entry win rate

Measure whether the initial stock entry generates positive forward returns over the intended holding horizon.

At minimum, report forward returns at:

```text
20 sessions
40 sessions
60 sessions
```

This isolates the quality of the original setup from later pyramiding decisions.

### 3. Add-on win rate

Each add is a separate capital decision and must be audited separately:

```text
Initial entry
Add #1
Add #2
```

For each layer, measure whether the incremental capital added at that point produces a positive realized or forward return.

A pyramiding rule should not be assumed beneficial simply because the final combined position is profitable.

### 4. Option-acceleration win rate

When the first confirmed breakout add uses Call options, the option layer must be evaluated independently from the stock position.

Track at minimum:

- profitable option sequences / total option sequences
- first-contract exit result
- remaining-contract exit result
- full option-layer P&L
- whether conversion from option profit into stock improved total trade outcome

Option leverage should only remain part of the strategy if the confirmation layer demonstrates a repeatable edge after realistic option execution assumptions are introduced.

### 5. Sector-conditioned win rate

The sector-selection thesis must be tested directly.

Compare:

```text
Top-3-sector / Top-3-stock selection
vs
Top-9 stocks without sector filtering
vs
broader Top-50 eligible setups
```

The key question is whether concentrating in the strongest three sectors materially improves hit rate and/or payoff quality.

### 6. Breakout-confirmation win rate

Compare valid right-side confirmations against simpler trend qualification.

Examples:

```text
5/10/20 bullish structure only
vs
bullish structure + breakout
vs
bullish structure + breakout + RVOL confirmation
```

This determines whether breakout and volume confirmation actually increase the probability of a successful trade.

### Win rate is not sufficient by itself

A high hit rate can still produce a poor strategy if losses are much larger than gains. Every win-rate report must therefore be paired with at least:

```text
win rate
average win
average loss
median trade return
payoff ratio = average win / abs(average loss)
profit factor = gross profits / gross losses
maximum adverse excursion (MAE)
maximum favorable excursion (MFE)
average holding period
```

The first audit should prioritize **statistical description**, not parameter optimization.

The initial research questions are:

1. Does Top-3-sector selection improve win rate versus simply buying the highest-ranked stocks?
2. Does breakout + RVOL confirmation improve win rate versus moving-average trend structure alone?
3. Is Add #1 more reliable than the initial entry?
4. Does Add #2 continue to add edge, or does it mostly add late-stage risk?
5. Does the option-acceleration layer improve expected outcome after accounting for its additional risk and execution complexity?
6. Which predefined exit structures preserve the best combination of hit rate and payoff ratio?

No ranking weight, pyramiding percentage, option rule, or exit threshold should be optimized before this baseline audit is established.

---

## Offensive Capital Constraint

This strategy describes only the offensive sleeve.

The total offensive allocation must not exceed:

```text
60% of total portfolio capital
```

The final offensive portfolio contains at most **nine stocks**, selected from the strongest three sectors with at most three stocks per sector.

If all nine positions eventually reach equal fully built size, the theoretical average maximum per stock is approximately:

```text
60% / 9 ≈ 6.67% of total portfolio NAV
```

Because positions are pyramided, the full allocation is not committed at the initial entry. Using the research baseline of 40% / 35% / 25% of a full stock allocation, a fully allocated 6.67%-NAV position would be built approximately as:

```text
Initial   ≈ 2.67% NAV
Add #1    ≈ 2.33% NAV
Add #2    ≈ 1.67% NAV
Full      ≈ 6.67% NAV
```

These tranche sizes are research assumptions and should be audited.

If fewer than nine valid positions are available, unused offensive capacity remains uncommitted.

Defensive capital, reserve capital, cash posture, and regime-level allocation are separate layers and are intentionally not defined in this document yet.

---

## Summary

FutureView's offensive strategy is best summarized as:

```text
Find liquid stocks with improving multi-week trend structure
        ↓
prefer constructive bases and volatility contraction
        ↓
rank qualified stocks by setup quality
        ↓
retain the Top 50 opportunity set
        ↓
identify the strongest 3 sectors
        ↓
select up to the Top 3 qualified stocks per sector
        ↓
maximum 9 offensive stocks
        ↓
define the complete exit plan before entry
        ↓
wait for right-side price and volume confirmation
        ↓
enter without excessive extension
        ↓
add only when the position proves itself again
        ↓
define exit conditions for every additional capital commitment
        ↓
let strong trends continue
        ↓
reduce progressively when predefined 5/10/20-day or structural conditions trigger
        ↓
only tighten risk controls as the trade develops
```

The strategy should continuously favor confirmed market strength over prediction:

> **Trade with the trend. Follow the strongest sectors. Define the exit before entry. Add to strength. Never average down. Never loosen risk. Avoid exhaustion. Exit as the trend breaks.**
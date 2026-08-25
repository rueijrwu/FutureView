# Strategy 1 — Entry Quality Framework

This document records the current event-conditioned Strategy 1 research framework. The frozen Strategy 1 mechanics are unchanged.

## Core research question

> Under the fixed Strategy 1 execution rules, can a model provide a useful causal score for whether the current legal Entry1 is a high-quality entry?

The model is not asked to imitate a perfect future pattern and is not trained to predict Oracle directly.

## Fixed Strategy 1 mechanics used by this research

Strategy 1 is defined from the perspective of **entering on the current legal Entry1 date** and then following the already-specified campaign rules. The research layer must not redefine the mechanics.

### Entry1

The legal Entry1 condition is based on the 5/10/20-day moving-average trend structure already defined by Strategy 1.

### Addon reference levels

Addon1 / Addon2 are **not** defined as breakouts of a rolling previous-20-session highest close.

At the Entry1 date:

```text
1. look backward from the Entry1 date,
2. identify the two nearest prior Local Maximum reference points,
3. require the two Local Maximum trading dates to be separated by more than 10 trading days,
4. lock those two Local Maximum levels at Entry1,
5. use those fixed structural reference levels for the later Addon1 / Addon2 decisions according to the existing Strategy 1 execution rules.
```

The addon structure is therefore anchored to market structure known at Entry1, not to a dynamically changing rolling 20-day breakout threshold.

### Exit

The existing Strategy 1 exit rules remain fixed:

```text
Close < MA5  -> sell 50% of the current position
Close < MA10 -> exit the remaining position
```

If both exit conditions become actionable together, the full-exit rule has priority according to the existing Strategy 1 mechanics.

### Trading spacing

After a Strategy 1 transaction, the next three trading sessions are blocked from another strategy transaction; the earliest next eligible strategy transaction is the fourth trading session after the prior action. Existing horizon-end forced liquidation behavior remains unchanged.

### Research guardrail

The Strategy 1 entry/addon/exit/spacing mechanics are treated as fixed infrastructure. Baseline, Oracle, model-target, and evaluation definitions must be built **on top of these rules** and must not silently alter them.

## Fixed scope for the current main analysis

```text
symbol = SPY
period = 5y
sample = legal Strategy 1 Entry1 event
input lookback = 50 daily sessions
comparison window = 30 trading sessions
no random split
```

The current main line remains 30D / 5y until the reference structure is fully understood. Earlier 15/30/45/60 horizon comparisons are exploratory only and do not currently redefine the main horizon.

## Three separate objects

### 1. Baseline

```text
Baseline_t = realized profit from taking the current legal Entry1 at t
             and following the frozen Strategy 1 mechanics inside the same 30D window
```

Baseline describes how profitable the entry implied by the current Strategy 1 pattern actually is.

Baseline is **not**:
- a model prediction,
- or an always-on policy benchmark.

Its exact relationship to the model target/label is intentionally left unresolved until the definitions are finalized.

### 2. Oracle

```text
Oracle_t = future-known best legal Strategy 1 profit available in the same 30D window
```

Oracle describes the best legal profit that could have been achieved with foreknowledge of the future.

Oracle is **not**:
- a realizable live-trading objective.

Its exact role relative to the final target/label definition remains to be finalized.

The current implementation guarantees:

```text
Oracle_t >= max(0, Baseline_t)
```

### 3. Model score

The model sees only causal OHLCV information available through the legal Entry1 close and produces an Entry Quality Score.

The score should distinguish whether the current entry is high quality, rather than simply detect that some opportunity exists somewhere in the future window.

## Profit-quality reference frame

Baseline and Oracle should be interpreted jointly.

```text
Baseline high, Oracle high
  current entry is profitable and the market also contains strong opportunity

Baseline low, Oracle low
  current entry is weak and the market contains little opportunity

Baseline low or negative, Oracle high
  the market contains opportunity, but the current entry timing is poor

Baseline high, Oracle even higher
  current entry is good, but a better legal opportunity exists in the same window
```

The difference

```text
OpportunityGap_t = Oracle_t - Baseline_t
```

measures the distance between the current entry outcome and the future-known best legal outcome in the same 30D window.

The exact naming and role of this difference are also left open until the Baseline / Oracle / target definitions are finalized.

## Existing 30D / 5y evidence

The current event-conditioned dataset contains approximately 94 legal Entry1 samples before common-future filtering.

Observed 30D reference levels in the existing run were approximately:

```text
Baseline / current-entry realized profit
  mean ~ +0.10%
  median ~ +0.03%
  win rate ~ 51%

Oracle
  mean ~ +0.95%

Oracle - Baseline
  mean ~ +0.86%
```

CNN A remains the strongest tested causal model in the existing 30D / 5y model comparison, with positive mean entry-return ranking and positive top-score realized-return lift. However, fold-level stability remains incomplete, especially in Fold 2. These model results are retained as prior evidence only while the conceptual definitions are being finalized.

## Current rule

Before adding new experiments, first finalize the definitions of:

```text
1. Market Opportunity
2. Current Entry Quality
3. Reference bounds: Baseline and Oracle
4. Model target
```

Do not introduce additional conceptual objects until these four are clear.

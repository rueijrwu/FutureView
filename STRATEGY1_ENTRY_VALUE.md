# Strategy 1 — Entry Quality Framework

This document records the current event-conditioned Strategy 1 research framework. The frozen Strategy 1 mechanics are unchanged.

## Core research question

> Under the fixed Strategy 1 execution rules, can a model provide a useful causal score for whether the current legal Entry1 is a high-quality entry?

The model is not asked to imitate a perfect future pattern and is not trained to predict Oracle directly.

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
- a training target,
- a label,
- a model prediction,
- or an always-on policy benchmark.

It is one side of the profit-quality reference frame.

### 2. Oracle

```text
Oracle_t = future-known best legal Strategy 1 profit available in the same 30D window
```

Oracle describes the best legal profit that could have been achieved with foreknowledge of the future.

Oracle is also **not**:
- a training target,
- a label,
- or a realizable live-trading objective.

It is the upper side of the same profit-quality reference frame.

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

This quantity was previously called OracleRegret in some experiments. In the current conceptual framework, `OpportunityGap` is the clearer name because Baseline and Oracle are reference values, not model decisions.

## Important consequence

A model must not receive Baseline, Oracle, or OpportunityGap as causal inputs or training labels.

They are used only after outcomes are known to characterize the economic quality of an entry and its market context.

The intended scientific question is therefore:

> Can causal market-state information produce a score that separates high-quality current entries, including within market environments that contain similar amounts of future opportunity?

This guards against a trivial model that merely learns "good market ahead" instead of "good entry now."

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

OpportunityGap
  mean ~ +0.86%
```

CNN A remains the strongest tested causal model in the existing 30D / 5y model comparison, with positive mean entry-return ranking and positive top-score realized-return lift. However, fold-level stability remains incomplete, especially in Fold 2. These model results are retained as prior evidence, not treated as final proof under the clarified reference-frame interpretation.

## Next analysis: Baseline–Oracle structure

Before changing horizon, architecture, thresholds, or data length, the next required step is to understand the 30D / 5y reference frame itself.

The canonical analysis is:

```bash
futureview-strategy1-baseline-oracle-30d
```

It reports, with no model involved:

```text
1. Baseline distribution
2. Oracle distribution
3. OpportunityGap distribution
4. Pearson and Spearman relationship between Baseline and Oracle
5. relationship between Baseline and OpportunityGap
6. median-defined Baseline/Oracle quadrants
7. timing-sensitive cases:
     Baseline <= 0
     Oracle > Oracle median
8. Baseline behavior within low/mid/high Oracle opportunity terciles
```

Median splits and Oracle terciles are descriptive only. They are not tuned trading thresholds and are not used for model training.

## Current rule

Until this 30D / 5y Baseline–Oracle structure is understood, do not:

```text
- switch the main horizon to 15D/45D/60D
- expand the main dataset beyond the currently chosen scope
- tune score gates on OOS results
- reinterpret Oracle as the learning target
- reinterpret Baseline as the learning target
```

The next model experiment, if justified by the reference analysis, should test whether CNN A retains entry-quality discrimination **within comparable Oracle-opportunity regimes**, rather than merely across different market-quality regimes.

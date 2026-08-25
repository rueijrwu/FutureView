# Strategy 1 — Current Research Summary

## Status

Current formal research version:

```text
research_version=formal_max2_spacing20
primary_window=60D
robustness_window=90D
distribution_weighting=unique_realized_paths
model_target=not_defined
```

The research framing is now intentionally simple.

We separate two questions:

```text
Symbol   -> determines expected profit opportunity
Strategy -> determines success rate / ability to select profitable paths
```

The immediate goal is not to add more efficiency, regret, capture, or exposure metrics. The primary research outputs are:

```text
Success Rate
Net Expected Return
```

where:

```text
Success Rate       = P(Return > 0)
Net Expected Return = E[Return]
```

Net Expected Return includes both successful profits and failed-path losses and can therefore be negative.

## Research interpretation

For a fixed future window, use three reference levels:

```text
Upper Bound  = absolute success: the best legal Strategy 1 path with full future information
Lower Bound  = random entry: no useful timing/selection information
Fixed DCA    = structured middle baseline: fixed equal entries without timing intelligence
```

Conceptually:

```text
Random Entry  ->  Fixed DCA  ->  Best Legal Path
Lower Bound       Middle          Upper Bound
```

These levels represent increasing selection quality, not three competing trading strategies.

### Upper Bound

Upper Bound answers:

> If future information were perfect and the best legal Strategy 1 path were always selected, what profit opportunity does this symbol provide?

It represents 100% successful path selection inside the Strategy 1 legal space.

### Lower Bound

Lower Bound is the random-entry reference.

It represents entry selection without useful timing information and is the low-information baseline for Strategy success.

The historical implementation also reports the minimum realized legal path return as a distribution extreme. That statistic remains useful for diagnostics, but it is no longer the conceptual Lower Bound used by the research framing.

### Fixed DCA

The fixed-entry comparator is deliberately simple:

```text
60D window
Entry Day 0
Entry Day 20
Entry Day 40
1/3 capital each time
hold all acquired shares to Day 59
```

It is a middle reference: more structured than random entry, but it contains no timing intelligence.

## What is being optimized

The working hypothesis is:

```text
Expected profit is primarily a property of the symbol.
Success rate is primarily what the strategy should improve.
```

A stronger underlying can provide a larger profit opportunity even with a simple fixed-entry rule. Strategy 1 should therefore not be judged mainly by whether it produces the highest raw return across different symbols.

Instead, within the same symbol, the important question is:

> Can Strategy 1 move success probability away from random entry and toward the Upper Bound?

The ideal research outcome is therefore:

```text
high Net Expected Return symbol
+
high Success Rate strategy
```

## Current Strategy 1 mechanics

### Entry Set

A formal Entry candidate is every session satisfying:

```text
Close > MA5
Close > MA10
Close > MA20
MA5 > MA10
MA10 > MA20
```

This is not limited to the first newly-true transition. Legacy `entry1_event` remains unchanged for older experiments.

### Addition Set

A confirmed local maximum at session `i` is:

```text
Close[i] > Close[i-1]
Close[i] >= Close[i+1]
```

Legal addition-reference configurations are:

```text
no addon
one local-max reference
two local-max references with index gap > 5
```

Formal Addon2 requires positive approximately equal realized price steps:

```text
first_gap  = Addon1Price - EntryPrice
second_gap = Addon2Price - Addon1Price

first_gap > 0
second_gap > 0
abs(second_gap / first_gap - 1) <= 0.20
```

### Exit execution

Execution remains deterministic under existing Strategy 1 mechanics:

```text
eligible MA10 full exit
> eligible MA5 half exit
> addon action
```

The three-session trading cooldown and horizon-end liquidation remain unchanged.

## Primary window

```text
30D  supporting
45D  supporting
60D  primary
90D  robustness
```

60D remains the primary comparison window.

## Cross-symbol 60D results

Five-year daily samples ending 2026-08-25. Strategy values below are the best legal Strategy 1 path per window; Fixed values use Day 0 / 20 / 40 equal entries.

| Symbol | Strategy Success Rate | Strategy Net Expected Return | Fixed DCA Success Rate | Fixed DCA Net Expected Return |
|---|---:|---:|---:|---:|
| SPY | 92.1% | +1.34% | 72.2% | +1.86% |
| QQQ | 89.8% | +2.09% | 67.4% | +2.43% |
| SMH | 81.7% | +3.72% | 67.5% | +5.73% |

### Current interpretation

The symbols show a clear profit-opportunity gradient:

```text
SPY -> lower expected profit opportunity
QQQ -> medium expected profit opportunity
SMH -> higher expected profit opportunity
```

At the same time, Strategy 1 produces a much higher positive-return frequency than the fixed-entry baseline on all three symbols:

```text
SPY: 72.2% -> 92.1%
QQQ: 67.4% -> 89.8%
SMH: 67.5% -> 81.7%
```

This supports the current decomposition:

```text
symbol choice drives how much profit is available
strategy quality drives how reliably profitable paths are selected
```

The fact that Fixed DCA can have higher average return than the Strategy Upper result does not invalidate this framing. Fixed DCA is outside the legal Strategy 1 path space and can benefit strongly from the positive drift of the underlying.

## Research direction

Do not add more primary metrics unless they answer a concrete unresolved question.

The next stage should stay focused on:

1. estimating the random-entry Lower Bound consistently for each symbol;
2. comparing Random Entry, Fixed DCA, and Upper Bound on the same 60D windows;
3. evaluating future strategy/model candidates mainly by how much they improve Success Rate toward the Upper Bound while preserving positive Net Expected Return.

Do not define a model target until this three-level success framework is operationally measured.

## Active data and runners

Market data access is symbol-agnostic:

```text
download_ticker_daily(symbol, ...)
FUTUREVIEW_TICKER=<symbol>
```

Current CI matrix:

```text
SPY
QQQ
SMH
```

Active commands:

```bash
futureview-strategy1-reference-distribution
futureview-strategy1-reference-distribution-fast
futureview-strategy1-fixed-entry-compare
```

Legacy Strategy 1 architecture and event definitions remain untouched unless explicitly changed by a separate experiment.

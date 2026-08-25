# Strategy 1 — Current Research Summary

## Status

Current formal research version:

```text
research_version=formal_max2_spacing20
primary_window=60D
robustness_window=90D
distribution_weighting=unique_realized_paths
model_target=entry_success_probability
```

The research framing is intentionally simple:

```text
Symbol   -> determines expected profit opportunity
Strategy -> determines success rate / ability to select profitable paths
```

Primary evaluation outputs:

```text
Success Rate        = P(Return > 0)
Net Expected Return = E[Return]
```

`Net Expected Return` includes both profitable and losing outcomes and can be negative.

## Reference levels

For each fixed future window, the existing formal Strategy 1 legal path space defines the two bounds:

```text
Lower Bound = minimum return across all formal legal realized paths
Upper Bound = maximum return across all formal legal realized paths
```

The fixed-entry comparator is:

```text
Fixed DCA = Day 0 / Day 20 / Day 40 equal entries, hold to Day 59
```

Conceptually:

```text
Lower Bound  ->  Fixed DCA  ->  Upper Bound
worst legal      simple          best legal
selection        schedule        selection
```

This ordering is a research interpretation of selection quality, not a requirement that the realized numeric return of DCA must always lie between the two Strategy 1 bounds. Fixed DCA is outside the formal Strategy 1 legal-path space.

### Upper Bound

Upper Bound is the perfect-information best legal Strategy 1 path in the window:

```text
UpperBound(W) = max(Return(path))
```

It is the absolute best selection available under the current Strategy 1 rules. It is not mathematically guaranteed to be positive when every legal path in a window loses money.

### Lower Bound

Lower Bound is the worst formal legal Strategy 1 path in the same window:

```text
LowerBound(W) = min(Return(path))
```

This is the previously computed formal Lower Bound. It is deliberately more relevant than a true random-trading-day entry baseline because it stays inside the same Strategy 1 Entry Set and legal execution space.

### Fixed DCA

The middle reference uses no timing intelligence:

```text
60D window
Entry Day 0
Entry Day 20
Entry Day 40
1/3 capital each time
hold all acquired shares to Day 59
```

It provides a simple scheduled-investment reference for the same symbol and horizon.

## What is being optimized

Working decomposition:

```text
Expected profit is primarily a property of the symbol.
Success rate is primarily what the strategy/model should improve.
```

Therefore model training should not primarily ask the model to predict the largest raw return across different symbols. The learning problem is to identify Entry candidates that are more likely to produce profitable legal Strategy 1 outcomes.

The desired combination is:

```text
high Net Expected Return symbol
+
high Success Rate strategy/model
```

## Model target

### Unit of prediction

One training example is one formal Strategy 1 `Entry candidate` at session `e` in a 60D future window.

The model only receives features observable at or before `e`. No future-derived bound, future return, future local maximum, future exit, or target statistic may be used as an input feature.

### Legal path set for one Entry

Let:

```text
P(e, W) = all unique formal legal realized Strategy 1 paths
          that begin at Entry candidate e inside window W
```

The path set uses the current formal rules:

```text
max_addons=2
addon2_spacing_tolerance=0.20
distribution_weighting=unique_realized_paths
existing deterministic exit execution
```

### Primary target: Entry Success Probability

For every Entry candidate:

```text
EntrySuccessProbability(e, W)
    = number of paths p in P(e,W) with Return(p) > 0
      ------------------------------------------------
      number of unique realized paths in P(e,W)
```

Equivalent:

```text
target_success_probability = mean(Return(path) > 0)
```

Range:

```text
0.0 = every legal realized path from this Entry loses
1.0 = every legal realized path from this Entry profits
```

This is the primary model target.

Why this target:

```text
1. It directly represents the quantity the strategy is supposed to improve: success probability.
2. It does not force the model to explain cross-symbol raw-return magnitude.
3. It uses the already-computed formal legal path set rather than inventing a true-random baseline.
4. It is a soft target, so two positive Entry candidates can still differ in reliability.
5. It preserves all legal-path outcomes instead of labeling only the single hindsight-best path.
```

### Secondary label: Entry Net Expected Return

For diagnostics, compute but do not make the primary learning objective:

```text
EntryNetExpectedReturn(e, W)
    = mean(Return(path) for path in P(e,W))
```

This includes losses and may be negative.

It answers a different question from success probability:

```text
EntrySuccessProbability -> how reliably this Entry produces profit
EntryNetExpectedReturn  -> average economic result of this Entry's legal paths
```

Because raw return magnitude is strongly symbol-dependent, `EntryNetExpectedReturn` is a secondary label/evaluation value rather than the primary target.

### Entry-specific bounds

Also retain:

```text
EntryLower(e,W) = min(Return(path) for path in P(e,W))
EntryUpper(e,W) = max(Return(path) for path in P(e,W))
```

These are future labels/audit values only. They are not model features and are not the primary target.

The window-level formal bounds remain:

```text
LowerBound(W) = min over all legal realized paths in W
UpperBound(W) = max over all legal realized paths in W
```

## Training protocol

The model predicts:

```text
p_hat = predicted EntrySuccessProbability
```

Higher `p_hat` means the model believes the current Entry candidate is more reliable.

Training and validation must be chronological / walk-forward. Do not use random train/test splits.

The selection threshold for `p_hat` must be chosen only on training/validation history, never on the future test segment.

A minimum number of selected entries must be required during evaluation so that success rate cannot be made artificially high by selecting only a trivial number of cases. This is an evaluation guardrail, not a new primary KPI.

## Model evaluation

The two primary out-of-sample results remain:

```text
Success Rate        = profitable selected realized outcomes / selected outcomes
Net Expected Return = mean realized return of selected outcomes
```

The model is useful when, on the same symbol and same chronological test period, it increases Success Rate while keeping Net Expected Return positive.

Reference comparisons remain:

```text
formal Lower Bound
Fixed DCA
formal Upper Bound
```

The Upper Bound is the perfect-information ceiling. The trained model is not expected to reproduce hindsight; it is evaluated by how much reliable profitable selection it can recover using only information available at decision time.

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

60D remains the primary training/reference horizon.

## Current cross-symbol 60D reference results

Five-year daily samples ending 2026-08-25. The Strategy values below are the formal best legal path per 60D window; Fixed values use Day 0 / 20 / 40 equal entries.

| Symbol | Upper-path Success Rate | Upper-path Net Expected Return | Fixed DCA Success Rate | Fixed DCA Net Expected Return |
|---|---:|---:|---:|---:|
| SPY | 92.1% | +1.34% | 72.2% | +1.86% |
| QQQ | 89.8% | +2.09% | 67.4% | +2.43% |
| SMH | 81.7% | +3.72% | 67.5% | +5.73% |

Current interpretation:

```text
SPY -> lower profit opportunity, higher best-path success frequency
QQQ -> middle
SMH -> higher profit opportunity, lower best-path success frequency
```

This supports the working split:

```text
symbol choice -> profit magnitude
strategy/model -> success reliability
```

## Next implementation step

Generate one supervised row per formal Entry candidate with at least:

```text
symbol
date
window
observable_features_at_entry
target_success_probability
entry_net_expected_return
entry_lower
entry_upper
legal_realized_path_count
```

Then train the first model to predict `target_success_probability` using chronological splits only.

Do not revive RuleReturn, OracleRegret, random-entry targets, or random train/test splits as the primary learning target.

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

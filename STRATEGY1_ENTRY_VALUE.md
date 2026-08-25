# Strategy 1 — Current Research Summary

## Status

```text
research_version=formal_max2_spacing20
primary_window=60D
robustness_window=90D
distribution_weighting=unique_realized_paths
model_target=entry_success_probability
first_training_symbol=QQQ
```

Research framing:

```text
Symbol   -> primarily determines expected profit opportunity
Strategy -> primarily determines success rate / profitable-path selection
```

Primary outputs:

```text
Success Rate        = P(Return > 0)
Net Expected Return = E[Return]
```

`Net Expected Return` includes losing outcomes and may be negative.

## Reference levels

For a fixed formal Strategy 1 window:

```text
Lower Bound = minimum return across formal legal realized paths
Upper Bound = maximum return across formal legal realized paths
Fixed DCA   = Day 0 / 20 / 40 equal entries, hold to Day 59
```

Conceptually:

```text
Lower Bound  ->  Fixed DCA  ->  Upper Bound
worst legal      simple          best legal
selection        schedule        selection
```

Fixed DCA is outside the formal Strategy 1 path space, so its realized return is not mathematically required to lie between the two formal bounds.

True random-trading-day Entry is not used as the Lower Bound. The existing formal minimum legal path is the research Lower Bound because it stays inside the same Entry Set and execution space.

## Current Strategy 1 rules

### Entry Set

Every session satisfying:

```text
Close > MA5
Close > MA10
Close > MA20
MA5 > MA10
MA10 > MA20
```

All qualifying sessions are Entry candidates. Legacy `entry1_event` remains untouched for older experiments.

### Addition Set

Confirmed local maximum at `i`:

```text
Close[i] > Close[i-1]
Close[i] >= Close[i+1]
```

Legal addon-reference configurations:

```text
no addon
one local-max reference
two local-max references with index gap > 5
```

Formal Addon2 requires:

```text
first_gap  = Addon1Price - EntryPrice
second_gap = Addon2Price - Addon1Price
first_gap > 0
second_gap > 0
abs(second_gap / first_gap - 1) <= 0.20
```

Execution remains deterministic:

```text
eligible MA10 full exit
> eligible MA5 half exit
> addon action
```

Three-session cooldown and horizon-end liquidation remain unchanged.

## Model target

### Unit of prediction

One supervised sample is one formal `entry_candidate` at session `e`.

The first model uses:

```text
symbol=QQQ
history=5y
future_horizon=60 sessions
input_lookback=50 sessions
addon_reference_lookback=60 sessions
```

The addon reference set is constructed only from local maxima observable before Entry. The model input ends on the Entry close.

No future return, future bound, future exit, future local maximum, or target statistic is allowed as an input feature.

### Primary target: Entry Success Probability

Let `P(e,60)` be all unique formal legal realized paths beginning at Entry `e`, using the current max2/spacing20 rules.

```text
EntrySuccessProbability(e,60)
    = count(Return(path) > 0) / count(unique legal realized paths)
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

This is a soft probability target. It is the primary learning objective because the model is intended to improve selection reliability rather than explain cross-symbol raw-return magnitude.

### Secondary labels

For every Entry candidate also retain:

```text
EntryNetExpectedReturn = mean(Return(path))
EntryLower             = min(Return(path))
EntryUpper             = max(Return(path))
LegalRealizedPathCount = number of unique realized paths
```

These are evaluation/audit labels, not model input features.

## QQQ first model

The first learning experiment is intentionally single-symbol:

```text
QQQ only
5 years maximum data
50-session causal OHLCV feature tensor
60-session future target horizon
formal max2 + spacing20 path semantics
unique-realized-path weighting
```

Architecture:

```text
EntrySuccessCNN
multi-scale 1D CNN kernels = 5 / 10 / 20
input channels = causal O/H/L/C/V features
output = one sigmoid probability
loss = binary cross entropy with soft target EntrySuccessProbability
```

The model does not train on raw return as the primary target.

### Training split

```text
chronological expanding folds only
purge = 60 raw trading sessions
no random train/test split
3 fixed seeds
```

The purge is measured in raw sessions so labels from a training Entry cannot overlap the future test period.

### OOS evaluation

Primary model-learning check:

```text
Does predicted top-20% Entry selection have higher realized
EntrySuccessProbability than all Entry candidates in the same OOS fold?
```

Reported model diagnostics:

```text
Spearman(prediction, target_success_probability)
MAE
Brier score
all-entry success probability
top-20% success probability
top-20% success lift
all-entry Net Expected Return
top-20% Net Expected Return
```

The main requirement is higher OOS Success Rate while Net Expected Return remains positive. Extra diagnostics are supporting evidence, not new primary research objectives.

## Current cross-symbol 60D reference results

Five-year daily samples ending 2026-08-25:

| Symbol | Upper-path Success Rate | Upper-path Net Expected Return | Fixed DCA Success Rate | Fixed DCA Net Expected Return |
|---|---:|---:|---:|---:|
| SPY | 92.1% | +1.34% | 72.2% | +1.86% |
| QQQ | 89.8% | +2.09% | 67.4% | +2.43% |
| SMH | 81.7% | +3.72% | 67.5% | +5.73% |

Working interpretation:

```text
symbol choice -> profit magnitude
strategy/model -> success reliability
```

QQQ is the first training symbol because it provides a middle case between SPY and SMH while keeping the first supervised experiment simple.

## Active commands

```bash
futureview-strategy1-reference-distribution
futureview-strategy1-reference-distribution-fast
futureview-strategy1-fixed-entry-compare
futureview-strategy1-success-model
```

The QQQ training workflow is:

```text
.github/workflows/strategy1-qqq-success-model.yml
```

Legacy Strategy 1 architecture and historical targets remain untouched unless explicitly changed by a separate experiment.

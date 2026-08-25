# Strategy 1 — Research Objective and Current Definition

## 1. Original objective

The project goal is not to optimize a trading gate, threshold, or portfolio scheduler.

The core research question is:

```text
Can a model identify better Strategy 1 Entry candidates
and thereby increase Success Rate,
while preserving positive Net Expected Return?
```

The intended decomposition is:

```text
Symbol   -> primarily determines profit opportunity / return magnitude
Strategy -> defines the legal trading process
Model    -> primarily improves Entry selection reliability / Success Rate
```

Primary outputs remain:

```text
Success Rate        = P(Return > 0)
Net Expected Return = E[Return]
```

`Net Expected Return` includes losses and may be negative.

This framing is the main line of research. Threshold engineering, adaptive gates, delayed-entry windows, portfolio state machines, and capital-efficiency studies are secondary implementation diagnostics only.

### Decision frequency is not a primary objective

A low number of model-selected Entries is not automatically a negative result.

It can mean:

```text
The current observable information is insufficient for the model
to distinguish a high-reliability Entry from the rest.
```

In that case, not making a strong decision can be appropriate behavior.

Therefore:

```text
low decision frequency != model failure
high decision frequency != model success
```

The model should be judged first by whether its score contains stable information about Entry quality. Coverage/frequency is a later deployment property.

The research must distinguish:

```text
model information quality
from
execution frequency
```

A model that only becomes decisive in a small number of information-rich regimes can still be useful if those decisions are reliably better than the underlying Strategy 1 Entry set.

## 2. Reference framework

For a fixed formal Strategy 1 future window:

```text
Lower Bound = minimum return across all formal legal realized Strategy 1 paths
Upper Bound = maximum return across all formal legal realized Strategy 1 paths
Fixed DCA   = Day 0 / 20 / 40 equal entries, hold to Day 59
```

Conceptually:

```text
Lower Bound  ->  Fixed DCA  ->  Upper Bound
worst legal      simple          best legal
selection        schedule        selection
```

Formal definitions:

```text
LowerBound(W) = min(all legal realized Strategy 1 path returns in W)
UpperBound(W) = max(all legal realized Strategy 1 path returns in W)
```

Lower and Upper come from the same formal Strategy 1 path space.

Fixed DCA is outside that path space, so its realized return is not mathematically required to lie between the two bounds.

True Random Entry is not used. It is too uninformative for the current objective and does not represent the intended Lower Bound.

## 3. What the model is supposed to learn

### Unit of prediction

One supervised sample is one formal `entry_candidate` at session `e`.

The model should answer:

```text
Given only information observable at Entry e,
how reliable is this Entry under the formal Strategy 1 path space?
```

The model is not primarily asked to predict the maximum future return, the Upper Bound, or the best future path.

### Primary target: Entry Success Probability

Let `P(e,60)` be all unique formal legal realized paths beginning from Entry `e` under the current Strategy 1 rules.

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

This is the primary learning target because it directly measures Entry reliability.

### Secondary labels

Retain for audit and evaluation:

```text
EntryNetExpectedReturn = mean(Return(path))
EntryLower             = min(Return(path))
EntryUpper             = max(Return(path))
LegalRealizedPathCount = number of unique realized paths
```

These are not model input features and are not the primary target.

## 4. Causality requirements

For every Entry candidate, model features must be observable at or before Entry.

Current first-model setup:

```text
symbol=QQQ
history<=5y
input_lookback=50 sessions
future_target_horizon=60 sessions
addon_reference_lookback=60 prior sessions
```

Allowed inputs are causal OHLCV-derived features only.

Forbidden as input features:

```text
future return
future Lower / Upper labels
future exit
future local maximum
future target statistic
future test score distribution
```

Training and evaluation must remain chronological / walk-forward.

```text
no random train/test split
purge future-label overlap
no future test labels in threshold or selection logic
```

## 5. Current formal Strategy 1 rules

### Entry Set

Every session satisfying:

```text
Close > MA5
Close > MA10
Close > MA20
MA5 > MA10
MA10 > MA20
```

All qualifying sessions are formal Entry candidates.

Legacy `entry1_event` remains untouched for compatibility with older experiments.

### Addition Set

Confirmed local maximum at `i`:

```text
Close[i] > Close[i-1]
Close[i] >= Close[i+1]
```

Legal reference configurations:

```text
no addon
one local-max reference
two local-max references with index gap > 5
```

Formal Addon2 requires approximately equal realized price spacing:

```text
first_gap  = Addon1Price - EntryPrice
second_gap = Addon2Price - Addon1Price
first_gap > 0
second_gap > 0
abs(second_gap / first_gap - 1) <= 0.20
```

### Execution

Three equal capital tranches are retained.

Execution priority remains:

```text
eligible MA10 full exit
> eligible MA5 half exit
> addon action
```

Three-session cooldown and horizon-end liquidation remain unchanged.

## 6. First model: QQQ Entry Success CNN

The first supervised experiment is intentionally single-symbol.

```text
QQQ only
5 years maximum data
50-session causal OHLCV tensor
60-session target horizon
formal max2 + spacing20 path semantics
unique-realized-path weighting
```

Architecture:

```text
EntrySuccessCNN
multi-scale 1D CNN kernels = 5 / 10 / 20
input channels = causal O/H/L/C/V features
output = one sigmoid probability
loss = BCE with soft EntrySuccessProbability target
```

The model does not train on raw return as its primary objective.

Training protocol:

```text
chronological expanding / walk-forward folds
60 raw-session purge
3 fixed seeds
no random split
```

## 7. What has been learned so far

### Model-learning evidence

The QQQ CNN showed that higher predicted Entry scores can identify a subset with better realized Entry quality than the full eligible set.

Earlier OOS candidate-level experiments showed positive top-selection lift, and deterministic Strategy 1 execution also showed improvement when model-selected Entries were compared with all eligible Entries.

This supports the hypothesis that the model contains useful Entry-selection information.

### Expanded OOS comparison

A later expanded walk-forward comparison used the same Strategy 1 execution on both sides:

```text
Ungated baseline:
    every formal Entry candidate can become a setup signal

Q55 diagnostic gate:
    model-selected subset only
```

Observed expanded OOS results:

| Metric | Ungated Strategy 1 | Q55-selected subset |
|---|---:|---:|
| Campaign count | 14 | 5 unique paths |
| Success Rate | 42.86% | 60.00% |
| Avg Campaign Return | +0.3526% | +0.9683% |

Diagnostic lift:

```text
Success Rate lift        = +17.14 percentage points
Net Expected Return lift = +0.6157 percentage points per campaign
```

This is evidence that the model can add Entry-selection value.

It is not evidence that Q55 is the final policy, and the smaller campaign count should not by itself be interpreted as a defect. The model may simply be more selective when observable information is weak.

## 8. Important correction to research direction

Recent work explored:

```text
fixed percentile thresholds
adaptive rolling thresholds
hybrid floors
Q50/Q55/Q60/Q65 sweeps
+3-session delayed entry
single non-overlapping live campaigns
expanded chronological OOS blocks
ungated portfolio baseline comparison
```

These experiments were useful for learning about score calibration and live execution constraints, but they are not the primary research objective.

They should be treated as diagnostics around the model, not as the thing being optimized.

In particular:

```text
Q55 is not a new research target.
Q55 is not a final deployable threshold.
100% historical Success Rate from sparse folds is not a target.
Maximizing trading frequency is not the current target.
Capital efficiency is not the current target.
```

The project should not drift into repeatedly tuning the gate against the same OOS history.

## 9. Current interpretation

The intended research decomposition remains:

```text
Symbol choice
    -> primarily controls available return opportunity / magnitude

Strategy 1 mechanics
    -> define the legal realization process

Model Entry selection
    -> should improve Success Rate / reliability
```

Ideal end state:

```text
high-opportunity symbol
+
Entry-selection model with stable OOS Success Rate lift
+
positive Net Expected Return
```

The model does not need to maximize raw return across symbols to be useful.

The model also does not need to make a decision on every Entry candidate. A valid model behavior is to remain non-committal when the available causal information does not support a strong distinction.

## 10. Next research priority

The next step returns directly to model quality:

```text
Across chronological OOS regimes, does a higher model score
correspond to higher EntrySuccessProbability and higher realized Entry quality?
```

This is evaluated without choosing a deployment threshold.

Priority order:

1. Keep Strategy 1 mechanics fixed.
2. Keep `EntrySuccessProbability` as the primary model target.
3. Keep QQQ as the first controlled symbol until model behavior is understood.
4. Evaluate the full OOS score distribution, not only selected trades.
5. Check whether Entry quality rises from low-score to high-score rank buckets.
6. Check stability across chronological regimes and seeds.
7. Use Net Expected Return as a secondary economic check.
8. Treat low model decisiveness as potentially meaningful abstention, not automatically poor coverage.
9. Only after stable score-quality structure is established should deployment-specific gate/frequency optimization resume.

A useful model result is therefore not:

```text
"Q55 made 5 good campaigns."
```

It is:

```text
"Across chronological OOS regimes, higher model scores consistently map to
higher EntrySuccessProbability and better realized Entry outcomes."
```

That is the original target.

## 11. Current cross-symbol 60D reference context

Five-year daily samples ending 2026-08-25:

| Symbol | Upper-path Success Rate | Upper-path Net Expected Return | Fixed DCA Success Rate | Fixed DCA Net Expected Return |
|---|---:|---:|---:|---:|
| SPY | 92.1% | +1.34% | 72.2% | +1.86% |
| QQQ | 89.8% | +2.09% | 67.4% | +2.43% |
| SMH | 81.7% | +3.72% | 67.5% | +5.73% |

Working interpretation remains:

```text
symbol choice -> profit magnitude / opportunity
strategy/model -> success reliability
```

These cross-symbol numbers are reference context, not a reason to change the current QQQ learning objective.

## 12. Active research commands

Core research:

```bash
futureview-strategy1-reference-distribution
futureview-strategy1-reference-distribution-fast
futureview-strategy1-fixed-entry-compare
futureview-strategy1-success-model
futureview-strategy1-success-model-oos-diagnostics
```

Later gate / portfolio diagnostic commands remain available but are secondary to the core objective.

Legacy Strategy 1 architecture and historical targets remain untouched unless explicitly changed by a separate experiment.

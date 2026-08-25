# Strategy 1 — Research Objective and Current Definition

## 1. Research objective

The project goal is not to optimize a trading gate, threshold, or portfolio scheduler.

The smallest current research question is:

```text
Given only information observable at a formal Strategy 1 Entry,
can a model predict how robustly profitable the legal Strategy 1 outcomes
from that Entry will be over the fixed future horizon?
```

The working decomposition is:

```text
Symbol   -> influences the realized opportunity / outcome distribution
Strategy -> defines the legal trading process and legal path space
Model    -> estimates characteristics of that future legal-path distribution
Planning -> later converts model estimates into trade / no-trade / sizing decisions
```

This decomposition is a research framework, not a claim that symbol, strategy, and model effects are perfectly separable.

The first model question should remain deliberately small. Threshold engineering, adaptive gates, delayed-entry windows, portfolio state machines, trade frequency, capital efficiency, and position sizing are downstream planning questions.

### Decision frequency is not a primary objective

A low number of model-selected Entries is not automatically a negative result. It can mean that current observable information is insufficient for a high-confidence estimate.

```text
low decision frequency != model failure
high decision frequency != model success
```

Coverage/frequency should be evaluated later, after the quality of the model estimate is established.

---

## 2. Realized Strategy bounds

For one fixed future window `W`, define the formal Strategy 1 legal realized-path set:

```text
S(W) = all unique legal realized Strategy 1 paths available in window W
```

Every path in `S(W)` obeys the same frozen Strategy 1 mechanics.

### Realized Strategy Lower Bound

```text
RealizedStrategyLowerBound(W)
= min(Return(p)) for p in S(W)
```

Interpretation:

```text
The worst legal realized Strategy 1 outcome available in that realized window.
```

### Realized Strategy Upper Bound

```text
RealizedStrategyUpperBound(W)
= max(Return(p)) for p in S(W)
```

Interpretation:

```text
The best legal realized Strategy 1 outcome available in that realized window,
assuming perfect hindsight over the legal path set.
```

For compatibility, the shorter names `LowerBound` and `UpperBound` may still be used in code and historical experiment output. In research discussion, `Realized Strategy Lower/Upper Bound` is preferred because these quantities are not theoretical market bounds, model prediction intervals, or claims about achievable live return.

Upper Bound is a hindsight reference ceiling. The model is not expected to reproduce or achieve it.

### Important boundary rule

Both bounds must always come from the same formal Strategy 1 legal path space:

```text
Lower Bound = worst legal Strategy 1 path
Upper Bound = best legal Strategy 1 path
```

Do not redefine Lower Bound as Random Entry, DCA, or another unrelated baseline.

### Strategy Outcome Dispersion / Path-Selection Spread

Define:

```text
StrategyOutcomeDispersion(W)
= UpperBound(W) - LowerBound(W)
```

This measures the realized spread between the best and worst legal Strategy 1 outcomes in the same window.

A large spread means that legal Strategy 1 path selection mattered substantially in that realized window. A small spread means legal paths produced more similar outcomes.

Important:

```text
large StrategyOutcomeDispersion != market volatility by definition
```

Volatility may contribute to a wider spread, but the spread also depends on Strategy 1 entry/add/exit mechanics and the realized price path. Whether higher-volatility symbols systematically produce wider Strategy 1 outcome dispersion is an empirical hypothesis to test, not part of the definition.

---

## 3. DCA reference

Current fixed DCA comparator:

```text
Day 0 / Day 20 / Day 40
three equal entries
hold to Day 59
```

DCA is a simple external comparator. It is outside the formal Strategy 1 path set `S(W)` and therefore is not mathematically required to lie between the Strategy 1 Lower and Upper bounds.

It should not be used to define either bound.

---

## 4. Entry-level legal-path distribution

For one formal Entry candidate `e`, define:

```text
P(e,60)
= all unique legal realized Strategy 1 paths beginning from Entry e
  over the 60-session horizon
```

For this path set, retain four conceptually separate outcome descriptors.

### 4.1 Entry Path Profitability Rate

```text
EntryPathProfitabilityRate(e,60)
= count(Return(path) > 0) / count(P(e,60))
```

Equivalent legacy target name:

```text
target_success_probability
= mean(Return(path) > 0)
```

Interpretation:

```text
Given this Entry and the realized future market path,
what fraction of the legal Strategy 1 decision paths finish profitable?
```

Examples:

```text
0.00 -> every legal path from this Entry loses
0.50 -> half of the legal paths profit
1.00 -> every legal path from this Entry profits
```

This quantity measures realized entry robustness across legal Strategy 1 paths.

It should not be casually interpreted as the unconditional probability that the future market rises or as a conventional stochastic probability over multiple possible future market paths. For one historical sample, the future market path is already realized; the fraction is taken over the legal Strategy 1 decision paths available on that realized future.

`EntrySuccessProbability` remains a legacy code/output name for compatibility, but `EntryPathProfitabilityRate` is the preferred research term.

### 4.2 Entry Net Expected Return across legal paths

```text
EntryNetExpectedReturn(e,60)
= mean(Return(path)) for path in P(e,60)
```

This includes losing paths and may be negative.

It measures the average realized result across the legal Strategy 1 path set and must remain separate from profitability rate.

### 4.3 Entry Lower and Upper

```text
EntryLower(e,60) = min(Return(path))
EntryUpper(e,60) = max(Return(path))
```

These describe the downside and upside extrema of the realized legal-path distribution from the Entry.

Together, the preferred entry-level description is:

```text
Q  = EntryPathProfitabilityRate
mu = EntryNetExpectedReturn
L  = EntryLower
U  = EntryUpper
```

They answer different questions:

```text
L  -> how bad was the worst legal execution?
U  -> how large was the best legal opportunity?
Q  -> how robustly profitable were the legal executions?
mu -> what was the average legal-path outcome?
```

No single one of these quantities should automatically be treated as a complete definition of a good Entry.

---

## 5. Window-level reference rates

When evaluating a specific realized reference rule across many windows, the observation unit is the window, not the individual legal path.

### 5.1 Profitable-Opportunity Rate

Preferred name:

```text
ProfitableOpportunityRate
= count(UpperBound(W) > 0) / count(valid windows)
```

Historical output may call this `Upper-path Success Rate` or `UpperBoundSuccessRate`.

Interpretation:

```text
In what fraction of evaluation windows did at least one legal Strategy 1 path make money?
```

It does not mean that this fraction of all legal paths was profitable, and it is not a model-achievable live win rate.

### 5.2 Robust-Profit Window Rate

Preferred name:

```text
RobustProfitWindowRate
= count(LowerBound(W) > 0) / count(valid windows)
```

Historical output may call this `LowerBoundSuccessRate`.

Interpretation:

```text
In what fraction of evaluation windows was even the worst legal Strategy 1 path profitable?
```

For the same valid windows and formal path space:

```text
RobustProfitWindowRate <= ProfitableOpportunityRate
```

A large difference between these rates means profitable opportunity often existed, but profitability was sensitive to legal path selection. A small high-level difference means many windows were robustly favorable. A small low-level difference means the windows generally offered poor Strategy 1 opportunity.

---

## 6. SPY / QQQ / SMH reference examples

Five-year daily reference samples ending 2026-08-25, using the current 60D formal Strategy 1 research definition:

| Symbol | Profitable-Opportunity Rate | Mean Upper Return | Fixed DCA Success Rate | Fixed DCA Net Expected Return | Mean Lower Return |
|---|---:|---:|---:|---:|---:|
| SPY | 92.1% | +1.34% | 72.2% | +1.86% | -1.95% |
| QQQ | 89.8% | +2.09% | 67.4% | +2.43% | -2.30% |
| SMH | 81.7% | +3.72% | 67.5% | +5.73% | -3.89% |

These observations show why opportunity frequency, return magnitude, downside, and path robustness should remain separate.

A neutral description of the current sample is:

```text
From SPY -> QQQ -> SMH,
the observed mean best-path return increases,
the observed mean worst-path return becomes more negative,
and the fraction of windows containing at least one profitable legal path decreases.
```

This is an empirical observation under the current sample and Strategy 1 definition. It should not yet be generalized into a universal claim that SPY is intrinsically safer or that higher-volatility symbols necessarily have wider Strategy 1 bounds.

### SPY

```text
Profitable-Opportunity Rate = 92.1%
Mean Upper Return           = +1.34%
DCA Success Rate            = 72.2%
DCA Net Return              = +1.86%
Mean Lower Return           = -1.95%
```

SPY had a high frequency of windows containing at least one profitable legal Strategy 1 path, while the observed best-path return magnitude was smaller than QQQ and SMH.

### QQQ

```text
Profitable-Opportunity Rate = 89.8%
Mean Upper Return           = +2.09%
DCA Success Rate            = 67.4%
DCA Net Return              = +2.43%
Mean Lower Return           = -2.30%
```

QQQ retained a high frequency of profitable opportunity while showing greater best-path return magnitude and a somewhat more negative mean Lower Bound than SPY in this sample.

### SMH

```text
Profitable-Opportunity Rate = 81.7%
Mean Upper Return           = +3.72%
DCA Success Rate            = 67.5%
DCA Net Return              = +5.73%
Mean Lower Return           = -3.89%
```

SMH showed the largest best-path return magnitude and the most negative mean Lower Bound of the three examples, together with a lower Profitable-Opportunity Rate.

These three symbols provide useful contrasting cases, but they are not sufficient by themselves to establish a general relationship between symbol volatility and Strategy Outcome Dispersion.

---

## 7. Current formal Strategy 1 rules

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

---

## 8. Current model target

One supervised sample is one formal `entry_candidate` at session `e`.

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

### Primary first-stage target

The current soft target remains code-compatible with existing experiments:

```text
target_success_probability
```

but its preferred research interpretation is:

```text
Q(e) = EntryPathProfitabilityRate(e,60)
```

The immediate model question is therefore:

```text
Can causal information observable at Entry e predict
how robustly profitable the realized legal Strategy 1 path set from e will be?
```

Secondary audit labels remain:

```text
EntryNetExpectedReturn = mean(Return(path))
EntryLower             = min(Return(path))
EntryUpper             = max(Return(path))
LegalRealizedPathCount = number of unique realized paths
```

Training and evaluation remain chronological / walk-forward:

```text
no random train/test split
purge future-label overlap
```

---

## 9. First model: QQQ Entry Robustness CNN

Current architecture:

```text
EntrySuccessCNN  # legacy implementation name
multi-scale 1D CNN kernels = 5 / 10 / 20
input channels = causal O/H/L/C/V features
output = one sigmoid estimate of Q(e)
loss = BCE with soft EntryPathProfitabilityRate target
```

The model does not train on raw return as its primary objective.

Training protocol:

```text
chronological expanding / walk-forward folds
60 raw-session purge
3 fixed seeds
no random split
```

The current model is research-grade. Existing OOS diagnostics should not be interpreted as establishing a calibrated probability of future market states. The first task is to establish whether the model can predict the realized entry-level path-profitability/robustness target out of sample.

---

## 10. Research sequence

The project should continue to ask small questions in sequence.

### Stage 1 — Entry robustness

```text
Can the model predict Q(e),
the Entry Path Profitability Rate?
```

Evaluation should test OOS ranking, calibration/error against the soft target, temporal stability, and stability across seeds/regimes.

### Stage 2 — Economic value

If Stage 1 is credible, ask separately whether the same causal information predicts:

```text
mu(e) = EntryNetExpectedReturn
L(e)  = EntryLower
U(e)  = EntryUpper
```

This separates robustness from payoff magnitude and downside/upside extrema.

### Stage 3 — Planning

Only after the predictive quantities are credible should a planning layer consider:

```text
trade / no trade
threshold
position sizing
capital allocation
portfolio overlap
trade frequency
capital efficiency
```

Do not optimize these yet:

```text
Q55
adaptive gate
trade frequency
portfolio overlap
capital efficiency
position sizing
symbol allocation
```

Upper Bound should remain a hindsight opportunity reference, not a direct model-performance target.

---

## 11. Active research commands

Core research:

```bash
futureview-strategy1-reference-distribution
futureview-strategy1-reference-distribution-fast
futureview-strategy1-fixed-entry-compare
futureview-strategy1-success-model
futureview-strategy1-success-model-oos-diagnostics
```

Later gate / portfolio diagnostic commands remain available but are secondary to the core objective.

Legacy Strategy 1 architecture, code field names, and historical targets remain untouched unless explicitly changed by a separate implementation experiment.

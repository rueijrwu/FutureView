# Strategy 1 — Research Objective and Current Definition

## 1. Original objective

The project goal is not to optimize a trading gate, threshold, or portfolio scheduler.

The core research question is:

```text
Given information observable now,
what is the success probability of a fixed Strategy 1 setup?
```

The intended decomposition is:

```text
Symbol   -> primarily determines profit opportunity / return magnitude
Strategy -> defines the legal trading process
Model    -> estimates Strategy 1 success probability from current information
```

Primary outputs remain:

```text
Success Rate        = probability / frequency that the defined outcome is profitable
Net Expected Return = E[Return]
```

`Net Expected Return` includes losing outcomes and may be negative.

This framing is the main line of research. Threshold engineering, adaptive gates, delayed-entry windows, portfolio state machines, and capital-efficiency studies are secondary implementation diagnostics only.

### Decision frequency is not a primary objective

A low number of model-selected Entries is not automatically a negative result.

It can mean:

```text
The current observable information is insufficient for the model
to make a high-confidence estimate or decision.
```

Therefore:

```text
low decision frequency != model failure
high decision frequency != model success
```

The model should first be judged by the quality of its probability estimate. Coverage/frequency is a later planning or deployment property.

---

## 2. Reference framework: Lower Bound, DCA, Upper Bound

For one fixed future window `W`, define the formal Strategy 1 legal realized-path set as:

```text
S(W) = all unique legal realized Strategy 1 paths available in window W
```

Every path in `S(W)` must obey the same formal Strategy 1 mechanics.

### Lower Bound

```text
LowerBound(W)
= min(Return(p)) for p in S(W)
```

Interpretation:

```text
The worst legal realized Strategy 1 outcome available in that window.
```

It is not Random Entry, and it is not an arbitrary bad trade. It is the minimum return from the same formal legal Strategy 1 search space used to define the Upper Bound.

### Upper Bound

```text
UpperBound(W)
= max(Return(p)) for p in S(W)
```

Interpretation:

```text
The best legal realized Strategy 1 outcome available in that window,
assuming perfect hindsight over the legal path set.
```

Upper Bound does not mean the model can achieve this return. It is a reference ceiling for what was legally achievable under Strategy 1 in that realized window.

### DCA reference

Current fixed DCA comparator:

```text
Day 0 / Day 20 / Day 40
three equal entries
hold to Day 59
```

Conceptually:

```text
Lower Bound  ->  DCA  ->  Upper Bound
worst legal      simple     best legal
Strategy 1       schedule   Strategy 1
selection                   selection
```

But this is conceptual only.

DCA is outside the formal Strategy 1 path set `S(W)`, so its realized return is not mathematically required to lie numerically between Lower and Upper.

### Important boundary rule

Lower and Upper must always be computed from the same formal Strategy 1 legal path space.

Do not redefine Lower Bound as Random Entry or any unrelated baseline.

```text
Lower Bound = worst legal Strategy 1 path
Upper Bound = best legal Strategy 1 path
```

---

## 3. Success Rate: exact definitions

The word `Success Rate` must always specify the observation unit.

There are two different quantities in the current research, and they should not be mixed.

### 3.1 Entry-level path success probability

For one formal Entry candidate `e`, let:

```text
P(e,60)
= all unique legal realized Strategy 1 paths beginning from Entry e
  over the 60-session horizon
```

Then:

```text
EntrySuccessProbability(e,60)
= count(Return(path) > 0) / count(P(e,60))
```

Equivalent:

```text
target_success_probability
= mean(Return(path) > 0)
```

Interpretation:

```text
Given this Entry and the formal Strategy 1 path space,
what fraction of legal realized paths finish profitable?
```

Examples:

```text
0.00 -> every legal path from this Entry loses
0.50 -> half of the legal paths profit
1.00 -> every legal path from this Entry profits
```

This is the current soft target used by the first CNN model.

### 3.2 Strategy / reference success rate across windows

When evaluating a specific reference rule across many windows, Success Rate means:

```text
SuccessRate(strategy)
= count(realized strategy returns > 0)
  / count(valid evaluation windows)
```

For example, `Upper-path Success Rate = 89.8%` for QQQ means:

```text
Across the valid QQQ 60D evaluation windows,
the best legal Strategy 1 path in 89.8% of those windows had positive return.
```

It does NOT mean:

```text
89.8% of all legal paths were profitable.
```

Those are different statistics.

### 3.3 Lower-bound success rate

The same definition can be applied to Lower Bound:

```text
LowerBoundSuccessRate
= count(LowerBound(W) > 0) / count(valid windows)
```

This asks a very strict question:

```text
In how many windows was even the worst legal Strategy 1 path profitable?
```

A low Lower-bound Success Rate does not imply Strategy 1 has no opportunity. It means legal path quality varies substantially within those windows.

### 3.4 Model probability versus empirical Success Rate

The model output should eventually be interpreted as:

```text
p_hat(e)
≈ P(Strategy 1 succeeds | information observable at Entry e)
```

If the model says `p_hat = 0.70`, the desired calibration interpretation is:

```text
Across many comparable OOS Entries where the model predicts about 70%,
roughly 70% should satisfy the chosen success definition.
```

This is a probability-estimation problem first. A threshold or trading decision can be added later.

---

## 4. How Bound and Success Rate relate

For each realized future window `W`, Lower and Upper are return values:

```text
LowerBound(W) <= UpperBound(W)
```

Across many windows, they induce two different Success Rates:

```text
LowerBoundSuccessRate
= P(LowerBound(W) > 0)

UpperBoundSuccessRate
= P(UpperBound(W) > 0)
```

These answer different questions.

### Lower Bound asks

```text
Was the window so favorable that even the worst legal Strategy 1 path made money?
```

### Upper Bound asks

```text
Did the window contain at least one legal Strategy 1 path that made money?
```

Therefore:

```text
LowerBoundSuccessRate <= UpperBoundSuccessRate
```

for the same set of valid windows and the same formal path space.

This gap is useful.

A large gap means:

```text
The symbol/window contains opportunity,
but path selection matters a lot.
```

A small high-level gap near 100% would mean:

```text
Most legal Strategy 1 paths are robustly profitable.
```

A small low-level gap would mean:

```text
The window generally offers poor Strategy 1 opportunity.
```

This is one reason Bound statistics are useful as reference structure even when the model target is a success probability.

---

## 5. SPY / QQQ / SMH examples

Five-year daily reference samples ending 2026-08-25, using the current 60D formal Strategy 1 research definition:

| Symbol | Upper-path Success Rate | Upper-path Net Expected Return | Fixed DCA Success Rate | Fixed DCA Net Expected Return | Lower-bound Mean Return |
|---|---:|---:|---:|---:|---:|
| SPY | 92.1% | +1.34% | 72.2% | +1.86% | -1.95% |
| QQQ | 89.8% | +2.09% | 67.4% | +2.43% | -2.30% |
| SMH | 81.7% | +3.72% | 67.5% | +5.73% | -3.89% |

These numbers illustrate why Success Rate and return magnitude should be kept separate.

### SPY example

```text
Upper-path Success Rate = 92.1%
Upper-path Net Return   = +1.34%
DCA Success Rate        = 72.2%
DCA Net Return          = +1.86%
Lower-bound mean        = -1.95%
```

Interpretation:

SPY had a very high frequency of windows containing at least one profitable legal Strategy 1 path. However, the average best-path return was smaller than QQQ and SMH.

This is consistent with the working interpretation:

```text
SPY -> relatively high reliability / lower return magnitude
```

The negative Lower-bound mean also shows that good opportunities did not imply every legal Strategy 1 path was good.

### QQQ example

```text
Upper-path Success Rate = 89.8%
Upper-path Net Return   = +2.09%
DCA Success Rate        = 67.4%
DCA Net Return          = +2.43%
Lower-bound mean        = -2.30%
```

Interpretation:

QQQ retained a high frequency of profitable opportunity while offering greater best-path return magnitude than SPY.

It is therefore a useful middle case for model development:

```text
not as defensive as SPY
not as high-variance as SMH
```

The research question for the model is not to reproduce the 89.8% Upper Bound. The model does not have hindsight.

The model should instead estimate, from causal information available now, how likely the current Strategy 1 setup is to succeed.

### SMH example

```text
Upper-path Success Rate = 81.7%
Upper-path Net Return   = +3.72%
DCA Success Rate        = 67.5%
DCA Net Return          = +5.73%
Lower-bound mean        = -3.89%
```

Interpretation:

SMH offered larger return magnitude, but the Upper-path Success Rate was lower and the Lower-bound mean was much worse.

That suggests a wider spread of possible Strategy 1 outcomes:

```text
more opportunity
+
more path-selection risk
```

This is why the working decomposition remains useful:

```text
symbol choice -> profit opportunity / magnitude
strategy/model -> reliability / success estimation
```

It is a research decomposition, not a claim that symbol and strategy effects are perfectly separable.

---

## 6. Current formal Strategy 1 rules

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

## 7. Current model target

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

Current primary soft target:

```text
EntrySuccessProbability(e,60)
```

Secondary audit labels:

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

## 8. First model: QQQ Entry Success CNN

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

The current model is still research-grade. Existing OOS diagnostics show some signal but do not yet establish reliable probability calibration across all regimes.

---

## 9. Current research direction

The project should now ask very small questions.

Current smallest model question:

```text
Given only information observable now,
can the model estimate the success probability of Strategy 1?
```

Do not optimize these yet:

```text
threshold
Q55
adaptive gate
trade frequency
portfolio overlap
capital efficiency
position sizing
symbol allocation
```

Those are downstream planning problems.

The immediate model problem is probability estimation.

A useful future result should look like:

```text
When the model predicts approximately 60%,
OOS realized success is approximately 60%.

When it predicts approximately 80%,
OOS realized success is approximately 80%.
```

Only after this is credible should the probability be used by a planning layer to decide whether, when, or how much to trade.

---

## 10. Active research commands

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

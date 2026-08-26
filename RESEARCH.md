# FutureView — Research Definition, Evidence, and Current Direction

Last consolidated: 2026-08-25

This is the canonical research document for FutureView. It consolidates the conceptual framework, Strategy 1 definition, target definitions, historical evidence, and current research direction. Implementation details, commands, architecture, data-provider details, and CI mechanics belong in `IMPLEMENT.md`.

## 1. Current research question

FutureView does not begin by inventing a universal trend score. The current question is deliberately smaller:

> Given only causal price/volume information observable at a formal Strategy 1 Entry, can a model identify entries whose future legal Strategy 1 outcomes have higher profitability and better economic return?

The working decomposition is:

```text
Symbol   -> shapes the realized opportunity distribution
Strategy -> defines the legal trading/path space
Model    -> estimates future properties of that legal-path distribution
Planning -> later converts estimates into trade/no-trade/sizing decisions
```

These effects are not assumed to be perfectly separable.

A central methodological rule is that model quality must not be confused with strategy headroom. Before asking whether a model can select good entries, we must ask whether the fixed strategy actually creates meaningful entry-to-entry outcome separation for that symbol.

## 2. Why strategy-relative targets

Earlier FutureView work investigated generic trend descriptors such as forward return, slope, R², directional persistence, efficiency ratio, curvature, MAE, MFE, Hurst exponent, and autocorrelation. These remain useful descriptive tools, but no arbitrary weighted combination is accepted as the primary target.

The present approach instead uses quantities that are mechanically determined by:

```text
fixed strategy + realized future data
```

This avoids manufacturing a subjective score before we understand the economic object being predicted.

## 3. Frozen Strategy 1 research mechanics

Strategy 1 is long-only and uses daily close information. The current formal research version uses three equal capital tranches and one campaign per evaluation window.

A formal Entry candidate satisfies:

```text
Close > MA5
Close > MA10
Close > MA20
MA5 > MA10
MA10 > MA20
```

All qualifying sessions are formal Entry candidates in the current entry-level research definition.

Legal future paths may contain no add-on, one legal add-on reference, or two legal add-on references. The current formal add-on construction uses confirmed local maxima and requires legal spacing; the second add-on additionally requires approximately equal realized price spacing relative to the first leg. Execution priority remains full MA10 exit, then eligible MA5 half exit, then add-on. Three-session cooldown and horizon-end liquidation remain part of the strategy.

The exact executable semantics are documented in `IMPLEMENT.md`; this section defines the research object, not code structure.

## 4. Window-level Strategy bounds

For one realized future window `W`, let:

```text
S(W) = all unique legal realized Strategy 1 paths available in W
```

Then:

```text
LowerBound(W) = min(Return(p)) for p in S(W)
UpperBound(W) = max(Return(p)) for p in S(W)
```

Preferred research names are Realized Strategy Lower Bound and Realized Strategy Upper Bound.

Interpretation:

```text
L -> worst legal Strategy 1 outcome in the realized window
U -> best legal Strategy 1 outcome in the realized window with hindsight
```

`U` is a hindsight reference ceiling. It is not a live-achievable promise and the model is not expected to reproduce it.

The realized path-selection spread is:

```text
StrategyOutcomeDispersion = U - L
```

A large `U-L` means legal path selection mattered substantially in that realized window. A small `U-L` means the strategy's legal paths produced similar outcomes. This is strategy-relative dispersion, not market volatility by definition.

## 5. Entry-level future distribution: L, U, μ, Q

For a formal Entry `e`, define:

```text
P(e,60) = all unique legal realized Strategy 1 paths beginning at e
          over the 60-session future horizon
```

The four historical descriptors are:

```text
L(e)  = min(Return(path))
U(e)  = max(Return(path))
μ(e)  = mean(Return(path))
Q(e)  = mean(Return(path) > 0)
```

Interpretation:

```text
L -> how bad was the worst legal execution from this Entry?
U -> how large was the best legal opportunity from this Entry?
μ -> what was the average legal-path return from this Entry?
Q -> what fraction of legal paths from this Entry finished profitable?
```

All four are ex-post labels: historical future data is allowed to construct them during training/research, but live inference receives only causal past/current data.

### Current priority

The current discussion places `Q` aside temporarily. `Q` may later be useful as a robustness/sensitivity descriptor, especially when entry timing is allowed to shift by one or more sessions. For the present reduced problem, retain the full information but focus analysis on:

```text
L, μ, U
```

`μ` is the most natural central economic quantity because it is the mean realized return across all legal future executions from the Entry. `L` and `U` preserve downside and upside context.

Do not compress `L, μ, U` into an arbitrary composite score yet. Any normalized position such as `(μ-L)/(U-L)` is derivable from the three raw quantities and can erase economically important absolute scale.

## 6. Historical reference distributions must be symbol-specific

A fixed absolute threshold is not assumed to mean the same thing across symbols. SPY, QQQ, and SMH have materially different payoff scales under Strategy 1.

The current historical reference procedure therefore asks first:

> For this symbol, where do the observed L, μ, and U values sit in that symbol's own historical distribution?

Percentiles are descriptive references, not yet approved trading thresholds.

### Holdout rule

The most recent three months are treated as unknown OOS data. They cannot be used to define historical distributions or thresholds.

Because each label requires a 60-session future path, an Entry belongs in the historical reference set only when its complete target horizon ends before the holdout begins:

```text
entry target end < holdout start
```

This creates a maturity gap between historical-reference samples and the live holdout and prevents future-label leakage.

## 7. SPY / QQQ / SMH historical L, μ, U characteristics

Using the same 60-session Strategy 1 entry-level definition and the same holdout isolation, the observed historical percentiles are:

| Metric | SPY P50 | SPY P75 | SPY P90 | QQQ P50 | QQQ P75 | QQQ P90 | SMH P50 | SMH P75 | SMH P90 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| L | -0.13% | +0.29% | +0.68% | -0.11% | +0.61% | +1.23% | -0.42% | +1.26% | +2.59% |
| U | +0.10% | +0.73% | +1.49% | +0.17% | +1.19% | +2.52% | +0.10% | +2.17% | +4.54% |
| μ | ~0.00% | +0.47% | +1.06% | ~0.00% | +0.86% | +1.90% | -0.20% | +1.67% | +3.39% |

Historical mature Entry counts were approximately SPY 346, QQQ 316, and SMH 295 under this reference construction.

Neutral interpretation:

```text
SPY -> narrower Strategy 1 payoff scale
QQQ -> wider positive/negative separation
SMH -> widest observed opportunity and downside scale
```

This is an empirical property of the current `symbol + Strategy 1 + sample` combination. It must not be generalized as a universal volatility law.

### SPY

The median `μ` is essentially zero and the upper percentiles rise relatively gradually. Good Strategy 1 entries therefore have smaller absolute separation than in QQQ/SMH.

### QQQ

Median `μ` is also near zero, but favorable entries have materially larger `μ` and `U`. Strategy 1 creates more economic separation between ordinary and strong entries than observed for SPY.

### SMH

Median `μ` is slightly negative while P75/P90 outcomes are much larger. Bad outcomes can also be substantially worse. This creates a broad strategy-relative opportunity space in which correct entry selection could have high economic value.

## 8. Important discovery: strategy headroom vs model skill

This is a central current finding.

Earlier baseline comparisons showed that on SPY, a simple fixed periodic/DCA-style comparator can perform close to, and in some summaries exceed, Strategy 1's hindsight best-path return. This means SPY's narrow Strategy 1 opportunity range cannot automatically be interpreted as a model limitation.

The correct decomposition is:

```text
Question A — Strategy headroom
Does this symbol + fixed strategy create meaningful timing/entry-selection value
relative to a simple non-predictive baseline?

Question B — Model skill
Given that headroom exists, can causal OHLCV identify the entries that realize
better L, μ, U outcomes out of sample?
```

A model cannot manufacture separation that the strategy itself does not create.

Therefore:

```text
small model separation on SPY
!= automatically model failure
```

if Strategy 1 itself has little incremental timing value over a simple baseline.

Conversely, wider L/μ/U distributions in QQQ or SMH are not proof of model skill. They only indicate that more outcome separation exists for a model to potentially learn.

### Consequence for evaluation

Before judging a model on a symbol, estimate the strategy's available optimization headroom against simple baselines. Useful reference comparisons include fixed periodic entry / DCA and always-on Strategy 1. This benchmark is not a model score; it tells us whether the learning problem has meaningful economic room.

## 9. DCA/reference baseline

The current fixed DCA comparator uses three equal entries at Day 0 / Day 20 / Day 40 and holds to Day 59.

DCA is external to the formal Strategy 1 path set. Therefore it is not mathematically required to lie between Strategy 1 `L` and `U`, and it must never be used to define either bound.

Five-year reference summaries previously observed:

| Symbol | Profitable-opportunity rate | Mean U | Fixed DCA success rate | Fixed DCA mean return | Mean L |
|---|---:|---:|---:|---:|---:|
| SPY | 92.1% | +1.34% | 72.2% | +1.86% | -1.95% |
| QQQ | 89.8% | +2.09% | 67.4% | +2.43% | -2.30% |
| SMH | 81.7% | +3.72% | 67.5% | +5.73% | -3.89% |

These numbers reinforce the need to separate opportunity frequency, absolute return magnitude, downside, and strategy-specific timing headroom.

## 10. What constitutes a good entry is not yet fixed

We have not approved rules such as:

```text
μ > P75
L > P50
U > P75
```

Percentiles are currently used to understand each symbol's historical scale only. Thresholds/filters must be discussed and justified one metric at a time before they are admitted into evaluation or planning.

The present order is:

```text
1. understand μ
2. understand L
3. understand U
4. only then consider a multidimensional rule or score if necessary
```

A single scalar may never be necessary. A good entry may remain a multidimensional object.

## 11. Model objective

At live inference time, the model does not know future `L`, `μ`, or `U`. It sees only causal information available at the Entry.

The supervised-learning problem is therefore:

```text
past/current causal OHLCV structure
        -> estimate/rank future entry-level L, μ, U characteristics
```

The model does not need to predict exact decimal values to be useful. A credible first capability may be stable OOS ranking: entries scored more favorably should subsequently exhibit better realized economic outcomes.

Point-error metrics alone are insufficient for this purpose. Earlier experiments showed that lower MAE can coexist with worse ranking. MAE remains diagnostic rather than an automatically accepted primary score.

No model metric is accepted merely because it is conventional. Every evaluation metric must be justified against the actual research question.

## 12. Historical model evidence

Earlier Strategy 1 work used raw Oracle Value/Q-oriented targets before the current reduction to L/μ/U. These experiments remain useful evidence about architecture and validation behavior, but they do not define the current target.

### Daily CNN ranking

For the earlier 30D raw Oracle Value problem, Daily CNN A with Sliding-260 history showed reproducible ranking evidence across five seeds:

```text
mean Spearman ≈ +0.234
positive mean-Spearman seeds = 5/5
mean top-20% Oracle lift ≈ +0.00419
positive top-20% lift seeds = 5/5
```

The CNN ranked better than a fixed low-dimensional Summary Ridge on Spearman, but did not establish superior realized portfolio economics.

### MAE lesson

Earlier results included cases where models with better MAE had worse ranking. Therefore MAE is not treated as a sufficient definition of model quality for the present entry-selection problem.

### Higher-frequency inputs

A matched-feed multi-fold comparison did not establish a reproducible advantage from doubling observations from daily 50 bars to 100 intraday RTH observations. Daily input remains the primary validated baseline; higher-frequency input is on hold.

### CNN + Summary20 fusion

Directly concatenating the fixed Summary20 features into the CNN degraded OOS ranking despite improving MAE. This experiment failed its predeclared ranking gate. Summary Ridge remains useful as an independent baseline, not as a proven beneficial CNN fusion input.

### Portfolio gate experiments

Earlier P80 gate experiments showed that restoring signal frequency through recent-OOS rank normalization did not improve economic selection; added campaigns were losing. This is a warning against post-hoc threshold engineering. Gate/portfolio optimization is downstream and should not drive the present definition work.

## 13. Validation principles

Formal evaluation must be chronological and causal:

```text
past -> train
purge future-label overlap
later data -> validation/test
```

No random train/test split.

The newest three-month block is reserved as unknown OOS data for the current historical-reference work. Historical thresholds, normalization references, or model choices must not use it.

Repeated tuning on the same OOS period converts that period into development data and must not be presented as fresh validation.

## 14. Current research sequence

The immediate sequence is intentionally narrow:

```text
Stage 0 — Strategy headroom
For each symbol, quantify whether Strategy 1 creates meaningful entry-selection
value relative to simple baselines.

Stage 1 — Historical L/μ/U structure
Understand symbol-specific distributions without inventing a score.

Stage 2 — Predictability
Test whether causal OHLCV can rank or estimate future μ, L, U OOS.

Stage 3 — Entry-quality definition
Only after predictability is understood, discuss justified thresholds/filters.

Stage 4 — Planning
Only then consider trade/no-trade, delayed entry, position sizing, portfolio overlap,
frequency, capital efficiency, and symbol allocation.
```

`Q` remains available for later robustness/sensitivity research, especially if entry timing becomes flexible.

## 15. Current concise conclusion

FutureView is presently testing a strategy-relative learning hypothesis, not a universal trend classifier.

The strongest current conceptual statement is:

> Historical future data can mechanically define each Strategy 1 Entry by its legal-path lower bound `L`, mean return `μ`, and upper bound `U`. These quantities have materially different distributions across SPY, QQQ, and SMH. Before judging model skill, we must first determine how much timing/entry-selection headroom Strategy 1 itself creates for each symbol relative to simple baselines. Only then can we fairly ask whether causal OHLCV identifies entries with better future `L`, `μ`, and `U`.

This separation between **strategy opportunity** and **model skill** is now a core FutureView research principle.

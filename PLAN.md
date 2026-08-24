# FutureView CNN Trend Research Plan

Last updated: 2026-08-24

## 1. Reset Scope

This branch is a clean research restart.

The previous momentum ranking, sector-selection, portfolio-construction, pyramiding, options, frontend, and production workflow logic are intentionally excluded from the initial research scope.

The first objective is much narrower:

> Using only recent SPY price and volume history, can a small CNN learn a useful forward-looking trend score whose higher values correspond to a higher probability of a successful, persistent bullish trend?

This branch should stay minimal until that question is answered empirically.

## 2. Core Research Principles

1. Start with SPY only.
2. Use price and volume only.
3. Use a CNN as the primary predictive model.
4. Do not assume older market data is equally representative of the current market.
5. Test training-history length empirically instead of fixing it by intuition.
6. Use strict chronological / walk-forward validation. Never random-shuffle overlapping time-series samples.
7. The model should estimate trend quality, not simply next-day direction.
8. Optimize for useful out-of-sample trend discrimination, not training accuracy.
9. Keep the first model small enough to match the available sample size.
10. Add QQQ, sector ETFs, and individual stocks only after the SPY experiment demonstrates genuine out-of-sample value.

## 3. Data Scope

### Instrument

Initial research instrument:

```text
SPY only
```

SPY is treated as a broad U.S. large-cap market proxy, not literally an equal-weight average of all stocks.

### Data fields

Allowed model information:

```text
Open
High
Low
Close
Volume
```

Derived transformations that use only price and volume are allowed, including normalized returns, relative price levels, moving averages, volume averages, volatility-like quantities derived from price, and future-path quantities used only for labels/evaluation.

No fundamentals, news, macro data, sentiment, options data, breadth data, or external technical indicators in the initial experiment.

### Data sources

Preferred research history:

```text
Yahoo Finance or another reliable source: up to ~5 years of daily SPY OHLCV
Massive: recent ~2 years for cross-checking and/or current updates
```

The model must not be constrained to two years merely because Massive currently exposes only that span.

Before combining or comparing sources, verify:

```text
trading dates
OHLC values
volume
adjustment conventions
missing sessions
corporate-action treatment
```

A single canonical series should be produced before training.

## 4. Recency Hypothesis

The central data hypothesis is:

> More history is not automatically better. Older market regimes may reduce relevance to current conditions.

Therefore training-history length is a research variable.

Primary comparison:

```text
1-year rolling history
2-year rolling history
3-year rolling history
5-year rolling history
```

Optional comparison:

```text
5-year history with recency-weighted loss
```

Example recency weighting:

```text
recent observations receive the highest weight
older observations decay exponentially
```

The exact decay rate must be treated as a tunable research parameter and evaluated only through walk-forward out-of-sample results.

## 5. Input Representation

### Lookback window

Initial baseline:

```text
50 trading sessions
```

Each sample uses only information available through day t.

### Raw input

Baseline tensor:

```text
50 x 5
```

representing transformed OHLCV.

Do not feed absolute SPY price levels directly without normalization.

Candidate normalized price channels:

```text
Open / previous Close - 1
High / previous Close - 1
Low / previous Close - 1
Close / previous Close - 1
```

or equivalent log-return forms.

Candidate volume normalization:

```text
log(volume)
relative / standardized volume using only trailing history
```

All normalization parameters must be computed from information available at or before the sample date.

## 6. CNN Architecture Hypothesis

The first model should be deliberately small.

Primary architecture concept:

```text
50-day OHLCV input
        |
  -------------------
  |        |        |
CNN-5    CNN-10   CNN-20
  |        |        |
  -------------------
        |
   fusion / gating
        |
 global pooling
        |
 small dense layer
        |
   Trend Score
```

The 5-, 10-, and 20-session receptive fields are intended to represent short, intermediate, and swing-trend structures.

The network should learn their relative importance rather than receiving fixed manual weights.

### Explicit moving-average ablation

A second model variant should expose explicit price and volume averages:

```text
Price MA5
Price MA10
Price MA20
Volume MA5
Volume MA10
Volume MA20
```

These features should enter a separate branch or fusion layer rather than replacing the raw OHLCV branch.

Required comparison:

```text
Model A: raw OHLCV CNN only
Model B: raw OHLCV CNN + explicit MA branch
```

This tests whether explicit smoothing improves generalization or whether the CNN can learn equivalent filters itself.

## 7. What the Model Should Predict

Do not begin with next-day up/down classification.

The target is a forward trend-quality concept over a fixed future horizon.

Initial horizon:

```text
20 trading sessions
```

The model should estimate whether the future path is not only positive, but persistent and risk-efficient.

## 8. Trend Ground Truth

Defining trend quality is the most important part of the project.

A good bullish trend should combine:

```text
positive forward return
high path efficiency / persistence
limited adverse excursion
reasonable directional consistency
```

Candidate forward quantities:

```text
ForwardReturn20
MAE20
MFE20
TrendEfficiency20
linear slope
R-squared / path fit quality
```

One useful path-efficiency definition is:

```text
Efficiency20 =
    (Close[t+20] - Close[t])
    /
    sum(abs(Close[i] - Close[i-1])) over the forward 20-session path
```

A smooth directional move should have higher efficiency than a noisy path ending at the same return.

### Preferred first target

Use a continuous future Trend Quality target rather than only a binary label.

Conceptually:

```text
FutureTrendQuality
= reward(forward return)
+ reward(path efficiency)
+ reward(direction consistency)
- penalty(adverse excursion)
```

Normalize the final target to a stable range such as:

```text
-1 ... +1
```

or:

```text
0 ... 1
```

Exact coefficients must remain research hypotheses rather than permanent constants.

### Binary success metric

A separate binary definition should be retained for evaluation.

For example, a successful bullish trend can require a combination of:

```text
minimum forward return
maximum acceptable adverse excursion
minimum trend efficiency
```

Thresholds must be tested for robustness and should not be optimized solely to maximize headline success rate.

## 9. Trend Score

The model output is:

```text
TrendScore(t)
```

Interpretation:

> Given the previous 50 sessions of SPY price/volume behavior, how strong is the evidence that the next ~20 sessions will form a high-quality bullish trend?

The primary research goal is not simply low prediction error.

The desired empirical property is monotonicity:

```text
higher TrendScore
-> higher future trend success rate
-> higher forward return / MFE
-> lower or better-controlled MAE
```

## 10. Validation Rules

### No random train/test split

Adjacent 50-day windows overlap heavily.

Therefore this is forbidden:

```text
random shuffle
random 80/20 train/test split
```

### Required validation

Use chronological walk-forward evaluation.

General form:

```text
Train on past data only
Validate on the next block
Test on a later untouched block
Roll forward
Repeat
```

The future label horizon must also be purged from training/validation boundaries so that no future information overlaps evaluation periods.

### Compare history windows fairly

For the 1Y / 2Y / 3Y / 5Y comparison:

```text
same model architecture
same preprocessing
same label definition
same evaluation dates
same optimization procedure
```

Only the available training-history window should change.

## 11. Primary Evaluation Metrics

Do not optimize for win rate alone.

Every experiment should report:

```text
TrendScore distribution
TrendScore quantile / decile results
signal count
coverage
success rate
mean forward return
median forward return
MAE
MFE
trend efficiency
calibration / monotonicity
```

A useful result should look qualitatively like:

```text
TrendScore increases
-> success rate rises
-> forward return improves
-> adverse excursion is controlled
```

A model that produces very few signals with a superficially high success rate should not automatically be considered superior.

## 12. Phase 1 Is Prediction Research, Not Yet a Trading Strategy

Do not immediately convert the CNN into entry/exit rules.

First prove that TrendScore contains out-of-sample information.

Primary Phase-1 analysis:

```text
TrendScore decile
vs
future 20-session return
future success rate
future MAE
future MFE
future trend efficiency
```

Only after a stable monotonic relationship is demonstrated should TrendScore be converted into a trading rule.

## 13. Baseline Models

A CNN result must be compared with simple baselines.

At minimum:

```text
naive constant predictor
simple recent return / momentum baseline
simple MA-based trend baseline
small linear / logistic model using the same allowed price-volume information
```

The CNN must demonstrate incremental out-of-sample value over these simpler alternatives.

## 14. Initial Experiment Matrix

### Data-history experiment

```text
CNN-1Y
CNN-2Y
CNN-3Y
CNN-5Y
CNN-5Y-recency-weighted
```

### Feature / architecture ablation

```text
raw OHLCV CNN
raw OHLCV CNN + explicit MA5/10/20 branch
```

### Initial prediction horizon

```text
20 sessions
```

Only after the 20-session baseline is understood should alternative horizons such as 10, 30, or 40 sessions be tested.

## 15. Expansion Path

Do not expand until the SPY model demonstrates reproducible out-of-sample value.

### Stage 1

```text
SPY
-> broad-market TrendScore
```

### Stage 2

Add style / market-regime proxies:

```text
QQQ
IWM
```

These should initially be treated as independent trend models rather than automatically as sector weights.

### Stage 3

Sector ETFs:

```text
XLK
XLF
XLE
XLV
XLI
...
```

Each can produce its own SectorTrendScore using the same price-volume-only framework.

### Stage 4

Individual stocks:

```text
MarketTrendScore
SectorTrendScore
StockTrendScore
```

Only at this stage should the project investigate how those scores combine into selection or position-sizing decisions.

## 16. Explicitly Deferred

Do not implement these during the initial SPY research phase:

```text
individual-stock ranking
Top-50 selection
sector ranking
portfolio construction
pyramiding
options acceleration
broker execution
frontend dashboard
production workflows
CNN-controlled dynamic trading rules
```

They can be reconsidered only after the basic trend-detection hypothesis is validated.

## 17. First Implementation Milestones

1. Build canonical SPY daily OHLCV dataset, preferably up to 5 recent years.
2. Cross-check recent overlap between Yahoo Finance and Massive where practical.
3. Implement causal preprocessing and 50-session sample generation.
4. Implement 20-session future trend-quality labels and evaluation fields.
5. Implement simple non-CNN baselines.
6. Implement the small multi-scale 1D CNN with 5/10/20-session receptive fields.
7. Implement the explicit MA branch variant.
8. Implement strict purged walk-forward training/evaluation.
9. Run 1Y / 2Y / 3Y / 5Y training-history comparisons.
10. Run 5Y recency-weighted comparison.
11. Produce TrendScore quantile/decile audit tables.
12. Decide empirically whether the CNN contains sufficient out-of-sample trend information to justify Phase 2.

## 18. Initial Success Criterion

The first milestone is not portfolio return.

The project advances only if out-of-sample results show that TrendScore has stable and useful ordering power across walk-forward folds.

The strongest evidence would be:

```text
higher TrendScore buckets consistently show
- higher successful-trend rate
- better forward return
- better MFE
- controlled MAE
- stronger path efficiency
```

and the CNN performs better than simple price-volume baselines without relying on a tiny number of extreme signals.

If these conditions are not met, revise the label, preprocessing, model capacity, or training-history assumptions before adding more instruments or complexity.

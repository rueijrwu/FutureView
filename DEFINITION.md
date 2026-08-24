# Trend Definition Candidates

This document is a literature-grounded candidate library for defining and measuring price trends in FutureView.

The purpose is **not** to lock in a final winning criterion yet. Different metrics measure different concepts: direction, persistence, path coherence, smoothness, shape, or tradability. These should be kept separate until we decide what FutureView should predict.

## 1. Guiding principle

There is no single universally accepted mathematical definition of a financial price trend. Academic finance, statistical time-series analysis, technical-analysis research, and systematic trading each operationalize “trend” differently.

For FutureView, candidate measures should therefore be treated as descriptors of different aspects of a future price path rather than as interchangeable definitions.

A useful conceptual decomposition is:

- **Direction**: Is the path moving upward or downward overall?
- **Magnitude**: How large is the net movement?
- **Persistence**: Does the path continue in the same direction over time?
- **Coherence / efficiency**: Is the path directional rather than highly back-and-forth?
- **Smoothness / fit**: Can a simple trend function explain much of the path?
- **Shape**: Is the trend steady, accelerating, decelerating, or curved?
- **Risk / tradability**: Was the path acceptable from an entry-risk perspective?

The last category should not automatically be treated as part of “trend morphology.”

---

## 2. Forward return / displacement

### Definition

For horizon `h`:

```text
R_h = C_(t+h) / C_t - 1
```

### What it measures

- Net direction
- Net magnitude

### Strengths

- Simple and directly interpretable
- Widely used in momentum and trend-following research
- Closely related to time-series momentum signals

### Limitations

Return alone does **not** distinguish a smooth trend from a highly erratic path that happens to finish higher.

Example:

```text
100 -> 101 -> 102 -> 103 -> 104
```

and

```text
100 -> 110 -> 90 -> 115 -> 104
```

have the same final return but very different path structure.

### Literature context

Time-series momentum research commonly uses the sign or magnitude of an asset’s own past return as the trend signal. Moskowitz, Ooi, and Pedersen (2012) are a central reference for this approach.

### Role for FutureView

**Core direction/magnitude descriptor, but not sufficient as a full trend definition.**

---

## 3. Linear trend slope

### Definition

Fit a line to the future log-price path:

```text
log(C_(t+i)) = a + b i + epsilon_i
```

where `b` is the slope.

Using log price is preferable because the slope then reflects approximately proportional rather than absolute price change.

### What it measures

- Direction
- Average rate of change

### Interpretation

- `b > 0`: upward trend
- `b < 0`: downward trend
- larger `|b|`: stronger directional movement

### Strengths

- Very direct statistical definition of trend
- Uses the whole path, not only the endpoint
- Easy to compare with goodness-of-fit

### Limitations

- A path can have a positive slope but still be very noisy
- A strongly nonlinear path may be poorly summarized by one slope

### Role for FutureView

**Strong candidate for a primary trend-direction descriptor.**

---

## 4. Regression goodness-of-fit (`R^2`)

### Definition

From the same regression:

```text
log(C_(t+i)) = a + b i + epsilon_i
```

compute the coefficient of determination `R^2`.

### What it measures

How much of the future price-path variation is explained by a simple linear trend.

### Interpretation

- high `R^2`: path follows a relatively coherent linear trend
- low `R^2`: path is noisy, curved, regime-changing, or otherwise poorly explained by one line

### Strengths

- Separates direction from trend quality
- Helps distinguish “large endpoint return” from “consistent path”

### Limitations

- Penalizes valid curved or accelerating trends
- Can be sensitive to horizon and volatility

### Literature context

Regression slope combined with goodness-of-fit is a standard statistical way to quantify trend strength. In systematic-trading literature, related regression-based trend measures are also common.

### Role for FutureView

**Strong candidate for trend smoothness/coherence, especially when paired with slope.**

---

## 5. Directional persistence / sign consistency

### Simple definition

One simple version is:

```text
P_h = number of positive returns / h
```

or for a bullish path:

```text
P_h = mean(Delta C_i > 0)
```

### What it measures

How frequently local moves agree with the overall direction.

### Strengths

- Directly measures directional persistence
- Distinguishes a trend from one or two isolated large jumps

### Limitations

- Daily sign is noisy
- A good trend can still contain many small down days
- Equal weighting of tiny and large moves may be undesirable

### Better variants to consider

- multi-day directional consistency
- fraction of rolling slopes with the same sign
- weighted sign consistency using return magnitude

### Role for FutureView

**Promising persistence descriptor, but likely should use a less noisy version than raw daily up/down fraction.**

---

## 6. Efficiency Ratio / path efficiency

### Definition

A Kaufman-style efficiency measure is:

```text
ER_h = |C_(t+h) - C_t| / sum(|C_(t+i) - C_(t+i-1)|)
```

For signed bullish/bearish direction, the numerator can retain its sign:

```text
E_h = (C_(t+h) - C_t) / sum(|C_(t+i) - C_(t+i-1)|)
```

### What it measures

Net directional displacement relative to total distance traveled.

### Interpretation

- near `+1`: very efficient upward path
- near `0`: highly back-and-forth path
- near `-1`: very efficient downward path

### Strengths

- Directly captures path coherence
- Scale-independent in the ratio form
- Complements return or slope well

### Limitations

- A tiny but perfectly monotonic move can have very high efficiency
- High efficiency does not imply economically meaningful magnitude

### Literature context

This measure is closely related to Perry Kaufman’s Efficiency Ratio, widely used in systematic technical analysis and adaptive trend-following.

### Role for FutureView

**Strong candidate for directional path coherence, but should not be used alone.**

---

## 7. Moving-average / filtered trend

### Definition family

Examples:

- short MA above long MA
- price above a moving average
- slope of a moving average
- weighted moving-average trend

### What it measures

A low-pass filtered estimate of local direction.

### Strengths

- Very common in practical trend-following
- Robust to some high-frequency noise
- Easy to interpret

### Limitations

- Depends heavily on filter/window choice
- Introduces lag
- Not a unique definition of trend

### Literature context

Published trend-following and time-series-momentum studies use multiple constructions, including past returns, moving averages, and weighted moving averages. There is no consensus on a single best trend measure.

### Role for FutureView

**Useful as a benchmark/baseline trend detector, probably not ideal as the only ground-truth definition.**

---

## 8. Nonparametric smoothed path / kernel regression

### Concept

Instead of fitting a specific linear or polynomial function, estimate a smooth latent price path with a nonparametric smoother such as kernel regression.

Conceptually:

```text
Observed price = smooth latent path + noise
```

Then analyze extrema, slopes, and shapes on the smooth path.

### What it measures

- underlying path structure
- trend or technical-pattern shape after suppressing noise

### Strengths

- Does not force the path to be linear
- Provides an objective alternative to visual chart interpretation
- Can support slope and curvature measurements on the smoothed trajectory

### Limitations

- Results depend on smoothing bandwidth
- A smoother can remove meaningful short-term structure if over-smoothed

### Literature context

Lo, Mamaysky, and Wang (2000), *Foundations of Technical Analysis*, use nonparametric kernel regression to convert subjective visual technical patterns into systematic, algorithmic representations.

### Role for FutureView

**Important candidate framework for estimating the underlying path before computing trend descriptors.**

---

## 9. Polynomial trend and curvature

### Definition

Fit a quadratic function to normalized future time and log price:

```text
log(C_(t+i)) = a + b x_i + c x_i^2 + epsilon_i
```

where time `x_i` should preferably be normalized to a common interval such as `[0,1]` or `[-1,1]` so curvature values are more comparable across horizons.

### What it measures

- `b`: first-order direction / local trend component
- `c`: curvature / acceleration or deceleration of the fitted path

### Interpretation for bullish paths

- `b > 0`, `c ~ 0`: approximately steady upward trend
- positive curvature: accelerating upward trajectory
- negative curvature: decelerating / flattening upward trajectory

### Strengths

- Captures shape that linear slope and `R^2` miss
- Can distinguish steady from accelerating/decelerating trends

### Limitations

- Curvature is **not** itself a standard universal definition of trend
- Large curvature may represent a late spike rather than a desirable persistent trend
- Polynomial coefficients can be unstable without time/price normalization

### Role for FutureView

**Useful trend-shape descriptor; should not automatically be treated as a monotonic reward.**

---

## 10. Local-slope evolution / curvature stability

### Concept

Estimate local slopes across the path and examine how smoothly they evolve.

Examples:

- rolling linear-regression slope
- derivative of a smoothed path
- variance of local slope
- monotonic change in local slope

### What it measures

Whether acceleration/deceleration is coherent rather than produced by noisy daily fluctuations.

### Strengths

- More robust conceptually than a single global quadratic coefficient
- Can distinguish smooth acceleration from unstable zig-zag behavior

### Limitations

- Requires additional smoothing/window choices
- More complex to normalize across horizons

### Role for FutureView

**Candidate extension if curvature proves useful.**

---

## 11. Mann–Kendall monotonic trend test

### Concept

A nonparametric statistical test for monotonic trend.

Instead of assuming a linear relation, it asks whether later observations tend systematically to be larger or smaller than earlier observations.

### What it measures

- statistical evidence of monotonic increasing or decreasing tendency

### Strengths

- nonparametric
- does not require normal residuals
- does not require a linear trend

### Limitations

- primarily a significance test, not naturally a continuous economic trend-quality score
- autocorrelation can complicate inference
- significance depends on sample length

### Role for FutureView

**Useful reference/statistical validation metric; probably not the primary CNN target.**

---

## 12. Hurst exponent / long-memory persistence

### Concept

The Hurst exponent is commonly interpreted as:

- `H > 0.5`: persistent behavior
- `H ~ 0.5`: random-walk-like behavior
- `H < 0.5`: anti-persistent / mean-reverting behavior

### What it measures

Persistence properties of a stochastic process or regime rather than the specific morphology of one short future trend path.

### Strengths

- useful for describing whether a regime is trend-friendly or mean-reverting

### Limitations

- estimation can be noisy
- interpretation over short windows is difficult
- does not directly answer whether one specific 15–60 day future path is a good bullish trend

### Role for FutureView

**Better suited as a regime descriptor or auxiliary feature than as the main future-trend ground truth.**

---

## 13. Autocorrelation / return persistence

### Concept

Trend persistence can also be studied through positive serial dependence in returns or through continuation of past returns.

### What it measures

Whether directional movement tends to continue rather than reverse.

### Strengths

- directly connected to momentum literature
- statistically interpretable

### Limitations

- individual-equity-index daily autocorrelation is often weak/noisy
- does not describe path shape

### Role for FutureView

**Useful conceptual link to time-series momentum, but not a complete path-level definition.**

---

## 14. Maximum Adverse Excursion (MAE)

### Definition

For a bullish candidate beginning at time `t`:

```text
MAE_h = min(0, min(C_(t+i)/C_t - 1))
```

### What it measures

Worst adverse movement relative to the starting price during the horizon.

### Strengths

- directly relevant to entry risk and tradability
- useful for defining whether a predicted trend was practically exploitable from the signal date

### Limitation that matters most

MAE does **not** describe trend morphology itself.

A path can experience a large initial drawdown and then develop a very coherent upward trend. Penalizing MAE inside the trend definition would mix “what the path became” with “how comfortable the entry was.”

### Role for FutureView

**Risk / successful-trade metric, not a preferred primary trend-definition variable.**

---

## 15. Maximum Favorable Excursion (MFE)

### Definition

```text
MFE_h = max(0, max(C_(t+i)/C_t - 1))
```

### What it measures

Largest favorable excursion achieved within the horizon.

### Strengths

- useful for evaluating opportunity magnitude

### Limitations

- a single price spike can create a large MFE without a persistent trend

### Role for FutureView

**Trade-opportunity/evaluation metric, not a primary trend descriptor.**

---

## 16. Candidate taxonomy for FutureView

The literature-backed measures can be organized as follows:

| Concept | Candidate measures |
|---|---|
| Direction | forward return, regression slope, moving-average slope |
| Magnitude | forward return, normalized slope |
| Persistence | return-sign consistency, local-slope consistency, time-series momentum |
| Coherence | Kaufman-style Efficiency Ratio |
| Smoothness | linear-regression `R^2`, residual variance |
| Nonlinear shape | quadratic curvature, smoothed-path derivatives |
| Monotonicity | Mann–Kendall statistic/test |
| Regime persistence | Hurst exponent, autocorrelation |
| Risk / tradability | MAE, drawdown |
| Opportunity | MFE |

---

## 17. Important distinction: trend vs. winning trade

For FutureView we should not prematurely collapse all of these into one formula.

A future path can be separated conceptually into two questions.

### Question A — What kind of trend occurred?

Candidate descriptors:

```text
slope
R^2
efficiency
persistence
curvature
smoothed-path shape
```

### Question B — Was acting on the signal successful?

Candidate evaluation variables:

```text
realized return
MAE / drawdown
MFE
possibly transaction-cost-adjusted return
```

This separation is important because defining “trend” and defining “winning prediction/trade” are not necessarily the same problem.

---

## 18. Current FutureView status

The current implementation in `labels.py` still uses a provisional continuous target based on return, efficiency, and MAE. That target exists only to validate the data/model pipeline and should **not** yet be interpreted as the final research definition of trend.

Before formal model evaluation, we should compare several of the literature-based descriptors above on historical SPY future paths and determine which ones best capture the phenomenon we actually want the CNN to predict.

No final weighting or success threshold is selected in this document.

---

## 19. References

1. Moskowitz, T. J., Ooi, Y. H., & Pedersen, L. H. (2012). **Time Series Momentum.** *Journal of Financial Economics*, 104, 228–250.
2. Lo, A. W., Mamaysky, H., & Wang, J. (2000). **Foundations of Technical Analysis: Computational Algorithms, Statistical Inference, and Empirical Implementation.** *Journal of Finance*, 55(4), 1705–1765. NBER Working Paper 7613. DOI: 10.3386/w7613.
3. Georgopoulou, A., & Wang, J. (2017). **The Trend Is Your Friend: Time-Series Momentum Strategies across Equity and Commodity Markets.** *Review of Finance*, 21(4), 1557–1592.
4. Kaufman, P. J. **Trading Systems and Methods.** Efficiency Ratio / adaptive-trend methodology.
5. Mann, H. B. (1945). **Nonparametric Tests Against Trend.** *Econometrica*, 13(3), 245–259.
6. Kendall, M. G. **Rank Correlation Methods.** Monotonic trend testing framework.

## 20. Source notes used in this revision

- Lo, Mamaysky, and Wang’s NBER version describes a systematic, automatic technical-pattern approach based on nonparametric kernel regression and explicitly addresses the subjectivity of visual chart interpretation.
- Modern time-series momentum literature continues to emphasize that there is no single consensus method for quantifying the trend of one asset; published implementations include past cumulative return and moving-average-based measures.
- Time-series momentum uses an asset’s own past directional return as a continuation signal, which supports treating direction/persistence separately from risk measures such as MAE.

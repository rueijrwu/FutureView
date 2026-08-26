# FutureView — Research Definition, Evidence, and Current Direction

Last consolidated: 2026-08-26

This is the canonical research document for FutureView. It records the current Strategy-1 Layer-1 research definition, the facts established so far, and the interpretation boundaries that should not be crossed prematurely. Implementation details, commands, architecture mechanics, data-provider details, and CI mechanics belong in `IMPLEMENT.md`.

## 1. Current research purpose

The present work is a **data-understanding / representation-interpretation study**.

We are not currently deciding which model component is required, which statistic is sufficient, which region is important, or which downstream layer should be built next.

The immediate question is deliberately smaller:

> **Given all legal realized Strategy-1 outcomes inside a fixed historical calendar interval `W`, what structure exists in those realized outcome distributions, and what information is preserved when they are compressed into a low-dimensional learned representation?**

The present study does not ask why a historical interval produced those outcomes. It does not use causal price/volume information to explain them. It also does not assign `good`, `bad`, or `neutral` labels in advance.

A central methodological rule is:

> **Observations come first. Interpretation and model-design decisions come later.**

No threshold, window length, maturity rule, normalization, derived statistic, class weighting, resampling rule, economic label, or downstream architecture should be treated as necessary merely because it is convenient or intuitive.

## 2. Broader two-layer framework

The wider FutureView concept remains:

```text
Layer 1: understand / represent Strategy-1 realized profitability structure
        -> Layer 2: later causal price/volume selection problem
        -> downstream C/Q entry-quality terminology
```

However, the current work is restricted to Layer 1.

Layer 1 asks only:

```text
What did the complete set of legal Strategy-1 paths produce in this historical interval?
```

Layer 2, if revisited later, would ask a different causal question using only information available at decision time. No conclusion about Layer 2 is implied by the present representation study.

## 3. Fixed calendar window `W`

The interval `W` is a fixed calendar/trading-session window, not a fixed number of recent legal paths.

This preserves the actual Strategy-1 path-occurrence structure of each historical period. A fixed-path-count construction would reach farther backward when legal opportunities are sparse and could mix different historical periods.

The exact production value of `W` is not frozen.

Current pilot values are:

```text
W = 20, 30, 60 trading sessions
```

These are experiment values only, not an optimality claim.

Other lengths in the repository have separate meanings and must not be confused with `W`:

```text
60 sessions  -> per-Entry future campaign horizon
50 sessions  -> historical causal price/volume context used elsewhere
260 sessions -> earlier sliding training policy
W             -> Layer-1 fixed historical calendar interval
```

## 4. Frozen Strategy-1 research mechanics

Strategy 1 is long-only and uses daily close information.

A formal Entry satisfies:

```text
Close > MA5
Close > MA10
Close > MA20
MA5 > MA10
MA10 > MA20
```

The current executable campaign uses three equal capital tranches:

- initial Entry uses one third of capital;
- up to two legal add-ons may occur;
- full MA10 exit has priority;
- then eligible MA5 half exit;
- then add-on;
- three-session cooldown is retained;
- unresolved positions are liquidated at the 60-session campaign horizon.

Exact executable semantics remain documented in `IMPLEMENT.md`.

## 5. Campaign return and unique realized path

Initial campaign capital is normalized to 1.0.

```text
CampaignReturn = final_cash - 1.0
```

The historical observation unit is:

```text
one unique realized legal path = one independent historical observation
```

The same formal Entry may produce multiple unique legal paths because different legal historical-reference/add-on configurations can produce different execution sequences. These are intentionally retained rather than averaged away.

## 6. Path representation

Each realized path is represented by its capital-exposure / execution sequence:

```text
S_p(t) = invested fraction of capital at campaign session t
```

with the present 60-session campaign horizon:

```text
S_p in R^60
```

Example:

```text
[1/3, 1/3, 1/3, 2/3, 2/3, ..., 1/3, ..., 0, 0]
```

This sequence naturally contains timing information for Entry, add-ons, partial exits, full exit, holding duration, and exposure.

Therefore explicit add-on count, exit count, or timing vector are not redundantly fed as primary sequence inputs when the sequence already contains that information.

Each path is paired with its realized campaign return:

```text
(S_p, R_p)
```

Execution labels remain metadata for later descriptive analysis.

## 7. Fixed structural IO and legality mask

The standardized Layer-1 IO preserves fixed calendar positions, six coarse execution categories, multiple slots per calendar/category cell, and a legality/existence mask.

Coarse organizational categories:

```text
Add-on count: 0 / 1 / 2
Exit count:   1 / 2
```

which gives:

```text
(A0,E1) (A0,E2)
(A1,E1) (A1,E2)
(A2,E1) (A2,E2)
```

For each slot:

```text
w = 1 -> a legal realized path exists
w = 0 -> no path exists
```

This distinction remains essential:

```text
R = 0, w = 1 -> a legal zero-profit realized path
w = 0        -> absence of a path, not zero profit
```

The standardized IO preserves multiple independent paths in the same calendar/category cell by using a slot dimension rather than averaging them.

## 8. Path count `N(W)`

Define:

```text
N(W) = sum(w)
```

This is a descriptive property of the fixed-window data.

Current experiments show that even after removing explicit count input and normalizing the decoder target to unit mass, a one-dimensional latent remains strongly correlated with `N(W)`. This demonstrates that path occurrence/density is recoverable from the fixed-window path/mask structure itself.

At this stage this fact should **not** be converted into a design judgment such as:

```text
N is required
N is unnecessary
N is a nuisance
N is the meaning of z
```

The current conclusion is only:

> **Path density is an intrinsic observable component of the present fixed-window representation.**

## 9. Historical Strategy-1 descriptive evidence — SMH

Five-year scan:

```text
347 formal legal Entries
807 unique realized campaign paths
```

### By realized add-on count

| Add-ons | Paths | Distinct Entries | Mean return | Median return | Fraction positive |
|---|---:|---:|---:|---:|---:|
| 0 | 347 | 347 | +0.423% | +0.056% | 51.9% |
| 1 | 446 | 223 | +0.606% | -0.140% | 47.1% |
| 2 | 14 | 13 | +1.586% | -0.951% | 42.9% |

The two-add-on group is rare but spans a wide observed payoff range, approximately -8.67% to +10.86%.

### By partial-exit occurrence

| Partial exit occurred | Paths | Distinct Entries | Mean return | Median return | Fraction positive |
|---|---:|---:|---:|---:|---:|
| No | 253 | 146 | -1.377% | -1.031% | 11.9% |
| Yes | 554 | 264 | +1.421% | +1.239% | 66.1% |

These are descriptive associations only, not causal statements.

## 10. Realized outcome distribution and descriptive statistics

For one fixed interval `W`, define the realized return set:

```text
D_W = {R_p : w_p = 1}
```

Useful descriptive statistics include:

```text
L = min(D_W)
U = max(D_W)
mu = mean(D_W)
P(R > 0)
quantiles of D_W
N(W)
```

`L` and `U` are realized bounds. They are not training labels and are not predefined definitions of economic regime quality.

Likewise:

```text
P(R > 0) approximately 0.5
```

is only one descriptive condition. Calling it `neutral` is an intuitive shorthand, not an established property of the data.

The present research uses these statistics to help understand the learned representation. None is assumed in advance to be the correct summary of profitability.

## 11. L/U empirical window audit

The descriptive L/U audit was performed for multiple fixed windows. The current pilot interpretation focuses on `W=20,30,60`.

### W = 20

```text
valid windows: 990
empty windows: 187
all-negative: 316
all-positive: 142
mixed-sign: 532
```

`L` distribution:

| Statistic | Value |
|---|---:|
| min | -9.7951% |
| P05 | -9.1645% |
| P10 | -6.4216% |
| P25 | -4.6679% |
| P50 | -2.2215% |
| P75 | -1.0118% |
| P90 | +0.9338% |
| P95 | +2.1555% |
| max | +6.8458% |

`U` distribution:

| Statistic | Value |
|---|---:|
| min | -5.2151% |
| P05 | -4.1219% |
| P10 | -1.0849% |
| P25 | -0.2771% |
| P50 | +1.4897% |
| P75 | +4.7557% |
| P90 | +7.8073% |
| P95 | +9.6498% |
| max | +10.8580% |

### W = 30

```text
valid windows: 1092
empty windows: 75
all-negative: 301
all-positive: 84
mixed-sign: 707
```

`L`:

```text
P10 -7.9059%
P25 -4.9002%
P50 -2.8739%
P75 -1.3167%
P90 -0.4661%
P95 +1.2794%
```

`U`:

```text
P10 -1.0434%
P25 -0.2480%
P50 +2.6206%
P75 +6.0388%
P90 +9.0038%
P95 +10.7186%
```

### W = 60

```text
valid windows: 1137
empty windows: 0
all-negative: 190
all-positive: 1
mixed-sign: 946
```

`L`:

```text
P10 -9.7945%
P25 -5.7032%
P50 -4.6679%
P75 -2.8739%
P90 -2.0217%
P95 -1.0496%
```

`U`:

```text
P10 -0.2659%
P25 +0.7104%
P50 +4.6921%
P75 +7.0359%
P90 +10.7186%
P95 +10.8580%
```

As `W` increases, the observed minimum tends to become more negative and the maximum more positive because larger windows contain more paths. Therefore absolute `L/U` thresholds should not be assumed comparable across `W`.

The earlier use of conditions such as `L>0` or `U<0` as predefined favorable/unfavorable labels is withdrawn. These conditions remain descriptive facts only.

## 12. Autoencoder as a data-understanding tool

The current autoencoder is used to ask whether complex realized path/outcome data can be represented compactly without manually choosing a summary statistic first.

Conceptually:

```text
{(S_p, R_p, w_p)} in W
        -> encoder
        -> z_W
        -> decoder
        -> reconstructed realized-profit distribution
```

The learned latent `z_W` has no economic meaning imposed in advance.

The current validated pilot uses:

```text
W = 20, 30, 60
latent dimension = 1 for the latest interpretation study
41 profit bins
5 epochs
chronological purged train/test split
unit-mass profit-distribution target
no explicit count channel
```

The current target normalization and latent dimension are pilot choices, not frozen production definitions.

## 13. Compression evidence

Earlier latent-dimension ablation compared:

```text
d = 1, 2, 4, 8
```

Held-out reconstruction losses under the earlier raw-count target were:

| W | d=1 | d=2 | d=4 | d=8 |
|---:|---:|---:|---:|---:|
| 20 | 0.327 | 0.339 | 0.334 | 0.321 |
| 30 | 0.452 | 0.458 | 0.476 | 0.459 |
| 60 | 0.843 | 0.855 | 0.866 | 0.871 |

This provides evidence that the realized distribution data has a strong low-dimensional component: increasing latent dimension did not systematically improve held-out reconstruction in that pilot.

This does **not** establish that one dimension is the correct final representation, nor that additional dimensions are unnecessary. It only shows that a one-dimensional representation captured a large share of the reconstruction-relevant variation in this experiment.

## 14. Latest d=1 normalized-target interpretation experiment

The latest experiment removed two explicit count pathways:

```text
1. raw-count histogram target -> unit-mass distribution target
2. explicit per-cell count channel -> removed
```

The fixed-window path/mask structure remained unchanged.

Held-out one-dimensional latent correlations were:

| W | corr(z,L) | corr(z,U) | corr(z,N) | corr(z,mu) | corr(z,win rate) |
|---:|---:|---:|---:|---:|---:|
| 20 | +0.224 | +0.524 | +0.836 | +0.456 | +0.500 |
| 30 | -0.303 | -0.562 | -0.855 | -0.471 | -0.553 |
| 60 | -0.714 | -0.387 | -0.869 | -0.392 | -0.538 |

The sign of `z` is arbitrary and can flip between separately trained models. The relevant observation is that `z` is associated with several descriptive properties at once and is not numerically identical to any one of them.

This should be interpreted as evidence that the learned coordinate tracks a major source of variation in the realized outcome data. It should not yet be called a profitability score.

## 15. Latent ordering audit

To understand what the compressed representation corresponds to, held-out windows were sorted by one-dimensional `z` and divided into quintiles.

### W = 20

| z group | mean profit | win rate | mean L | mean U | mean N |
|---|---:|---:|---:|---:|---:|
| Q1 | -2.579% | 24.0% | -3.790% | -0.989% | 4.52 |
| Q2 | +0.068% | 43.8% | -2.138% | +2.714% | 13.17 |
| Q3 | +0.152% | 48.7% | -3.120% | +3.109% | 20.91 |
| Q4 | +1.750% | 76.0% | -0.931% | +4.914% | 23.47 |
| Q5 | +2.136% | 76.9% | -1.365% | +5.766% | 31.18 |

The ordering is accompanied by systematic changes in several realized-distribution properties at once.

### W = 30

Here the arbitrary latent sign is reversed relative to W=20.

| z group | mean profit | win rate | mean L | mean U | mean N |
|---|---:|---:|---:|---:|---:|
| Q1 | +2.185% | 76.0% | -1.805% | +6.725% | 40.88 |
| Q2 | +1.652% | 73.2% | -2.332% | +5.459% | 34.97 |
| Q3 | +1.498% | 68.0% | -1.358% | +4.368% | 27.00 |
| Q4 | -0.891% | 32.7% | -4.536% | +2.477% | 20.74 |
| Q5 | -2.063% | 27.5% | -4.167% | -0.234% | 7.30 |

Again, `z` ordering corresponds to broad changes across the realized distribution rather than only one statistic.

### W = 60

| z group | mean profit | win rate | mean L | mean U | mean N |
|---|---:|---:|---:|---:|---:|
| Q1 | +2.058% | 74.3% | -2.533% | +7.678% | 74.57 |
| Q2 | +1.328% | 68.4% | -2.877% | +6.221% | 57.95 |
| Q3 | +0.725% | 58.7% | -3.856% | +5.576% | 52.18 |
| Q4 | +1.133% | 61.4% | -3.838% | +6.297% | 47.52 |
| Q5 | +0.049% | 43.1% | -7.481% | +5.140% | 35.48 |

The relationship is structured but not perfectly monotonic across every statistic and every quintile.

The conservative conclusion from the ordering audit is:

> **The one-dimensional latent is associated with a broad, systematic transformation of the realized Strategy-1 outcome distribution.**

It is not yet established which single economic concept, if any, should be assigned to that transformation.

## 16. Similar-win-rate subset: descriptive observation only

A separate descriptive audit selected held-out windows satisfying:

```text
abs(P(R>0) - 0.5) <= 0.05
```

This selection was motivated by intuition and is **not** a privileged or validated `neutral regime` definition.

Observed low-z / high-z groups were:

| W | group | win rate | mean profit | mean L | mean U | mean N |
|---:|---|---:|---:|---:|---:|---:|
| 20 | low z | 47.8% | +0.769% | -1.858% | +5.077% | 12.08 |
| 20 | high z | 50.7% | +0.232% | -2.155% | +2.637% | 24.18 |
| 30 | low z | 51.2% | +0.198% | -2.850% | +3.795% | 31.36 |
| 30 | high z | 47.9% | +0.629% | -1.918% | +4.650% | 15.77 |
| 60 | low z | 51.9% | +0.132% | -5.436% | +5.083% | 62.22 |
| 60 | high z | 53.0% | +0.607% | -4.706% | +6.730% | 44.47 |

What this establishes is limited but useful:

> **Similar positive-return fractions can coexist with materially different realized payoff distributions.**

This shows that win rate alone does not describe the complete realized outcome structure.

It does **not** establish that the approximately-50% region is the most important region, a distinct natural regime, or the correct place to focus future modeling. Those ideas remain intuition until supported by broader evidence.

## 17. What is currently known about `z`

Current evidence supports the following descriptive statements:

1. A low-dimensional learned representation can reconstruct substantial structure in fixed-window realized outcome distributions.
2. One-dimensional `z` has systematic associations with multiple descriptive statistics including `L`, `U`, `mu`, `P(R>0)`, and `N`.
3. Sorting held-out windows by `z` produces visible changes in the realized distribution.
4. The sign of `z` is arbitrary across separately trained models.
5. `z` is not demonstrated to equal any single conventional statistic.
6. Similar win rates can correspond to different `L/U`, mean return, and distribution quantiles.
7. Relationships vary with `W`; the same interpretation should not automatically be transferred from `W=20` to `W=60`.

The current safest name for `z` is therefore:

```text
learned Strategy-1 realized-outcome representation
```

not:

```text
profitability score
good/bad score
neutrality score
regime label
```

## 18. Interpretation boundaries

The following conclusions are intentionally **not** established by the current experiments:

```text
N is required or unnecessary
N is a nuisance variable
one latent dimension is sufficient in general
more latent dimensions are required
P(R>0) near 0.5 defines a natural neutral regime
mixed-sign windows are intrinsically the most important windows
z is a profitability score
z has a fixed economic direction across models
L>0 means extreme good
U<0 means extreme bad
Layer 2 should now be added or changed
Q/C should be predicted from z
```

These may become future hypotheses, but they are not current findings.

## 19. Downstream C/Q terminology

For one Entry's realized legal return set:

```text
L = minimum realized campaign return
U = maximum realized campaign return
mu = mean realized campaign return
```

Downstream terminology remains:

```text
C = U - L
Q = (U - mu) / (U - L)
```

when the denominator is well-defined.

```text
C -> opportunity/capacity range
Q -> quality-gap ratio; lower means the realized mean lies closer to U relative to the observed range
```

These definitions remain useful downstream terminology, but they do not define the current Layer-1 autoencoder target and are not used to assign meaning to `z` in advance.

## 20. Validation principles

Any eventual predictive model must remain chronological and causal:

```text
past -> train
purge future-label overlap where necessary
later period -> validation/test
```

The current autoencoder experiment is historical representation learning, not a live causal predictor. Historical realized profits may therefore be used to understand the outcome distribution.

Heavily overlapping rolling windows must not be interpreted as independent evidence merely because the numerical sample count is large.

Facts and interpretations should remain separated:

```text
observed distribution / correlation / ordering -> fact
meaning assigned to that structure             -> interpretation
model-design consequence                        -> later decision
```

## 21. Current concise definition

> **The present Layer-1 work is a data-understanding study of Strategy 1's realized legal outcome distributions inside fixed historical calendar windows. Each legal path is represented by its execution/capital-exposure sequence and realized campaign return, with legality/path-occurrence structure preserved. An autoencoder is used as a compression tool rather than as a predefined profitability classifier. Current experiments show that the fixed-window outcome data contains strong low-dimensional structure: a one-dimensional latent can capture substantial reconstruction-relevant variation, and sorting held-out windows by that latent produces systematic changes in realized return bounds, mean return, positive-return fraction, path density, and distribution quantiles. Similar win rates can nevertheless correspond to different payoff distributions. These observations help describe the data, but they do not yet justify naming latent regions as good, bad, neutral, necessary, unnecessary, or assigning a final economic score to `z`. The current purpose is to understand what structure the data contains before making those decisions.**

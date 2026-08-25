# Strategy 1 — Entry Quality Framework

This document records the current Strategy 1 research framework while the target definition is being finalized.

## Core research question

> Under fixed Strategy 1 execution rules, can a model provide a useful causal score for the quality of the current legal entry?

The model target is intentionally **not yet finalized**.

## Current formal Strategy 1 research policy

The formal Reference Distribution policy is now fixed for the next phase of research:

```text
max_addons = 2
Addon2 realized-price spacing tolerance = ±20%
distribution weighting = unique realized paths
primary research window = 60D
robustness window = 90D
supporting windows = 30D, 45D
```

The earlier unrestricted Addon2 policy is retained only for historical reproducibility and policy comparison. It is no longer the formal research policy.

## Strategy 1 candidate sets used by Reference Distribution

Reference Distribution is built from candidate sets first, then formal legal Strategy 1 combinations.

### Entry Set

For Reference Distribution, an Entry candidate is **every session that satisfies the Strategy 1 entry condition on that session**.

The existing `entry1_event` transition definition is retained for legacy event-conditioned experiments, but it is not used to define the formal Reference Distribution Entry Set.

Current entry condition:

```text
Close > MA5
Close > MA10
Close > MA20
MA5 > MA10
MA10 > MA20
```

Therefore a multi-day run satisfying the entry condition contributes every qualifying session to the Entry Set rather than only the first newly-true day.

### Local-Maximum Set and Addition combinations

Addon1 / Addon2 are **not** rolling previous-20-session highest-close breakouts.

A confirmed close-price Local Maximum at session `i` is:

```text
Close[i] > Close[i-1]
Close[i] >= Close[i+1]
```

For each Entry candidate inside a fixed Reference Distribution window:

```text
1. scan all confirmed Local Maximum points already inside the fixed window and before the Entry,
2. build the Local Maximum candidate set,
3. allow a no-addition configuration,
4. allow every single-Local-Maximum addition-reference configuration,
5. allow every two-Local-Maximum configuration whose trading-index distance is > 5,
6. order a two-level configuration by recency: more recent reference first, older reference second,
7. execute Addon1 with the existing Strategy 1 breakout/cooldown mechanics,
8. allow Addon2 only when its realized execution price satisfies the formal equal-price-step rule below.
```

Formal Addon2 rule:

```text
first_gap  = Addon1Price - EntryPrice
second_gap = Addon2Price - Addon1Price

first_gap > 0
second_gap > 0
abs(second_gap / first_gap - 1) <= 0.20
```

Equivalent ratio form:

```text
0.8 <= (Addon2Price - Addon1Price) / (Addon1Price - EntryPrice) <= 1.2
```

### Why Addon2 is constrained

Policy-comparison results showed that unrestricted Addon2 increased the achievable upper tail, but it also materially worsened the lower tail and reduced pooled efficiency. The ±20% equal-price-step rule removed almost all of that downside deterioration while preserving a small amount of additional upside.

The formal interpretation is therefore:

```text
Addon1 = normal optional addition
Addon2 = rare, high-condition second addition
```

Addon2 is not expected to occur frequently.

### Exit Set

Reference Distribution also scans all sessions satisfying the existing exit conditions:

```text
Close < MA5  -> Exit5 candidate
Close < MA10 -> Exit10 candidate
```

These full candidate sets are reported for audit. However, a legal combination still executes exits with the existing Strategy 1 event timing, priority, and spacing rules rather than allowing future knowledge to arbitrarily skip an actionable exit.

Current execution priority remains:

```text
eligible MA10 full exit > eligible MA5 half exit > addon action
```

### Trading spacing

The existing three-session trading restriction remains part of every simulated combination. Existing horizon-end forced liquidation behavior also remains unchanged.

## Distribution weighting

Different legal configurations can collapse to the same actual trading path. The formal Reference Distribution therefore weights **unique realized paths**, not raw configuration multiplicity.

Realized-path key:

```text
Entry
actual Addon1 execution
actual Addon2 execution
Exit5 execution
Exit10 execution
Horizon exit
```

If multiple legal configurations produce the same realized-path key, that path is counted once in the distribution.

This prevents configurations that collapse to the same execution path from artificially dominating mean, median, win-rate, variance, or efficiency statistics.

## Four definitions currently under discussion

Do not introduce additional conceptual objects until these four are clear.

### 1. Market Opportunity

To be described using the Reference Bounds and the return distribution of formal legal realized paths inside a fixed future window. No additional market-opportunity indicator is currently defined.

### 2. Current Entry Quality

This is the conceptual quantity we ultimately want the model to identify: whether the current entry is close to the best achievable legal realized-path quality available inside the relevant Reference Bounds.

Its mathematical learning target is not yet defined.

### 3. Reference Bounds

For a fixed future window:

```text
Entry Set     = every session satisfying the entry condition
Local Max Set = confirmed Local Maximum candidates before each Entry
Exit Set      = sessions satisfying the exit conditions
Combination   = Entry × legal optional Addition-reference configuration,
                with max 2 additions and formal Addon2 spacing ±20%,
                executed with Strategy 1 exit/spacing mechanics
```

Let every unique formal legal realized path produce one realized Strategy 1 return.

```text
Lower Bound = minimum realized return over all formal legal realized paths
Upper Bound = maximum realized return over all formal legal realized paths
Reference Bounds = [Lower Bound, Upper Bound]
```

The earlier terminology `Baseline` / `Oracle` is no longer assumed to be the final representation of the bounds.

Reference Distribution Data reports:

```text
Entry candidate count
Local Maximum candidate count
Exit5 candidate count
Exit10 candidate count
Legal configuration count
Unique realized-path count
Dedup ratio
Addon2 realized-path rate

Return distribution:
Lower Bound
Upper Bound
Mean
Median
STD
P25
P75
IQR
Win rate

Efficiency distribution:
Lower Bound
Upper Bound
Mean
Median
STD
P25
P75
IQR
Positive rate
Aggregate efficiency
Pooled efficiency
```

Efficiency remains:

```text
realized return / capital-weighted exposure days
```

These values are descriptive references, not model inputs.

### 4. Model target

Unknown. Do not force Rule Return, Upper Bound, Lower Bound, range, ratio, gap, classification, or ranking into the target until Current Entry Quality is defined against the formal Reference Distribution.

## Current Reference Distribution findings

The current five-year SPY run covers 2021-08-25 through 2026-08-25 and compares 30D / 45D / 60D / 90D windows.

### Primary 60D window

60D is the current primary research window because it has full nonempty coverage while keeping the realized-path universe materially smaller than 90D.

Current formal 60D summary:

```text
anchors = 1166
nonempty_rate = 1.000
entry_candidates_mean = 19.776
legal_combinations_mean = 606.932
realized_paths_mean = 33.195
dedup_ratio_mean = 0.0875
addon2_path_rate_mean = 0.0048

Return:
lower_mean = -0.019509
upper_mean = 0.013404
mean_mean = -0.001250
median_mean = -0.000307
std_mean = 0.008689
iqr_mean = 0.010005
win_rate_mean = 0.467

Efficiency:
mean_mean = -0.000458
median_mean = -0.000113
aggregate_efficiency_mean = -0.000255
pooled_efficiency = 0.000153
```

### 60D realized Addon groups

```text
0 Addon:
realized_paths_mean = 19.776
return_mean = -0.001039
win_rate_mean = 0.417
efficiency_pooled = 0.000088

1 Addon:
realized_paths_mean = 13.222
return_mean = -0.001944
win_rate_mean = 0.535
efficiency_pooled = 0.000160

2 Addons:
realized_paths_mean = 0.196
realized_paths_median = 0
return_mean = 0.014318
return_median = 0.013946
win_rate_mean = 0.837
efficiency_pooled = 0.001652
```

Interpretation: formal Addon2 is rare, but when it occurs it is associated with high-return/high-efficiency realized paths. Because this is a conditional realized-path subset, these statistics are descriptive and should not be interpreted as causal proof that Addon2 creates the return.

### Window interpretation

```text
30D = supporting window; Addon2 is effectively absent
45D = supporting window; Addon2 begins to appear but remains very rare
60D = primary research window
90D = robustness / longer-horizon reference
```

90D remains useful because it shows whether conclusions persist with more time for additions and exits to develop. It is not currently the primary target window because the realized-path universe and tail dispersion expand materially relative to 60D.

The 90D formal distribution also shows a slightly positive mean window-level median return, which indicates that longer horizons shift the center of the distribution upward, but this comes with wider bounds and larger dispersion.

## Reference Distribution CLI

The formal commands are:

```text
futureview-strategy1-reference-distribution
futureview-strategy1-reference-distribution-fast
```

Both represent:

```text
research_version = formal_max2_spacing20
distribution_weighting = unique_realized_paths
```

Historical unrestricted Reference Distribution code remains available for reproducibility and policy-comparison work, but it is not the formal research definition.

## Compatibility guardrail

Legacy Strategy 1 event-conditioned runners retain `entry1_event` and the default nearest-two-local-max execution behavior. Historical unrestricted Addon2/reference-distribution code remains available for reproducibility and policy comparison. The formal Reference Distribution CLI uses max2 + Addon2 spacing ±20% with unique-realized-path weighting.

## Current data scope

The historical source period remains capped at five years for the current research branch.

## Current research decision

Strategy-rule tuning is paused here. Do not continue optimizing Addon2 tolerance unless new evidence specifically requires reopening the policy comparison.

The next research question is:

> How should Current Entry Quality be defined mathematically from the 60D formal Reference Distribution?

Before returning to model training:

```text
1. keep the formal Strategy 1 policy fixed at max2 + spacing20,
2. use 60D as the primary Reference Distribution window,
3. use 90D as robustness context,
4. use unique realized paths for distribution statistics,
5. define Current Entry Quality against the formal 60D Reference Distribution,
6. only then define the mathematical model target.
```

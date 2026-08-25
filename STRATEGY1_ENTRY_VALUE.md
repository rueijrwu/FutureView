# Strategy 1 — Entry Quality Framework

This document records the current Strategy 1 research framework while the target definition is being finalized.

## Core research question

> Under fixed Strategy 1 execution rules, can a model provide a useful causal score for the quality of the current legal entry?

The model target is intentionally **not yet finalized**.

## Strategy 1 candidate sets used by Reference Distribution

Reference Distribution is built from candidate sets first, then legal Strategy 1 combinations. The current formal research policy is **max 2 additions with a realized-price Addon2 spacing tolerance of ±20%**.

### Entry Set

For Reference Distribution, an Entry candidate is **every session that satisfies the Strategy 1 entry condition on that session**.

The existing `entry1_event` transition definition is retained for legacy event-conditioned experiments, but it is not used to define the new Reference Distribution Entry Set.

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

This is the current formal Strategy 1 research policy. The earlier unrestricted Addon2 behavior remains available only for historical/policy-comparison work.

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

## Four definitions currently under discussion

Do not introduce additional conceptual objects until these four are clear.

### 1. Market Opportunity

To be described using the Reference Bounds and the return distribution of formal legal realized paths inside a fixed future window. No additional market-opportunity indicator is currently defined.

### 2. Current Entry Quality

This is the conceptual quantity we ultimately want the model to identify: whether the current entry is close to the best achievable legal combination quality available inside the relevant Reference Bounds.

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

Unknown. Do not force Rule Return, Upper Bound, Lower Bound, range, ratio, gap, classification, or ranking into the target until the Reference Distribution Data is understood.

## Reference Distribution Data

The preferred name for the initial descriptive dataset is **Reference Distribution Data**, not `baseline data`, because it describes the distribution of formal legal Strategy 1 realized paths rather than a baseline model.

The future-window length is a research parameter. Current candidate windows are:

```text
30D
45D
60D
90D
```

The purpose is to see how the candidate sets, legal combinations, realized paths, bounds, return distribution, and efficiency distribution behave as the window grows before choosing a window for Current Entry Quality modeling.

## Compatibility guardrail

Legacy Strategy 1 event-conditioned runners retain `entry1_event` and the default nearest-two-local-max execution behavior. Historical unrestricted Addon2/reference-distribution code remains available for reproducibility and policy comparison. The formal Reference Distribution CLI now uses max2 + Addon2 spacing ±20% with unique-realized-path weighting.

## Current data scope

The historical source period remains capped at five years for the current research branch.

## Current rule

Before returning to model training:

```text
1. audit the expanded Entry / Local Maximum / Exit candidate sets,
2. calculate formal max2 + spacing20 Reference Distribution Data,
3. inspect how bounds, realized-path counts, and efficiency change as the window grows,
4. use unique realized paths rather than raw configuration multiplicity for distribution statistics,
5. only then define the mathematical model target.
```

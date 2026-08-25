# Strategy 1 — Entry Quality Framework

This document records the current Strategy 1 research framework while the target definition is being finalized.

## Core research question

> Under fixed Strategy 1 execution rules, can a model provide a useful causal score for the quality of the current legal entry?

The model target is intentionally **not yet finalized**.

## Strategy 1 candidate sets used by Reference Distribution

Reference Distribution is built from candidate sets first, then legal Strategy 1 combinations.

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
7. execute the resulting Addon1 / Addon2 crossings using the existing Strategy 1 transaction rules.
```

This makes Addition optional in the Reference Distribution combination universe without yet removing Addition from Strategy 1. It also makes it possible to compare later whether no-addition combinations preserve or improve the reference distribution.

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

To be described using the Reference Bounds and the return distribution of all legal combinations inside a fixed future window. No additional market-opportunity indicator is currently defined.

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
                executed with Strategy 1 exit/spacing mechanics
```

Let every legal combination produce one realized Strategy 1 return.

```text
Lower Bound = minimum realized return over all legal combinations
Upper Bound = maximum realized return over all legal combinations
Reference Bounds = [Lower Bound, Upper Bound]
```

The earlier terminology `Baseline` / `Oracle` is no longer assumed to be the final representation of the bounds.

Reference Distribution Data initially reports:

```text
Entry candidate count
Local Maximum candidate count
Exit5 candidate count
Exit10 candidate count
Legal combination count

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

The preferred name for the initial descriptive dataset is **Reference Distribution Data**, not `baseline data`, because it describes the distribution of legal Strategy 1 combinations rather than a baseline model.

The future-window length is a research parameter. Current candidate windows are:

```text
30D
45D
60D
90D
```

The purpose is to see how the candidate sets, legal combinations, bounds, return distribution, and efficiency distribution behave as the window grows before choosing a window for Current Entry Quality modeling.

## Compatibility guardrail

Legacy Strategy 1 event-conditioned runners retain `entry1_event` and the default nearest-two-local-max execution behavior. The exhaustive candidate-set logic is added specifically for Reference Distribution so earlier evidence is not silently rewritten.

## Current data scope

The historical source period remains capped at five years for the current research branch.

## Current rule

Before returning to model training:

```text
1. audit the expanded Entry / Local Maximum / Exit candidate sets,
2. calculate legal-combination Reference Distribution Data,
3. inspect how bounds and efficiency change as the window grows,
4. compare future no-addition subsets against the full combination universe if needed,
5. only then define the mathematical model target.
```

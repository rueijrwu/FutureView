# Strategy 1 — Entry Quality Framework

This document records the current Strategy 1 research framework while the target definition is being finalized.

## Core research question

> Under fixed Strategy 1 execution rules, can a model provide a useful causal score for the quality of the current legal entry?

The model target is intentionally **not yet finalized**.

## Fixed Strategy 1 mechanics used by this research

Strategy 1 is defined from the perspective of entering on a legal Entry1 date and then following the already-specified campaign rules. The research layer must not redefine these mechanics.

### Entry1

The legal Entry1 condition is based on the 5/10/20-day moving-average trend structure already defined by Strategy 1.

### Local-maximum set and Addon reference levels

Addon1 / Addon2 are **not** rolling previous-20-session highest-close breakouts.

At each legal Entry1 close:

```text
1. use only price history observable through the Entry1 close,
2. identify confirmed prior close-price Local Maximum points,
3. form the prior Local Maximum set,
4. select the nearest prior Local Maximum,
5. select the nearest earlier Local Maximum whose trading-date distance
   from the first is strictly greater than 5 trading sessions,
6. lock those two Local Maximum prices at Entry1,
7. use the locked levels for Addon1 / Addon2 according to Strategy 1.
```

Current implementation defines a confirmed prior close-price Local Maximum at session `i` as:

```text
Close[i] > Close[i-1]
Close[i] >= Close[i+1]
```

The Entry1 session itself is never a Local Maximum candidate. The definition is causal because every value used to confirm a prior maximum is already known by the Entry1 close.

The two selected reference levels are ordered by recency:

```text
Addon1 reference = nearest prior eligible Local Maximum
Addon2 reference = next-nearest prior Local Maximum with index gap > 5
```

Once Entry1 occurs, the selected levels are frozen for that campaign; they are not replaced by future rolling highs.

### Exit

The existing Strategy 1 exit rules remain fixed:

```text
Close < MA5  -> sell 50% of the current position
Close < MA10 -> exit the remaining position
```

If both exit conditions become actionable together, the full-exit rule has priority according to the existing Strategy 1 mechanics.

### Trading spacing

The existing three-session trading restriction remains part of Strategy 1. Existing horizon-end forced liquidation behavior also remains unchanged.

### Research guardrail

The Strategy 1 entry/addon/exit/spacing mechanics are fixed infrastructure. Reference-distribution, model-target, and evaluation definitions must be built on top of them and must not silently alter them.

## Four definitions currently under discussion

Do not introduce additional conceptual objects until these four are clear.

### 1. Market Opportunity

To be described using the Reference Bounds and the return distribution of all legal entries inside a fixed future window. No additional market-opportunity indicator is currently defined.

### 2. Current Entry Quality

This is the conceptual quantity we ultimately want the model to identify: whether the current entry is close to the best achievable entry quality available inside the relevant Reference Bounds.

Its mathematical learning target is not yet defined.

### 3. Reference Bounds

For a fixed future window, construct an `Entry Set` containing every legal Strategy 1 Entry1 inside that window. Run every entry with the same Strategy 1 mechanics.

```text
Lower Bound = worst realized Strategy 1 return in the Entry Set
Upper Bound = best realized Strategy 1 return in the Entry Set
Reference Bounds = [Lower Bound, Upper Bound]
```

The earlier terminology `Baseline` / `Oracle` is no longer assumed to be the final representation of the bounds.

The return distribution of the Entry Set should initially be described with simple statistics only:

```text
Entry count
Lower Bound
Upper Bound
Mean
Median
STD
P25
P75
IQR
Win rate
```

These values are descriptive references, not model inputs.

### 4. Model target

Unknown. Do not force Rule Return, Upper Bound, Lower Bound, range, ratio, gap, classification, or ranking into the target until the Reference Distribution Data is understood.

## Reference Distribution Data

The preferred name for the initial descriptive dataset is **Reference Distribution Data**, not `baseline data`, because it describes the distribution of Strategy 1 returns available from the legal Entry Set rather than a baseline model.

The future-window length is currently a research parameter rather than a fixed 30D assumption. Initial candidate windows may include:

```text
30D
45D
60D
90D
```

The purpose is to see how the Entry Set and its Reference Bounds behave as the window grows before choosing a window for Current Entry Quality modeling.

## Current data scope

The historical source period remains capped at five years for the current research branch.

## Current rule

Before returning to model training:

```text
1. verify the corrected Local Maximum addon implementation,
2. calculate Reference Distribution Data for candidate future windows,
3. inspect whether the bounds/distribution stabilize as the window grows,
4. only then define the mathematical model target.
```

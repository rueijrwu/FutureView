# Strategy 1 — Entry Horizon Baseline

This baseline answers whether 30D remains the most effective horizon after changing the learning problem from Oracle prediction to scoring the realized return of the current legal Entry1.

No model is trained in this baseline. Oracle remains benchmark only.

## Comparison design

The comparison uses the same legal Entry1 dates across all horizons.

```text
period = 5y
lookback eligibility = 50 daily sessions
horizons = 15 / 30 / 45 / 60 trading sessions
common-event requirement = every sample has a complete 60D future window
sample = legal Strategy 1 Entry1 event
model = none
```

Using common dates prevents horizon-specific sample availability from contaminating the comparison.

For each common Entry1 event and each horizon:

```text
EntryReturn(h)
  realized return from taking this exact Entry1 and following frozen Strategy 1

OracleValue(h)
  future-known best legal single Strategy 1 campaign in the same horizon

OracleRegret(h)
  OracleValue(h) - EntryReturn(h)
```

Dataset invariants require Oracle to dominate the current legal entry.

## Metrics

Raw horizon metrics:

```text
EntryReturn mean / median / p10 / p90
entry win rate / loss rate
mean exposure days
mean holding days
mean entries used
all-three-entries rate
OracleValue mean
Oracle positive-opportunity rate
OracleRegret mean / median / p90
Oracle exact-match rate (numerical epsilon only)
```

Efficiency metrics:

```text
mean EntryReturn / horizon days
mean EntryReturn / capital-weighted exposure days
mean OracleValue / Oracle exposure days
```

The horizon-day normalization is descriptive only. Exposure-day efficiency is preferred because Strategy 1 can be partially invested and can exit before the horizon boundary.

## Paired comparison against 30D

Because all horizons use exactly the same Entry1 dates, the runner also reports event-by-event comparisons:

```text
mean EntryReturn(h) - EntryReturn(30D)
fraction of events where h has higher EntryReturn than 30D
fraction of equal EntryReturn outcomes
mean OracleRegret(h) - OracleRegret(30D)
fraction of events where h has lower regret than 30D
```

## Important finding — strategy headroom must be separated from model skill

The current research now distinguishes two different questions:

```text
1. Strategy headroom:
   Given this symbol and the frozen Strategy 1 legal mechanics,
   how much economically meaningful outcome separation exists to exploit?

2. Model skill:
   Given only causal information available at Entry,
   can the model identify Entries associated with better future L / mu / U outcomes?
```

These questions must not be merged.

A model cannot create predictive separation that does not exist inside the strategy-defined outcome space. If Strategy 1 itself provides little incremental timing value for a symbol, weak model separation on that symbol is not automatically evidence that the model failed. Conversely, a large Strategy 1 L/U spread does not by itself prove that the model can predict which side of the spread will occur from causal data.

### Why this matters for SPY / QQQ / SMH

The 5-year 60D fixed-entry comparison ending 2026-08-25 shows that the external fixed three-entry baseline can be competitive with, and in mean return can exceed, the formal Strategy 1 Upper Bound because the fixed baseline is outside the Strategy 1 legal path set.

```text
60D fixed three-entry baseline: Day 0 / Day 20 / Day 40, equal capital, hold to horizon
Strategy Upper Bound: best formal legal realized Strategy 1 path
```

Observed mean returns:

| Symbol | Strategy 1 Upper mean | Fixed three-entry mean | Upper beats fixed rate |
|---|---:|---:|---:|
| SPY | +1.34% | +1.85% | 35.2% |
| QQQ | +2.08% | +2.42% | 40.8% |
| SMH | +3.72% | +5.72% | 41.8% |

This does **not** mean the fixed baseline is a new Upper Bound. It means the Strategy 1 Upper Bound is only an upper bound *inside Strategy 1's own legal path space*.

Therefore:

```text
Strategy 1 Upper Bound != market opportunity ceiling
Strategy 1 Upper Bound != best possible investment outcome
Strategy 1 Upper Bound != model-achievable return
```

The result also means that observed SPY / QQQ / SMH differences cannot be attributed only to symbol volatility. The frozen Strategy 1 rules impose their own preferences and constraints, and those rules interact differently with each symbol.

### Current interpretation

SPY has a narrower Strategy 1 entry-value distribution and a simple fixed-entry baseline that is already highly competitive. This suggests that Strategy 1 may offer relatively limited incremental timing headroom on SPY under the current rules.

QQQ and SMH show larger absolute L/U/mu outcome amplitudes, but this should not automatically be called greater model opportunity. Some of that spread can come from symbol volatility, and some from the way Strategy 1 interacts with those price paths.

The correct research sequence is now:

```text
A. Measure symbol + Strategy 1 outcome structure.
B. Measure strategy-relative timing headroom against simple external baselines.
C. Only then evaluate whether a causal model captures that headroom OOS.
```

This distinction is a major interpretation rule for future model evaluation.

## Interpretation

There is no arbitrary composite score. `30D` should only be called the most effective baseline horizon if the evidence is favorable across the economically relevant dimensions, especially:

```text
realized EntryReturn
win rate
EntryReturn per exposure day
OracleRegret
Oracle match rate
```

Longer horizons should not be declared superior only because they have more calendar time to accumulate raw return.

## Run

```bash
futureview-strategy1-entry-horizon-baseline
```

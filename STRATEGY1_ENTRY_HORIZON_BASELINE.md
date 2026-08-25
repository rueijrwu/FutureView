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

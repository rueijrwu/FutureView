# Strategy 1 — Current Research Summary

## Status

Current formal research version:

```text
research_version=formal_max2_spacing20
primary_window=60D
robustness_window=90D
distribution_weighting=unique_realized_paths
model_target=not_defined
```

Strategy-rule tuning is paused. The next research task is to define **Current Entry Quality** from the formal Reference Distribution, then define the model target.

## Entry Set

A Reference Distribution Entry candidate is every session satisfying:

```text
Close > MA5
Close > MA10
Close > MA20
MA5 > MA10
MA10 > MA20
```

This is not limited to the first newly-true transition. Legacy `entry1_event` remains for older experiments only.

## Addition Set

A confirmed local maximum at session `i` is:

```text
Close[i] > Close[i-1]
Close[i] >= Close[i+1]
```

For each Entry candidate, scan all confirmed local maxima inside the fixed window and before Entry. Legal addition-reference configurations are:

```text
no addon
one local-max reference
two local-max references with index gap > 5
```

The more recent reference is Addon1 and the older reference is Addon2.

### Formal Addon2 rule

Addon2 is allowed only when the realized price steps are positive and approximately equal:

```text
first_gap  = Addon1Price - EntryPrice
second_gap = Addon2Price - Addon1Price

first_gap > 0
second_gap > 0
abs(second_gap / first_gap - 1) <= 0.20
```

Equivalent:

```text
0.8 <= second_gap / first_gap <= 1.2
```

The earlier unrestricted Addon2 policy was rejected as the formal rule because it increased upside but deteriorated downside and efficiency too much. Its implementation has been removed from the active worktree; Git history retains the experiment.

## Exit Set and execution

Audit candidate sets:

```text
Close < MA5  -> Exit5 candidate
Close < MA10 -> Exit10 candidate
```

Execution remains deterministic under existing Strategy 1 mechanics:

```text
eligible MA10 full exit
> eligible MA5 half exit
> addon action
```

The three-session trading cooldown and horizon-end liquidation remain unchanged.

## Reference Distribution

For a fixed future window:

```text
Entry Set     = all qualifying Entry sessions
Local Max Set = all confirmed local maxima before each Entry
Combination   = Entry × legal optional addon-reference configuration
Execution     = formal max2 + spacing20 Strategy 1 rules
```

Different legal configurations can produce the same actual trading path. Distribution statistics therefore use **unique realized paths**, not raw configuration multiplicity.

Realized-path key:

```text
Entry
actual Addon1 execution
actual Addon2 execution
Exit5 execution
Exit10 execution
Horizon exit
```

Reference Bounds:

```text
Lower Bound = minimum return across formal legal realized paths
Upper Bound = maximum return across formal legal realized paths
```

Efficiency:

```text
realized return / capital-weighted exposure days
```

## Window choice

Current windows:

```text
30D  supporting
45D  supporting
60D  primary research window
90D  robustness / longer-horizon reference
```

60D is the main window because it has full nonempty coverage and enough Entry / Addon1 / Exit structure without the broader dispersion of 90D. Addon2 is effectively absent at 30D and remains a rare event at longer windows.

## Formal 60D result

Five-year SPY sample, 2021-08-25 through 2026-08-25:

```text
anchors                    1166
nonempty_rate              1.000
entry_candidates_mean      19.776
local_max_candidates_mean  132.809
legal_combinations_mean    606.932
realized_paths_mean        33.195
dedup_ratio_mean           0.0875
addon2_path_rate_mean      0.0048

Lower Bound mean           -0.019509
Upper Bound mean            0.013404
Return mean                -0.001250
Return median              -0.000307
Win rate                    0.467
Pooled efficiency           0.000153
```

Realized-path composition:

```text
0 addon paths mean   19.776
1 addon paths mean   13.222
2 addon paths mean    0.196
```

Interpretation: Strategy 1 is primarily Entry-only or Entry + Addon1. Formal Addon2 is intentionally a rare, high-condition event rather than a routine second deployment.

## 90D robustness result

```text
realized_paths_mean        54.961
addon2_path_rate_mean      0.0082
Lower Bound mean           -0.025370
Upper Bound mean            0.018077
Return mean                -0.000847
Return median               0.000367
Win rate                    0.485
Pooled efficiency           0.000137
```

The longer window improves the distribution center but widens the range and tail exposure, so 90D remains a robustness reference rather than the primary window.

## Current research question

The execution framework is now fixed enough to move back to modeling.

Next question:

> Given the 60D formal Reference Distribution, how should **Current Entry Quality** be defined causally for the current Entry?

Do not force Upper Bound, Lower Bound, return, regret, classification, ranking, or another target before this definition is explicit.

## Active commands

```bash
futureview-strategy1-reference-distribution
futureview-strategy1-reference-distribution-fast
```

The fast command uses the same formal semantics with a bounded Numba simulation cache.

## Compatibility

Legacy Strategy 1 event-conditioned/model research remains in the repository unless separately removed. Historical Reference Distribution policy-comparison code is available through Git history rather than active scripts.

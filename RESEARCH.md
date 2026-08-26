# FutureView — Research Definition, Evidence, and Current Direction

Last consolidated: 2026-08-26

This is the canonical research document for FutureView. It consolidates the conceptual framework, Strategy 1 definition, target definitions, historical evidence, and current research direction. Implementation details, commands, architecture, data-provider details, and CI mechanics belong in `IMPLEMENT.md`.

## 1. Current research question

The current work is deliberately simplified. We are not adding another model layer. We are revisiting the **pre-filter / gate** in the existing FutureView training framework.

The central question is:

> Given the complete set of known historical Strategy 1 paths and their realized campaign profits in a historical interval, can the profitability structure of that interval be represented as a small number of useful states/classes without manually declaring that one summary statistic means "good" or "bad"?

The motivation is the earlier pre-filter bottleneck. A historical interval may contain many legal Entries or very few, and each Entry may have one or more legal realized paths. Mean return, win rate, standard deviation, Entry count, μ, or another single statistic may fail to represent the full economic structure of the interval. We therefore do not want to define the gate by an arbitrary threshold on one such statistic before examining the full path-level outcome data.

A central methodological rule remains: no new threshold, window, maturity rule, normalization, derived statistic, class weighting, resampling rule, or other modeling assumption is introduced silently. Descriptive statistics may be used to understand the data, but are not automatically model inputs, labels, or trading rules.

## 2. Existing model framework

The intended overall framework remains conceptually simple:

```text
normalized causal price/volume
        -> pre-filter / gate
        -> C/Q entry-quality model
```

The present research concerns only the **pre-filter**. We are not introducing an additional historical-analysis layer, refine layer, planning layer, or extra sequential CNN into the production architecture.

The later C/Q model remains a separate entry-quality problem. The present task is to determine what the pre-filter should mean and how historical Strategy 1 profitability should define its states.

## 3. Strategy-relative research object

Strategy 1 defines the legal trading/campaign space. Historical realized data then provides the observed outcomes of those legal campaigns.

The basic research object is therefore not a manually constructed technical indicator. It is the collection of legal realized Strategy 1 paths and their realized campaign returns.

For a historical interval `W`:

```text
P(W) = {(path_i, R_i)}
```

where `path_i` is one unique legal realized Strategy 1 execution path and `R_i` is its realized campaign return.

The unresolved pre-filter problem is how the full structure of `P(W)` should determine the profitability state/class of interval `W`.

## 4. Frozen Strategy 1 research mechanics

Strategy 1 is long-only and uses daily close information. The current formal research version uses three equal capital tranches and one campaign per evaluation window.

A formal Entry candidate satisfies:

```text
Close > MA5
Close > MA10
Close > MA20
MA5 > MA10
MA10 > MA20
```

All qualifying sessions are formal Entry candidates in the current entry-level research definition.

The campaign begins with one one-third-capital Entry. Depending on the legal historical-reference/add-on configuration and subsequent realized prices, it may have zero, one, or two add-ons. Each add-on uses another one-third of initial capital. Execution priority remains full MA10 exit, then eligible MA5 half exit, then add-on. Three-session cooldown and horizon-end liquidation remain part of the current executable strategy.

The exact executable semantics are documented in `IMPLEMENT.md`.

## 5. Campaign return and path-level data unit

For one legal realized campaign, initial capital is normalized to 1.0. Entry/add-on purchases convert the relevant one-third capital tranche into shares at the realized execution price. Partial/full exits convert shares back into cash.

The realized campaign return is:

```text
CampaignReturn = final_cash - 1.0
```

This is a portfolio-level return on initial normalized capital, not simply `(exit price - first entry price) / first entry price`.

The fundamental historical data unit is now explicitly:

```text
one unique realized legal path = one independent historical observation
```

The same formal Entry may therefore appear in multiple independent path observations when different legal reference/add-on configurations produce different realized execution paths. This is intentional and is not treated as a duplicate-data error.

Each path retains its own factual labels/metadata, including where applicable:

```text
Entry
reference/add-on configuration
executed add-on count
partial-exit occurrence
terminal exit
campaign return
execution sequence / event locations
```

These factual path labels are preserved so that later analysis can determine which execution structures are associated with which profitability states. They are not automatically input features and are not themselves definitions of "good" or "bad".

## 6. Historical campaign-structure analysis — SMH

A five-year descriptive scan of the current SMH Strategy 1 implementation produced:

```text
347 formal legal Entries
807 unique realized campaign paths
```

This analysis is descriptive only. The statistics below are not approved gate inputs or thresholds.

### By realized add-on count

| Add-ons | Paths | Distinct Entries | Mean return | Median return | Fraction positive |
|---|---:|---:|---:|---:|---:|
| 0 | 347 | 347 | +0.423% | +0.056% | 51.9% |
| 1 | 446 | 223 | +0.606% | -0.140% | 47.1% |
| 2 | 14 | 13 | +1.586% | -0.951% | 42.9% |

The two-add-on group is rare, but its observed payoff range is very wide, approximately -8.67% to +10.86%. Its positive mean together with negative median demonstrates why a single summary statistic can be misleading: a small number of economically large outcomes can coexist with a negative typical outcome.

Rarity is therefore not automatically evidence that a state is unimportant. Rare but economically large paths are retained rather than discarded merely because their count is small.

### By partial-exit occurrence

| Partial exit occurred | Paths | Distinct Entries | Mean return | Median return | Fraction positive |
|---|---:|---:|---:|---:|---:|
| No | 253 | 146 | -1.377% | -1.031% | 11.9% |
| Yes | 554 | 264 | +1.421% | +1.239% | 66.1% |

This is a strong descriptive association, not a causal claim that partial exit creates profit. The same realized future price path affects both campaign return and whether a partial-exit event occurs.

Partial exit is therefore retained as factual path metadata useful for interpreting discovered profitability states, rather than being declared in advance to be a "good" class.

### Terminal exit

806 of 807 realized paths ended through the normal full-exit mechanism; only one ended at the horizon. Terminal-exit type therefore currently contains little independent variation.

## 7. The pre-filter problem

The earlier pre-filter work attempted to summarize historical strategy quality through quantities such as μ or related fixed statistical rules. The current concern is that this may impose the answer before the model has seen the full structure of the realized outcomes.

For an interval `W`, suppose the known historical Strategy 1 outcomes are:

```text
P(W) = {(p_1, R_1), (p_2, R_2), ..., (p_n, R_n)}
```

A conventional approach might first reduce these data to:

```text
mean(R)
standard deviation(R)
win rate
median(R)
Entry count
path count
```

and then define a gate such as `mean(R) > threshold`.

That is not the current intended direction. Such quantities remain useful for inspection, but we do not yet know which statistic, combination of statistics, or threshold correctly represents whether Strategy 1 is suitable in an interval.

The research goal is instead to preserve enough of the complete path/profit structure for distinct profitability states to be identified from the data.

## 8. Profitability-state classification

The intended pre-filter target is a **profitability state/class of a historical interval**, not an add-on class and not a partial-exit class.

Conceptually:

```text
all known Strategy 1 paths + realized profits in interval W
        -> profitability structure/state of W
```

The classes should not initially be defined by an arbitrary rule such as:

```text
mean return > x  => good
win rate > y     => good
μ > z            => good
```

because that would simply encode a human-selected statistic into the gate.

Instead, the current research question is whether the complete path/profit structure naturally supports a small number of economically distinct states. Possible structures could include, purely as examples and not predefined labels:

```text
consistently poor outcomes
mixed / low-information outcomes
broadly favorable outcomes
rare but very high-payoff outcomes
```

These examples are explanatory only. The number of classes and their boundaries are not yet frozen.

After states are identified, existing path labels such as add-on count and partial-exit occurrence can be used to interpret them. For example, we may ask whether a discovered high-profitability state contains disproportionate numbers of partial-exit paths or rare two-add-on paths. That is post-hoc interpretation of a state, not the definition of the state itself.

## 9. Important distinction: historical state definition vs causal prediction

The current work is first concerned with defining and understanding the pre-filter target from known historical outcomes.

This should not be confused with the later causal prediction problem.

Historical target-definition question:

```text
known realized Strategy 1 paths + profits
        -> what profitability state did this interval actually represent?
```

Later pre-filter prediction question:

```text
information available at decision time
        -> can the model predict that profitability state?
```

These are two stages of studying the same pre-filter, not two additional production model layers.

The eventual gate still belongs in the original framework:

```text
causal normalized price/volume -> pre-filter state/probability -> C/Q model
```

## 10. Withdrawn exploratory formulation

The exploratory baseline:

```text
normalized price/volume -> add-on 0/1/2 classifier
normalized price/volume -> partial-exit yes/no classifier
```

is not the current pre-filter definition.

That experiment collapsed to majority-class predictions and, more importantly, answered a different question. Add-on count and partial exit describe realized path execution; they do not by themselves define whether the historical interval was suitable for Strategy 1.

The experiment is retained only as exploratory evidence and should not guide further class weighting, oversampling, or architecture tuning at this stage.

## 11. Historical reference bounds and C/Q terminology

For one Entry's legal realized campaign-return set, define:

```text
L = minimum realized campaign return
U = maximum realized campaign return
μ = mean realized campaign return
```

For the current entry-quality terminology:

```text
C = U - L
Q = (U - μ) / (U - L)
```

when the denominator is well-defined.

Interpretation:

```text
C -> opportunity/capacity range; larger is better when usable
Q -> quality-gap ratio; lower is better / more efficient
```

L, U, μ, C, Q and other statistics remain valuable for analysis. However, the current pre-filter research deliberately avoids assuming that any one of them is the correct definition of historical strategy suitability.

The C/Q entry-quality problem remains downstream and is not being redesigned in the present step.

## 12. Representation remains an open question

We have not yet frozen how all path/profit observations within a historical interval should be represented computationally.

Candidates may include direct empirical distributions, set-based representations, histogram/density representations, CNN-compatible representations, or other methods capable of retaining information that a single summary statistic discards.

No method is assumed superior in advance. In particular, a CNN is a candidate tool for learning structure, not a justification for inventing labels or statistical definitions.

The representation should ideally preserve information such as:

```text
where realized profits occur
how broadly or narrowly outcomes are distributed
how much support exists for different outcomes
rare but economically large outcomes
path multiplicity / amount of historical evidence
```

without requiring us to decide beforehand that mean, standard deviation, win rate, or another fixed statistic is the correct gate statistic.

## 13. Validation principles

Any eventual predictive evaluation must be chronological and causal:

```text
past -> train
purge future-label overlap where required by the defined target
later data -> validation/test
```

No random train/test split for the final predictive pre-filter.

However, the immediate task is still target/representation definition from historical realized data. The exact interval length, availability rule, state count, and computational representation are not yet frozen and must be discussed before they are used in a predictive experiment.

A previous diagnostic introduced a `maturity` condition without prior discussion; conclusions depending on that unapproved condition remain withdrawn.

## 14. Immediate research sequence

The current sequence is intentionally narrow:

```text
1. Keep the existing Strategy 1 mechanics and campaign-return definition fixed.
2. Keep one unique realized legal path as one historical observation.
3. Preserve each path's factual execution labels and realized campaign return.
4. Group the known historical paths by historical interval without first reducing them to a manually selected "good/bad" statistic.
5. Determine whether the complete path/profit structure supports useful profitability states/classes for the existing pre-filter.
6. Use descriptive statistics and execution labels only to interpret those states, not to define them automatically.
7. Once the pre-filter target is understood, test whether causal normalized price/volume can predict it chronologically OOS.
8. Leave the downstream C/Q entry-quality model unchanged during this work.
```

Do not introduce additional model layers, thresholds, statistical features, bootstrap/resampling, rare-class weighting, or representation hyperparameters without explicit discussion.

## 15. Current concise conclusion

FutureView is not currently adding another CNN layer. The active problem is the original pre-filter.

> We know all legal historical Strategy 1 paths and each path's realized campaign profit. The goal is to use the full path-level outcome structure within a historical interval to identify the interval's profitability state/class without first declaring that a human-selected statistic such as mean return, win rate, standard deviation, or μ defines "good" or "bad." Add-on, partial-exit, and other execution labels remain available for interpreting the discovered states. Once a meaningful pre-filter target exists, the existing causal price/volume model can be evaluated on its ability to predict that state; the downstream C/Q model remains a separate, unchanged entry-quality problem.

The next unresolved question is therefore narrowly defined: **how should the set of path-level realized outcomes within one historical interval be represented so that economically distinct profitability states can be identified without manually imposing the state definition?**

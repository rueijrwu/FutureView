# FutureView — Research Definition, Evidence, and Current Direction

Last consolidated: 2026-08-26

This is the canonical research document for FutureView. It consolidates the conceptual framework, Strategy 1 definition, target definitions, historical evidence, and current research direction. Implementation details, commands, architecture, data-provider details, and CI mechanics belong in `IMPLEMENT.md`.

## 1. Current research question

The current work is deliberately simplified. We are not adding another production model layer. We are revisiting the **pre-filter / gate** in the existing FutureView framework.

The clearest current definition is:

> **Layer 1 measures how favorable the current regime is to Strategy 1 itself from the realized return distribution of all legal historical Strategy 1 paths. It describes the strategy's realized profitability environment, but does not attempt to explain which price/volume structure caused that environment. Layer 2 is most useful when Layer 1 is neutral/mixed: it uses causal price/volume information to distinguish Entries and seek outcomes closer to the best available legal outcomes.**

This distinction is fundamental. The first layer asks whether Strategy 1 has an attractive opportunity environment. The second asks which Entry is preferable inside that environment.

A central methodological rule remains: no new threshold, window, maturity rule, normalization, derived statistic, class weighting, resampling rule, or other modeling assumption is introduced silently. Descriptive statistics may be used to understand the data, but are not automatically model inputs, labels, or trading rules.

## 2. Existing model framework

The intended overall framework remains conceptually simple:

```text
Strategy-1-specific regime suitability / pre-filter
        -> causal price/volume Entry selection
        -> C/Q entry-quality objective
```

This is not a proposal to add a separate historical-analysis CNN followed by another production CNN. The historical path analysis defines and evaluates the target of the **existing pre-filter**.

The two conceptual questions are:

```text
Layer 1 / pre-filter:
How favorable is this regime to Strategy 1 itself?

Layer 2 / Entry model:
Given that opportunity environment, which legal Entry is most likely to approach the better available outcomes?
```

The downstream Entry model remains based on C/Q and causal normalized price/volume. The present research concerns the first question.

## 3. Strategy-relative regime

The regime in this research is **strategy-specific**. It is not intended to be a generic bull/bear market label.

Strategy 1 defines the legal trading/campaign space. Historical realized data provides the observed outcomes of those legal campaigns. Therefore the preference of a regime is defined relative to Strategy 1's actual legal opportunity set.

For a historical interval `W`:

```text
P(W) = {(path_i, R_i)}
```

where `path_i` is one unique legal realized Strategy 1 execution path and `R_i` is its realized campaign return.

The return distribution of `P(W)` describes how Strategy 1 performed in that interval. Layer 1 does not need to know why that distribution occurred. The causal price/volume structure associated with the outcomes belongs to the later Entry-selection problem.

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

The fundamental historical data unit is:

```text
one unique realized legal path = one independent historical observation
```

The same formal Entry may appear in multiple path observations when different legal reference/add-on configurations produce different realized execution paths. This is intentional and is not treated as a duplicate-data error.

Each path retains factual labels/metadata such as:

```text
Entry
reference/add-on configuration
executed add-on count
partial-exit occurrence
terminal exit
campaign return
execution sequence / event locations
```

These labels are for statistical interpretation and explanation. They do not define regime quality and are not automatically input features. For example, after a favorable profitability state is identified, we may inspect whether its paths disproportionately contain partial exits or particular add-on behavior. That is explanation after the fact, not the definition of the state.

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

Partial exit is therefore retained as factual path metadata useful for interpreting profitability states, rather than being declared in advance to be a favorable class.

### Terminal exit

806 of 807 realized paths ended through the normal full-exit mechanism; only one ended at the horizon. Terminal-exit type therefore currently contains little independent variation.

## 7. What Layer 1 measures

Layer 1 evaluates the **comprehensive realized profitability distribution of Strategy 1's legal paths within a historical interval**.

For interval `W`:

```text
D_W = {R_1, R_2, ..., R_n}
```

The objective is not merely to calculate a conventional scalar summary such as mean return, standard deviation, median, or win rate. Those statistics can be inspected, but we do not assume beforehand that any one of them correctly measures strategy suitability.

Instead, the aim is to determine whether the complete return distribution contains a more appropriate statistical meaning for the pre-filter.

Zero return provides a natural economic reference:

```text
R = 0  -> neutral outcome
```

The realized bounds also provide immediately interpretable information:

```text
L = min(D_W)
U = max(D_W)
```

If:

```text
U < 0
```

then every observed legal Strategy 1 path in the interval lost money. This is an unambiguously unfavorable historical opportunity set.

If:

```text
L > 0
```

then every observed legal Strategy 1 path was profitable. This is an unambiguously favorable historical opportunity set.

The difficult and most informative case is generally:

```text
L < 0 < U
```

where profitable and unprofitable legal paths coexist.

## 8. The central statistical problem: neutral/mixed profitability

A central motivation for the pre-filter research is that:

```text
P(R > 0) ≈ 0.5
```

does **not** necessarily imply that Strategy 1 has no useful opportunity in the interval.

Two intervals can have similar win probabilities while having very different payoff structures. One may contain roughly symmetric small gains and losses. Another may contain many ordinary losses but a smaller set of very large profitable legal paths. Their conventional win rates may both appear neutral even though their economic opportunity structures are different.

Therefore the research question is:

> When the probability of a profitable legal path is approximately neutral, does the rest of the realized return distribution contain structure indicating that the interval is nevertheless favorable or unfavorable to Strategy 1?

This is where a learned representation such as a CNN may be useful: not to invent the Strategy 1 outcomes, but to learn which aspects of the complete realized profitability distribution carry useful statistical meaning beyond a manually selected single summary statistic.

The exact representation, class count, and boundaries remain open research questions and are not yet frozen.

## 9. Strategy preference and the value of Layer 2

Layer 1 defines a **Strategy-1-specific regime preference**. Conceptually, regimes can range continuously from unfavorable through neutral/mixed to highly favorable. These descriptions are conceptual anchors, not yet fixed threshold classes.

### Unfavorable regime

Strategy 1's legal opportunity set itself is poor. The extreme example is:

```text
U < 0
```

where even the best observed legal path loses money.

In such a regime there is little useful positive opportunity for the downstream Entry model to learn or select. Training or optimizing Entry selection primarily on these regimes may therefore have limited economic meaning.

### Neutral / mixed regime

The strategy has no overwhelming unconditional advantage, but legal paths contain materially different outcomes:

```text
L < 0 < U
```

and the positive probability may be near neutral.

This is expected to be the regime where the downstream Entry model has its greatest potential value. The task becomes:

```text
Given a mixed opportunity set,
use causal price/volume information to identify Entries
that are more likely to approach the better available legal outcomes.
```

This is the principal role of the C/Q model.

### Highly favorable regime

Strategy 1 already performs well across much of its legal opportunity set. The extreme example is:

```text
L > 0
```

where every observed legal path is profitable.

The downstream Entry-selection model may still improve efficiency or outcome quality, but its marginal value is smaller because the strategy already has a strong unconditional historical advantage in that regime.

Thus the expected value of Layer 2 is not constant across regimes. Conceptually:

| Strategy-1 regime | Opportunity set | Expected marginal value of Entry selection |
|---|---|---|
| Strongly unfavorable | Few/no attractive legal outcomes | Low |
| Neutral / mixed | Good and bad legal outcomes coexist | Highest |
| Strongly favorable | Most legal outcomes already attractive | Lower |

This is a conceptual research hypothesis, not yet an empirically validated rule or a hard gate threshold.

## 10. Role of price/volume information

The separation between Layer 1 and Layer 2 is intentional.

Layer 1 asks:

```text
What profitability environment did Strategy 1 experience?
```

It uses the realized legal path return distribution and does not need to explain the market mechanism that produced it.

Layer 2 asks:

```text
What observable causal price/volume structure distinguishes the better legal opportunities inside that environment?
```

This is where normalized price/volume information becomes central.

The benefit of this separation is that the Entry model is not asked to learn from regimes in which Strategy 1 has no meaningful positive opportunity, while its principal usefulness is concentrated on neutral/mixed regimes where selection can potentially move realized performance toward the better part of the available outcome range.

## 11. Withdrawn exploratory formulation

The exploratory baseline:

```text
normalized price/volume -> add-on 0/1/2 classifier
normalized price/volume -> partial-exit yes/no classifier
```

is not the current pre-filter definition.

That experiment collapsed to majority-class predictions and, more importantly, answered a different question. Add-on count and partial exit describe realized path execution; they do not by themselves define whether the historical regime was suitable for Strategy 1.

The experiment is retained only as exploratory evidence and should not guide further class weighting, oversampling, or architecture tuning at this stage.

## 12. Historical reference bounds and C/Q terminology

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

For Layer 1, `L` and `U` have direct descriptive meaning as the observed realized profitability bounds. They do not by themselves solve the mixed-distribution problem. In particular, when `L < 0 < U`, the internal structure of the distribution remains important.

The C/Q Entry-quality problem remains downstream and is not being redesigned in the present step.

## 13. Representation remains an open question

We have not yet frozen how the path-level return distribution within a historical interval should be represented computationally.

Candidates may include direct empirical distributions, set-based representations, histogram/density representations, CNN-compatible representations, or other methods capable of retaining information that a single summary statistic discards.

A CNN is a candidate for learning the statistical meaning of the distribution; it is not a justification for inventing arbitrary good/bad labels.

The representation should preserve, as directly as practical:

```text
location of realized profits relative to zero
lower and upper realized opportunity bounds
shape/asymmetry of the outcome distribution
amount of historical support
rare but economically large outcomes
path multiplicity
```

without requiring us to decide beforehand that mean, standard deviation, win rate, or another fixed statistic is the correct gate statistic.

Path execution labels remain available afterward to explain the learned states statistically.

## 14. Validation principles

Any eventual predictive evaluation must be chronological and causal:

```text
past -> train
purge future-label overlap where required by the defined target
later data -> validation/test
```

No random train/test split for the final predictive pre-filter/Entry model.

The immediate task, however, is still to understand the Strategy-1-specific profitability regime from realized historical paths. The exact interval length, learned representation, and profitability-state parameterization are not yet frozen and must be discussed before they become predictive-model assumptions.

A previous diagnostic introduced a `maturity` condition without prior discussion; conclusions depending on that unapproved condition remain withdrawn.

## 15. Immediate research sequence

The current sequence is intentionally narrow:

```text
1. Keep Strategy 1 mechanics and campaign-return semantics fixed.
2. Keep one unique realized legal path as one historical observation.
3. Preserve each path's factual execution labels and realized campaign return.
4. For each historical interval, construct the complete Strategy 1 legal-path return distribution.
5. Use zero, L, and U as economically interpretable references/bounds, not as an arbitrary composite score.
6. Study whether the full distribution provides a useful Strategy-1-specific profitability state, especially when positive probability is near neutral.
7. Use path labels only to statistically explain learned profitability states.
8. After the regime definition is understood, evaluate the causal price/volume Entry model primarily where selection has economic meaning, especially neutral/mixed regimes.
9. Keep the downstream C/Q objective unchanged while this first-layer question is resolved.
```

Do not introduce additional production model layers, arbitrary composite profitability scores, bootstrap/resampling, rare-class weighting, or new representation hyperparameters without explicit discussion.

## 16. Current concise definition

> **Layer 1 evaluates the realized profitability distribution of all legal Strategy 1 paths in a historical interval and determines how favorable that regime is to Strategy 1, without attempting to explain the underlying price/volume cause. Zero return is the natural neutral reference and L/U describe the observed profitability range; the key unresolved problem is whether the rest of the distribution contains useful strategy edge when win probability is approximately neutral. Layer 2 then uses causal price/volume information to select among legal opportunities, with its greatest expected value in neutral/mixed regimes where good and bad outcomes coexist. In strongly unfavorable regimes there may be little useful opportunity to learn, while in strongly favorable regimes the strategy already performs well and Entry selection has smaller marginal effect.**

# FutureView — Research Definition, Evidence, and Current Direction

Last consolidated: 2026-08-26

This is the canonical research document for FutureView. It consolidates the conceptual framework, Strategy 1 definition, target definitions, historical evidence, and current research direction. Implementation details, commands, architecture, data-provider details, and CI mechanics belong in `IMPLEMENT.md`.

## 1. Current research question

The current work is deliberately simplified. We are not adding another production model layer. We are revisiting the **first layer / pre-filter / gate** in the existing FutureView framework.

The clearest current definition is:

> **Layer 1 measures how favorable a fixed historical regime is to Strategy 1 from the realized outcomes of all legal Strategy 1 paths in that calendar interval. It describes the strategy's realized profitability environment but does not attempt to explain which price/volume structure caused that environment. Layer 2 is most useful when Layer 1 is neutral/mixed: it uses causal price/volume information to distinguish Entries and seek outcomes closer to the best available legal outcomes.**

The immediate Layer-1 research problem is now narrower:

> **Given a fixed-calendar window containing the legal Strategy 1 execution paths and their realized profits, what training target/objective should a CNN/autoencoder use so that the learned representation captures the economically meaningful profitability structure of the regime without manually imposing a conventional statistic as the answer?**

The input representation is now substantially defined. The **target/objective is intentionally not yet frozen**.

A central methodological rule remains: no new threshold, window length, maturity rule, normalization, derived statistic, class weighting, resampling rule, or target definition is introduced silently.

## 2. Two-layer conceptual framework

```text
Layer 1: Strategy-1-specific regime suitability / pre-filter
        -> Layer 2: causal price/volume Entry selection
        -> C/Q entry-quality objective
```

Layer 1 asks:

```text
How favorable is this regime to Strategy 1 itself?
```

Layer 2 asks:

```text
Given that opportunity environment,
which legal Entry is most likely to approach the better available outcomes?
```

The first layer does not explain the price/volume cause of a regime. The second layer is where causal normalized price/volume information is used.

The historical Layer-1 analysis is not an additional production layer. It defines the target/meaning of the existing pre-filter.

## 3. Strategy-relative regime and fixed calendar window

The regime is **strategy-specific**, not a generic bull/bear label.

Strategy 1 defines the legal execution space. Historical realized data provides the observed outcomes of those legal executions. The preference of a regime is therefore defined relative to Strategy 1's actual opportunity set.

The regime interval `W` must be a **fixed calendar/trading-session window**. It must not be defined as the most recent fixed number of legal paths.

This distinction is important because Strategy 1 itself has regime preference. If a fixed number of recent paths were used, a regime with few legal opportunities would automatically reach farther backward in time and could mix information from a different regime. A fixed calendar window preserves the actual opportunity density of the strategy in that period.

The exact length of `W` is not yet frozen. Existing implementation lengths have different meanings and must not be confused with `W`:

```text
60 sessions  -> current per-Entry future campaign/label horizon
50 sessions  -> historical causal price/volume input context
260 sessions -> historical sliding training policy
W             -> Layer-1 fixed-calendar regime window; still to be selected
```

## 4. Frozen Strategy 1 research mechanics

Strategy 1 is long-only and uses daily close information. The current formal research version uses three equal capital tranches.

A formal Entry candidate satisfies:

```text
Close > MA5
Close > MA10
Close > MA20
MA5 > MA10
MA10 > MA20
```

The campaign begins with one one-third-capital Entry. Depending on the legal historical-reference/add-on configuration and subsequent realized prices, it may have zero, one, or two add-ons. Each add-on uses another one-third of initial capital. Execution priority remains full MA10 exit, then eligible MA5 half exit, then add-on. Three-session cooldown and horizon-end liquidation remain part of the current executable strategy.

The exact executable semantics are documented in `IMPLEMENT.md`.

## 5. Campaign return and unique path

For one legal realized campaign, initial capital is normalized to 1.0. Entry/add-on purchases convert the relevant one-third capital tranche into shares at the realized execution price. Partial/full exits convert shares back into cash.

```text
CampaignReturn = final_cash - 1.0
```

The fundamental historical observation remains:

```text
one unique realized legal path = one independent historical observation
```

The same formal Entry may have multiple independent realized paths when different legal reference/add-on configurations produce different execution sequences. This is intentional and is not a duplicate-data error.

## 6. Path representation: execution sequence

For Layer 1, a path is represented directly by its **execution/capital-exposure sequence**, rather than by separately feeding hand-described timing variables such as add-on count, exit count, or event-day vector.

For the current 60-session campaign horizon, define for path `p`:

```text
S_p(t) = capital exposure / invested fraction at campaign session t
```

so:

```text
S_p in R^60
```

A schematic example is:

```text
[1/3, 1/3, 1/3, 2/3, 2/3, ..., 1/3, ..., 0, 0]
```

The sequence itself contains the execution-time structure:

```text
initial Entry
add-on timing
partial-exit timing
full-exit timing
holding duration
capital exposure through time
```

Therefore add-on count, exit count, and explicit timing vector `D` should **not be redundantly added as Layer-1 model inputs** when the sequence already encodes them.

Each legal path is paired with its realized campaign return:

```text
(S_p, R_p)
```

Path labels such as executed add-on count, partial-exit occurrence, terminal exit, and reference configuration are retained as metadata for later statistical interpretation of learned states. They do not define regime quality and are not automatically model inputs.

## 7. Fixed input slots and legality mask

A Layer-1 sample must have a fixed input shape even though the number of legal Strategy 1 paths varies by regime.

The current structural proposal retains fixed calendar positions and path categories rather than selecting a fixed number of recent legal paths.

The coarse execution categories remain:

```text
Add-on count: 0 / 1 / 2
Exit count:   1 / 2
```

which gives six organizational path sets:

```text
(A0,E1) (A0,E2)
(A1,E1) (A1,E2)
(A2,E1) (A2,E2)
```

These categories primarily provide fixed organizational slots. The actual path representation is still the execution sequence.

For every calendar position and applicable path slot, retain a legality/existence mask:

```text
w = 1 -> legal realized path exists in this slot
w = 0 -> no legal realized path exists in this slot
```

This distinction is essential:

```text
R = 0, w = 1 -> legal path with neutral realized profit
w = 0        -> no legal path; not a zero-profit observation
```

If `W` contains `T` trading sessions and the six coarse path sets are sufficient to index the required observations, the conceptual sequence tensor is:

```text
6 x T x 60
```

with corresponding profit and mask information.

The exact handling of multiple unique paths that share the same calendar day and coarse `(Add-on, Exit)` category remains an implementation detail that must preserve the independent paths rather than silently averaging them.

## 8. Path count is information, not a nuisance

The number of legal paths in a fixed calendar regime is itself meaningful Strategy-1 information.

With the legality mask:

```text
N(W) = sum(w)
```

Therefore the model can in principle learn not only the realized payoff distribution but also the **opportunity density** of Strategy 1 in the regime.

We should not normalize every regime to a fixed number of legal paths, because doing so would remove this information and can force sparse regimes to borrow paths from earlier, different regimes.

Layer 1 therefore preserves jointly:

```text
path execution structure
realized profit
legal-path occurrence/density
calendar-time organization
```

## 9. Historical campaign-structure evidence — SMH

A five-year descriptive scan of the current SMH Strategy 1 implementation produced:

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

The two-add-on group is rare, but its observed payoff range is wide, approximately -8.67% to +10.86%. A small number of economically large outcomes can therefore coexist with a negative typical outcome. Rare paths must not be discarded merely because their count is small.

### By partial-exit occurrence

| Partial exit occurred | Paths | Distinct Entries | Mean return | Median return | Fraction positive |
|---|---:|---:|---:|---:|---:|
| No | 253 | 146 | -1.377% | -1.031% | 11.9% |
| Yes | 554 | 264 | +1.421% | +1.239% | 66.1% |

This is descriptive association, not a causal claim. Partial exit remains metadata for interpreting learned states rather than a definition of a favorable state.

806 of 807 realized paths ended through the normal full-exit mechanism; only one ended at the horizon.

## 10. What Layer 1 measures

For fixed calendar interval `W`, Layer 1 evaluates the comprehensive realized Strategy-1 opportunity structure:

```text
P(W) = {(S_p, R_p, w_p)}
```

for the legal-path organization of that interval.

The central economic quantity remains the realized profitability distribution:

```text
D_W = {R_p : w_p = 1}
```

but the model is allowed to retain the associated path sequence and path density rather than reducing the regime to one hand-selected scalar statistic.

Zero return is the natural economic reference:

```text
R = 0 -> neutral realized outcome
```

and:

```text
L = min(D_W)
U = max(D_W)
```

provide clear realized profitability bounds.

If:

```text
U < 0
```

then every observed legal path lost money and the historical opportunity set is unambiguously unfavorable.

If:

```text
L > 0
```

then every observed legal path was profitable and the historical opportunity set is unambiguously favorable.

The difficult and most informative case is:

```text
L < 0 < U
```

where profitable and unprofitable legal paths coexist.

## 11. Central statistical problem: neutral/mixed profitability

A key motivation is:

```text
P(R > 0) approximately 0.5
```

does **not** necessarily imply that Strategy 1 has no useful opportunity in the interval.

Two regimes can have similar win probabilities while having very different payoff distributions. One may contain roughly symmetric small gains and losses. Another may contain ordinary losses together with a smaller number of very large profitable legal paths.

The research question is therefore:

> When profitable-path probability is approximately neutral, does the remaining path-conditioned realized-profit structure contain statistical information showing that the regime is nevertheless favorable or unfavorable to Strategy 1?

We deliberately do not answer this in advance with mean return, standard deviation, win rate, a fixed percentile, or another manually selected composite statistic.

## 12. Strategy preference and value of Layer 2

Conceptually, Strategy-1 regimes range from unfavorable through neutral/mixed to highly favorable. These are conceptual anchors, not frozen threshold classes.

| Strategy-1 regime | Opportunity set | Expected marginal value of Layer 2 |
|---|---|---|
| Strongly unfavorable | Few/no attractive legal outcomes | Low |
| Neutral / mixed | Good and bad legal outcomes coexist | Highest |
| Strongly favorable | Most legal outcomes already attractive | Lower |

In an unfavorable regime, there may be little positive opportunity worth selecting. In a neutral/mixed regime, selecting the right Entry can matter greatly. In a highly favorable regime, Strategy 1 already performs well across much of the opportunity set, so Entry selection may add less marginal value.

This is a research hypothesis, not yet a hard gate rule.

## 13. Role of price/volume information

Layer 1 asks:

```text
What profitability environment did Strategy 1 experience?
```

It does not need to explain the market mechanism that produced it.

Layer 2 asks:

```text
What observable causal price/volume structure distinguishes the better legal opportunities inside that environment?
```

Normalized causal price/volume therefore belongs to Layer 2. It is not required to define the historical realized profitability state in Layer 1.

## 14. CNN and autoencoder status

A CNN remains the preferred simple model family to investigate Layer 1 because the representation contains structured sequences and calendar organization.

An **autoencoder is retained as a candidate Layer-1 architecture**:

```text
Layer-1 input
    -> CNN encoder
    -> latent representation z_W
    -> decoder / training objective
```

The motivation is to allow a learned representation without first imposing arbitrary good/bad class labels.

However, an ordinary reconstruction autoencoder is **not yet accepted as the final objective**. Reconstruction alone may encourage the network to preserve execution patterns that are easy to reconstruct without necessarily learning the statistical meaning of profitability that Layer 1 is intended to measure.

Therefore the architecture and the target are deliberately separated:

```text
Architecture candidate: CNN / autoencoder       -> retained
Layer-1 input representation                    -> substantially defined
Layer-1 training target / objective              -> NOT YET DEFINED
```

The next research question is specifically the target/objective. We must determine what the model should be optimized to learn so that `z_W` represents Strategy-1 profitability meaning rather than merely compressing path mechanics.

No good/bad label, reconstruction loss, mean-profit target, win-rate target, `L/U` target, or composite score should be adopted as the answer until this question is explicitly evaluated.

## 15. Withdrawn exploratory formulation

The earlier exploratory baseline:

```text
normalized price/volume -> add-on 0/1/2 classifier
normalized price/volume -> partial-exit yes/no classifier
```

is not the current Layer-1 definition. Add-on and partial-exit labels describe realized execution and remain useful for explanation, but they do not themselves define whether a regime is suitable for Strategy 1.

## 16. Historical reference bounds and C/Q terminology

For one Entry's legal realized campaign-return set:

```text
L = minimum realized campaign return
U = maximum realized campaign return
mu = mean realized campaign return
```

For downstream entry-quality terminology:

```text
C = U - L
Q = (U - mu) / (U - L)
```

when the denominator is well-defined.

```text
C -> opportunity/capacity range; larger is better when usable
Q -> quality-gap ratio; lower is better / more efficient
```

For Layer 1, `L` and `U` are economically interpretable realized bounds, but they do not solve the internal mixed-distribution problem. The downstream C/Q problem is unchanged during the present Layer-1 research.

## 17. Validation principles

Any eventual predictive evaluation must be chronological and causal:

```text
past -> train
purge future-label overlap where required
later data -> validation/test
```

No random train/test split is allowed for the final predictive pre-filter/Entry model.

The immediate task is not yet live prediction. It is to define the historical Strategy-1-specific regime representation and its correct learning target.

## 18. Immediate research sequence

```text
1. Keep Strategy 1 mechanics and campaign-return semantics fixed.
2. Keep one unique realized legal path as one independent historical observation.
3. Use a fixed calendar/trading-session regime window W; do not use a fixed recent-path count.
4. Represent each path by its 60-session capital-exposure/execution sequence S_p.
5. Pair each path with realized campaign profit R_p and legality/existence mask w.
6. Preserve N(W) = sum(w) as genuine regime information.
7. Retain add-on/exit/reference labels as interpretation metadata, not redundant sequence inputs.
8. Retain CNN/autoencoder as the simple first Layer-1 architecture candidate.
9. Do NOT yet freeze the autoencoder target/objective.
10. Next determine what target/objective makes the learned representation express Strategy-1 profitability meaning, especially in neutral/mixed regimes.
11. Only after Layer 1 is defined should causal price/volume prediction and downstream C/Q selection be revisited.
```

## 19. Current concise definition

> **Layer 1 uses a fixed calendar regime window and preserves every legal Strategy 1 opportunity through its execution/capital-exposure sequence, realized campaign profit, and legality mask. The number of legal paths is itself regime information and must not be normalized away by selecting a fixed path count. Add-on/exit labels remain metadata for interpretation because their timing information is already encoded by the execution sequence. A CNN/autoencoder is retained as the simplest learned Layer-1 representation, but its training target is deliberately unresolved: the next question is what objective will make the latent representation capture the economically meaningful Strategy-1 profitability structure—particularly when win probability is neutral—rather than merely reconstructing execution mechanics.**

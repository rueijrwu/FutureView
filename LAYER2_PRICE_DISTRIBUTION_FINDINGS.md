# Layer2 Price Distribution — Current Findings

Date: 2026-09-04
Branch: `layer2-price-distribution-v1`

This note records the current interpretation of the Layer2 price-distribution experiments. It is intentionally neutral: the purpose is to distinguish what the experiments actually show from stronger conclusions that are not yet supported.

## 1. Current research scope

Layer1 and Layer2 have different roles.

Layer1 uses the fixed Strategy and historical Strategy-path statistics to identify regions where Strategy-relative historical structure is sufficiently non-neutral to justify further analysis. U/C/Q are Strategy-relative quantities.

The current research scope is now intentionally narrower:

> Study only the H-selected region and ask whether the preceding normalized price/volume window contains a learnable nonlinear signal associated with the distribution of the stock's price change over the next 3 sessions.

Other Layer1 regions are currently out of scope. They are excluded from Layer2 research rather than treated as separate modeling targets.

Current Layer2 input is the already-defined normalized historical price/volume window. The current output is price only; future volume is deliberately excluded for now. The realized target is the 3-session close-to-close log return `r3`. The small CNN produces price-distribution/ranking outputs including q10, q50, q90 and P(up).

The main quantity of interest at this stage is not trading profit and not a claim of exact price prediction. It is whether model score creates stable conditional separation in the realized future-price distribution inside H.

## 2. Earlier experiments and what changed

### Experiment A — final-year OOS CNN with retrospective Layer1 selection

Layer1 classifications were prepared retrospectively from the historical Strategy-path construction. Layer2 training and validation were chronological, but the Layer1 selection itself was not reconstructed as an as-of-t state.

This experiment produced strong separation in the final-year sample. For q50 buckets, realized P(up) was approximately 25% / 40.6% / 83.3% from bottom / middle / top, with top mean r3 around +2.49% and bottom around -2.99%.

This was evidence that, given the retrospectively selected historical population, the CNN could find strong price/volume structure associated with future 3-session price behavior. It was not yet evidence that the complete Layer1→Layer2 pipeline could have produced the same selection in real time.

### Experiment B — yearly chronological OOS CNN with retrospective Layer1 selection

The CNN was then evaluated with expanding chronological folds. Each OOS year was predicted only by a model trained on earlier selected samples. This made Layer2 generalization substantially stricter while retaining retrospective Layer1 selection.

Pooled q50 buckets across 329 OOS samples were:

```text
bottom20: n=66, mean r3=-2.55%, P(up)=31.8%
middle60: n=197, mean r3=+0.14%, P(up)=51.3%
top20:    n=66, mean r3=+3.60%, P(up)=65.2%
```

The yearly top-vs-bottom separation remained in the same direction in 2023, 2024 and 2025. This strengthened the evidence that the Layer2 hidden signal was not solely a single final-year accident.

### Experiment C — as-of-t Layer1 classification + chronological Layer2

The third experiment changed the information boundary of Layer1. For each current date `t`, Layer1 was reconstructed using only information available through `t`.

The Action run was `33897988068`, source commit `f981f1224cfa1aa84f679e1595c4ec660f0889b9`, and tests passed 7/7.

Causal Layer1 summary:

```text
raw rows        = 2012
classified W    = 952
High            = 274
Neutral         = 427
Low             = 251
Layer2 selected = 524
```

Pooled chronological q50 buckets over 389 OOS predictions became:

```text
bottom20: n=80,  mean r3=-0.95%, P(up)=46.25%
middle60: n=229, mean r3=+0.15%, P(up)=49.78%
top20:    n=80,  mean r3=+1.10%, P(up)=56.25%
```

The pooled ordering remained but weakened substantially.

## 3. Refined Layer1 interpretation: entry-C/Q and exit-C/Q

Subsequent analysis exposed that a single C/Q characterization is insufficient. There are two useful C/Q views tied to the two sides of the Strategy path:

- entry-relative C/Q: characterizes the opportunity relative to entry/path construction;
- exit-relative C/Q: characterizes the opportunity relative to exit/path construction.

Q preserves its historical meaning as path inefficiency relative to the best path:

```text
Q = (U - P) / |C|
```

where applicable to the historical definition. During the later distribution audit, normalization by an externally imposed scale was removed; dispersion is instead inspected using the empirical standard deviation because that scale belongs to the data/Strategy structure itself.

For the current Layer2 study, the entry and exit views are combined only to determine whether a window qualifies for the H-focused population. Conflicting or neutral combinations are excluded. The important point is that Layer1 acts as a filter; Layer2 is not asked to predict the Layer1 label itself.

## 4. H as the current Layer2 study population

The current research does not interpret H as a generic bull label or as a claim that price will rise.

H is a Strategy-relative historical region in which path structure appears sufficiently informative to justify a second-stage price-distribution model. Absolute realized return can still be negative. The reason to focus on H is empirical: among the tested populations, H-only evaluation produced the clearest and most stable Layer2 ranking signal.

The current research question is therefore:

```text
Given that a window is in H,
can normalized recent price/volume structure rank future 3-session outcomes?
```

No parallel Layer2 research program is currently planned for other regions.

## 5. Layer2 training definition retained after simplification

Several candidate additions were introduced during exploration but had not been independently validated. They were removed from the approved core experiment rather than being silently retained.

The retained training definition is deliberately small:

```text
input:          90-session normalized price/volume window
memory:         most recent 150 eligible training samples
Layer1 scope:   H-focused selection from dual entry/exit C/Q filtering
retraining:     rolling chronological retraining
model focus:    conditioned/shared model architecture, evaluated on H only
```

Unvalidated additions are not considered part of the current baseline merely because they appeared in an intermediate experiment.

## 6. H-only result and retraining cadence

The clearest current Layer2 signal occurs in H-only OOS evaluation.

With the original 8-year data horizon, 90D normalized P/V input, 150-sample memory and 15D retraining, the H-only conditioned model produced approximately:

```text
OOS n            = 131
folds            = 22
Spearman         = 0.262
bottom20 P(up)   = 25.9%
top20 P(up)      = 55.6%
bottom20 mean r3 = -1.60%
top20 mean r3    = +1.40%
```

Changing only retraining cadence from 15D to 10D produced:

```text
OOS n            = 131
folds            = 26
Spearman         = 0.292062
bottom20 P(up)   = 7.41%
top20 P(up)      = 62.96%
bottom20 mean r3 = -3.101%
top20 mean r3    = +2.601%
```

The 10D run used `period=8y`, `roll_days=10`, `memory=150`; the Action run was `33922738929`.

The important point is that OOS n stayed at 131. The improvement therefore did not come from adding more H samples. The model was simply refreshed more frequently on the same regime-local training definition.

The current strongest observed configuration is consequently:

```text
8y history
90D normalized P/V input
150 eligible-sample rolling memory
10D retrain cadence
H-only Layer2 evaluation
```

This is the strongest observed configuration, not a claim that 10D is globally optimal.

## 7. Longer history audit: more OOS samples did not improve the H signal

The H-only history-length audit deliberately increased available history while retaining the local training concept.

Observed results were approximately:

| data horizon | H-only OOS n | folds | Spearman | bottom20 P(up) | top20 P(up) | bottom20 mean r3 | top20 mean r3 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 8y | 131 | 22 | 0.262 | 25.9% | 55.6% | -1.60% | +1.40% |
| 12y | 287 | 46 | 0.054 | 24.1% | 36.2% | -1.72% | -1.60% |
| max | 534 | 80 | 0.029 | 35.5% | 40.2% | -0.67% | -1.01% |

Thus increasing nominal OOS coverage from 131 to 287 and 534 did not strengthen the relationship. Ranking correlation collapsed and the top bucket ceased to have positive mean r3 in the longer-history runs.

The correct conclusion is not that older data are intrinsically useless. The result shows that the learned H-conditioned mapping is not stationary across the full available history under the current representation/training procedure.

Together with the 10D-vs-15D result, this supports a **regime-local hypothesis**:

> For the current H-focused Layer2 representation, adapting more frequently to relatively recent eligible structure appears more useful than indiscriminately increasing historical coverage.

This remains a hypothesis to be stress-tested, not a proof of a specific market-regime model.

## 8. What the model prediction currently means

The Layer2 score should currently be interpreted primarily as a **ranking variable**, not as a calibrated probability forecast.

For H-only 10D OOS, higher scores correspond to a substantially more favorable realized 3-session return distribution at the extremes. The top/bottom P(up) separation is economically large, but `P(up)` output values themselves should not automatically be interpreted as literal probabilities until calibration is separately established.

The useful claim is therefore:

```text
Within H-selected windows, the model can rank some recent P/V structures
into groups with materially different realized near-future price distributions.
```

The evidence does not yet justify:

```text
model output 0.70 == a calibrated 70% probability of an up move
```

Nor does it prove trading profitability after transaction costs, position sizing or policy integration.

## 9. Current consolidated conclusion

The current experiments support the following bounded interpretation:

1. Layer1's role is filtering/conditioning, not direct next-price prediction. Entry-relative and exit-relative Strategy statistics provide complementary views used to identify the H-focused study population.
2. The current Layer2 research scope is H only. Other Layer1 regions are excluded from the active research question and are not being modeled or compared at this stage.
3. Layer2's strongest current evidence is H-conditioned ranking.
4. Under the original 8-year horizon, 90D normalized P/V input and 150-sample rolling memory, reducing retraining cadence from 15D to 10D improved H-only Spearman from about 0.262 to 0.292 and materially widened the extreme-bucket separation without increasing OOS n.
5. Extending history to 12 years or maximum available history increased OOS n but sharply weakened H-only ranking. The current mapping is therefore not demonstrably stationary over long history.
6. Taken together, the results favor a regime-local training interpretation: recent relevant samples plus more frequent updating currently work better than maximizing historical sample count.

The present result is evidence of conditional statistical structure. It is not yet evidence of a deployable trading strategy, an optimized retraining interval, or a calibrated probability model.

## 10. Next bounded questions

The next experiments should remain narrow and attribution-preserving. Useful unresolved questions are:

```text
A. Is 10D genuinely better than nearby retraining cadences, or is the observed improvement sampling variance?
B. Does the H-only ranking survive other chronological segments/tickers without redefining H?
C. How stable are top/bottom bucket results under bootstrap or fold-level uncertainty?
D. Only after ranking stability is established: should P(up) calibration be studied separately?
```

No additional target, purge rule, loss mixture, handcrafted indicator, non-H policy comparison or strategy optimization should be treated as approved merely because it is a plausible next step.
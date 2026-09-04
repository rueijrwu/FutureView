# Layer2 Price Distribution — Current Findings

Date: 2026-09-04
Branch: `layer2-price-distribution-v1`

This note records the current interpretation of the Layer2 price-distribution experiments. It is intentionally neutral: the purpose is to distinguish what the experiments actually show from stronger conclusions that are not yet supported.

## 1. Research question

Layer1 and Layer2 have different roles.

Layer1 uses the fixed Strategy and historical Strategy-path statistics to identify High / Neutral / Low regions. U/C/Q are Strategy-relative quantities; Neutral is the region filtered out for the current Layer2 price-distribution experiment.

Layer2 does not predict Strategy return. Its current question is narrower:

> Conditional on Layer1 selecting a non-Neutral region, does the preceding normalized price/volume window contain a learnable nonlinear signal associated with the distribution of the stock's price change over the next 3 sessions?

Current Layer2 input is the already-defined normalized historical price/volume window. The current output is price only; future volume is deliberately excluded for now. The realized target is the 3-session close-to-close log return `r3`. The small CNN produces price-distribution/ranking outputs including q10, q50, q90 and P(up).

The main quantity of interest at this stage is not trading profit and not a claim of exact price prediction. It is whether model score creates stable conditional separation in the realized future-price distribution.

## 2. Three experiments and what differs

### Experiment A — final-year OOS CNN with retrospective Layer1 selection

Layer1 H/N/L classifications were prepared retrospectively from the historical Strategy-path construction. Layer2 training and validation were chronological, but the Layer1 selection itself was not reconstructed as an as-of-t state.

This experiment produced strong separation in the final-year sample. For q50 buckets, realized P(up) was approximately 25% / 40.6% / 83.3% from bottom / middle / top, with top mean r3 around +2.49% and bottom around -2.99%.

This was evidence that, *given the retrospective Layer1-selected set*, the CNN could find strong price/volume structure associated with future 3-session price behavior. It was not yet evidence that the complete Layer1→Layer2 pipeline could have produced the same selection in real time.

### Experiment B — yearly chronological OOS CNN with retrospective Layer1 selection

The CNN was then held conceptually fixed and evaluated with expanding chronological folds. Each OOS year was predicted only by a model trained on earlier selected samples. This made Layer2 generalization substantially stricter, while retaining the retrospective Layer1 W classification.

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

Q should preserve its historical meaning as path inefficiency relative to the best path:

```text
Q = (U - P) / |C|
```

where applicable to the historical definition. During the later distribution audit, normalization by an externally imposed scale was removed; dispersion is instead inspected using the empirical standard deviation because that scale belongs to the data/Strategy structure itself.

The two H/L classifications should not be collapsed prematurely. The important filtering result is that the strongest definition of Neutral is the overlap where the entry and exit views do not jointly identify a directional Strategy regime. In particular, mixed `(H,L)` and `(L,H)` states are treated as neutral for the current Layer2 experiment rather than forcing them into H or L.

The purpose of this filter is not to claim that H/L itself predicts the next price move. Its purpose is to remove regions where the historical Strategy statistics are comparatively neutral, so Layer2 is trained on windows for which the Strategy-conditioned historical structure is more informative.

## 4. Interpretation of H and L

The H/L labels are Strategy-relative, not generic bull/bear labels.

The distribution audit suggests an asymmetric economic interpretation:

- **L region:** the periodic baseline is comparatively strong. A simple interpretation is that periodic accumulation already fits these regions well; Strategy path selection does not clearly add superior return. Negative/weak C can therefore coexist with attractive absolute U because the baseline itself is hard to beat.
- **H region:** the periodic baseline is comparatively weak, while the Strategy exhibits stronger downside-resistance/path-selection structure. Absolute realized return can still be negative. H therefore does not mean 'price will rise'; it identifies a region where Strategy-relative path information may matter more.

This distinction is important for Layer2. The model should not be expected to solve the same problem in H and L.

A plausible policy-level hypothesis is therefore:

```text
L -> periodic baseline may already be sufficient
H -> Layer2 ranking may have higher marginal value
```

This is a hypothesis supported by the current distribution/model evidence, not yet a completed direct policy comparison. A strict `L periodic vs L Layer2-selected` return comparison on identical OOS windows remains to be performed before promoting it to a strategy rule.

## 5. Layer2 training definition retained after simplification

Several candidate additions were introduced during exploration but had not been independently validated. They were removed from the approved core experiment rather than being silently retained.

The retained training definition is deliberately small:

```text
input:          90-session normalized price/volume window
memory:         most recent 150 eligible training samples
Layer1 filter:  dual entry/exit H/L consensus; mixed H/L states neutral
retraining:     rolling chronological retraining
model focus:    conditioned model, with H-only evaluation of primary interest
```

Unvalidated additions are not considered part of the current baseline merely because they appeared in an intermediate experiment.

## 6. H-only result and retraining cadence

Separating H and L materially changed the interpretation of Layer2. The clearest current signal occurs in H-only OOS evaluation.

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

The current strongest configuration is consequently:

```text
8y history
90D normalized P/V input
150 eligible-sample rolling memory
10D retrain cadence
dual entry/exit neutral filtering
H-only primary Layer2 evaluation
```

This is the strongest observed configuration, not a claim that 10D is globally optimal.

## 7. Longer history audit: more OOS samples did not improve the signal

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

> For the current Layer2 representation, adapting more frequently to relatively recent eligible structure appears more useful than indiscriminately increasing historical coverage.

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

1. Layer1's role is filtering/conditioning, not direct next-price prediction. Entry-relative and exit-relative Strategy statistics provide complementary views; mixed H/L states are currently removed as Neutral.
2. H and L should not be interpreted symmetrically. L appears closer to a region where periodic accumulation is already strong; H appears to be the region where Strategy-relative path information has greater marginal relevance.
3. Layer2's strongest current evidence is therefore H-conditioned ranking rather than a universal H+L predictor.
4. Under the original 8-year horizon, 90D normalized P/V input and 150-sample rolling memory, reducing retraining cadence from 15D to 10D improved H-only Spearman from about 0.262 to 0.292 and materially widened the extreme-bucket separation without increasing OOS n.
5. Extending history to 12 years or maximum available history increased OOS n but sharply weakened H-only ranking. The current mapping is therefore not demonstrably stationary over long history.
6. Taken together, the results favor a regime-local training interpretation: recent relevant samples plus more frequent updating currently work better than maximizing historical sample count.
7. L may ultimately require no Layer2 ranking at all if a direct same-window comparison confirms that periodic policy is already sufficient. That comparison is still outstanding.

The present result is evidence of conditional statistical structure. It is not yet evidence of a deployable trading strategy, an optimized retraining interval, or a calibrated probability model.

## 10. Next bounded questions

The next experiments should remain narrow and attribution-preserving. Useful unresolved questions are:

```text
A. On identical L OOS windows, does Layer2 selection improve anything over periodic baseline?
B. Is 10D genuinely better than nearby retraining cadences, or is the observed improvement sampling variance?
C. Does the H-only ranking survive other chronological segments/tickers without redefining H/L?
D. How stable are top/bottom bucket results under bootstrap or fold-level uncertainty?
E. Only after ranking stability is established: should P(up) calibration be studied separately?
```

No additional target, purge rule, loss mixture, handcrafted indicator or policy optimization should be treated as approved merely because it is a plausible next step.
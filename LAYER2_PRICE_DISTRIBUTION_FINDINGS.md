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

However, Layer1 was still answering the retrospective question: after historical Strategy outcomes are known, which W belongs to High/Neutral/Low?

### Experiment C — as-of-t Layer1 classification + chronological Layer2

The third experiment changed the information boundary of Layer1.

For each current date `t`, Layer1 was reconstructed using only information available through `t`. Paths whose final exit lay after `t` were force-closed at the current close for the as-of calculation. The experimental causal implementation also reconstructed local extrema from the available prefix. The resulting as-of W classification determined whether the sample was passed to Layer2. Layer2 itself continued to use only historical price/volume through the current date and chronological OOS training.

This experiment therefore asks a different and stricter question:

> If the entire Layer1 selection state must be knowable as of the current date, does the Layer2 price-distribution ranking remain?

The Action run was `33897988068`, source commit `f981f1224cfa1aa84f679e1595c4ec660f0889b9`, and tests passed 7/7.

Causal Layer1 summary:

```text
raw rows       = 2012
classified W   = 952
High           = 274
Neutral        = 427
Low            = 251
Layer2 selected = 524
```

Pooled chronological q50 buckets over 389 OOS predictions became:

```text
bottom20: n=80,  mean r3=-0.95%, P(up)=46.25%
middle60: n=229, mean r3=+0.15%, P(up)=49.78%
top20:    n=80,  mean r3=+1.10%, P(up)=56.25%
```

The pooled ordering therefore did not disappear, but it became much weaker than in Experiment B.

Year-level q50 top-vs-bottom P(up) was:

```text
2023: bottom 44.0%, top 60.0%
2024: bottom 66.7%, top 45.8%   <- reversal
2025: bottom 30.0%, top 65.0%
2026: bottom 36.4%, top 54.5%
```

Fold q50 Spearman was approximately 0.087, 0.084, 0.228 and 0.051 for 2023–2026 respectively.

## 3. Central interpretation

The most important distinction between Experiments B and C is the classification of the W at the current point in time.

Experiment B effectively uses:

```text
W_t_class = classification derived from retrospective historical Strategy outcomes
```

Experiment C uses:

```text
W_t_class = classification derivable from information available as of t
```

The CNN is not the main changed variable between these two questions. The information structure feeding Layer1 selection is.

This makes the observed degradation scientifically useful rather than simply a failed model run. It shows that the strength of the measured Layer2 conditional signal depends materially on how Layer1 defines the selected population.

At present the evidence supports all of the following simultaneously:

- The retrospective Layer1-selected population contains a strong price/volume-conditioned future 3-day separation that a small CNN can learn chronologically OOS.
- When Layer1 itself is reconstructed as-of-t, pooled Layer2 ordering remains positive but is substantially weaker.
- The fully causal experiment does not show stable year-by-year separation: 2024 reverses, and 2026 top-bucket mean return is approximately flat despite better top-bucket P(up).
- Therefore the current evidence is not sufficient to claim a stable ~65% real-time Layer2 win probability.
- The result also does not justify concluding that historical price/volume contains no useful signal. The causal pooled distribution still shifts in the expected direction, just much more weakly.

## 4. Important conceptual question exposed by the experiment

The causal test exposes a definition issue that should be discussed before modifying the model.

Layer1 was originally conceived as a statistical characterization of historical Strategy opportunities: after historical W outcomes are known, U/C/Q describe whether those historical regions were favorable, unfavorable, or neutral under the fixed Strategy. Layer2 then asks whether the price/volume structure preceding or associated with such historical states contains a reusable pattern.

That is not automatically identical to requiring the *current unfinished W* to have a fully knowable H/N/L label in real time.

Consequently, Experiment C may be testing a stricter operational interpretation of Layer1 rather than merely removing leakage from Experiment B. Whether that stricter interpretation is the intended production semantics remains an open research question.

This distinction must not be resolved implicitly by code.

## 5. Attribution is not yet isolated

Experiment C changed more than one aspect of Layer1 information availability. In particular, it combined the current-day forced-exit rule with prefix-only reconstruction of local extrema.

Therefore the reduction from the retrospective result to the as-of result cannot yet be attributed uniquely to one mechanism.

Possible contributors include:

```text
A. current-day force-close of unfinished historical paths
B. loss of retrospective confirmation of 5/10-session extrema
C. resulting changes in U/C/Q and H/N/L W membership
D. interaction of the above with the population presented to Layer2
```

No conclusion should yet state that the forced-exit rule alone caused the degradation.

## 6. Current neutral conclusion

The strongest current conclusion is:

> Layer2 has demonstrated that a small CNN can extract a nontrivial relationship between normalized historical price/volume structure and the next 3-session realized price distribution inside Layer1-selected historical regions. That relationship survives chronological OOS testing when Layer1 states are retrospective. When Layer1 W classification is instead reconstructed strictly as-of the current date, the relationship weakens substantially and is not stable across every OOS year. This difference is itself a key research result because it identifies Layer1 information semantics, rather than CNN capacity alone, as an important variable.

The current experiments should therefore be treated as evidence about conditional statistical structure, not as proof of a deployable trading strategy or calibrated probability forecast.

## 7. Next discussion, not yet an approved implementation

Before changing the CNN, the next useful research decision is to clarify which Layer1 question is intended:

```text
Historical-label question:
Given completed historical Strategy outcomes, which historical W were H/N/L,
and can their preceding price/volume structures teach Layer2 a reusable signal?

versus

Real-time-state question:
Standing at t, what H/N/L classification can be computed for the current W
using only information available through t, and does Layer2 remain predictive conditional on that state?
```

These are related but not identical statistical questions. The difference should be resolved explicitly before interpreting the causal degradation as either leakage removal or a change of research target.

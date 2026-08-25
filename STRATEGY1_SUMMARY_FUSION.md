# Strategy 1 — CNN + Summary20 Fusion Experiment

This document records the 20-feature fusion test. It does not change frozen Strategy 1 mechanics or the Oracle definition.

## Question

> Does adding the same 20 fixed causal summary features used by the Summary Ridge baseline improve Daily CNN A's OOS prediction of 30D raw Strategy 1 Oracle Value?

The purpose is to test whether the low-dimensional information that has looked useful at the portfolio-selection layer adds signal beyond the raw 50-session OHLCV tensor.

## Fixed setup

- Instrument: SPY
- Input history: 50 daily sessions
- Target: 30D raw Strategy 1 Oracle Value
- Training: Sliding-260
- OOS evaluation: same four purged chronological 60-session folds
- Purge: 60 sessions
- Seeds: `20260821,20260822,20260823,20260824,20260825`
- Epochs: 20
- Learning rate: `3e-3`
- Huber delta: `0.01`
- No random split
- Primary metrics: fold-wise OOS Spearman, top-20% realized Oracle Value lift, fold stability, seed stability
- MAE: secondary calibration diagnostic

## Models

```text
CNN_A
  existing TrendCNNJoint
  input = [batch, 5, 50]
  params = 2764

CNN_A_PLUS_SUMMARY20
  identical Model-A CNN encoder through 16-dimensional global pooled representation
  + 20 causal summary features
  concatenate 16 + 20 = 36 dimensions
  -> hidden width 8
  -> 4 horizon outputs
  -> Tanh
  params = 2924
```

The fusion test intentionally does not replace the Model-A convolution encoder.

## Summary20 features

The 20 features are exactly the existing Summary Ridge feature set.

Lookbacks:

```text
5 / 10 / 20 / 50 sessions
```

For each lookback:

```text
close_sum
close_std
range_mean
abs_close_mean
volume_z_mean
```

Total:

```text
4 lookbacks x 5 statistics = 20 features
```

All features are calculated from the same causal 50-session input window. No Ridge prediction is used as an input and no future target information enters the feature vector.

## Standardization

Summary features are standardized independently inside each fold using only the Sliding-260 training window:

```text
mean_train = mean(summary_train)
std_train = std(summary_train)
z_train = (summary_train - mean_train) / std_train
z_test = (summary_test - mean_train) / std_train
```

OOS data is never used to fit feature normalization.

## Predeclared interpretation gate

The hypothesis is supported only if `CNN_A_PLUS_SUMMARY20` shows a meaningful and reasonably stable improvement in ranking-oriented metrics relative to `CNN_A` on the same OOS dates.

```text
PASS direction:
- higher mean cross-seed Spearman;
- positive Spearman remains stable across seeds;
- fold-level advantage is not concentrated in only one fold;
- top20 realized Oracle lift is preserved or improved.

NOT a pass:
- MAE improves while Spearman/top20 lift deteriorate;
- improvement is driven by one seed or one fold;
- top20 lift materially worsens despite a small Spearman gain.
```

## Observed result

Dataset and evaluation remained the fixed formal setup:

```text
windows = 623
folds = 4
horizon = 30
train = Sliding-260
purge = 60
test_size = 60
summary_dim = 20
```

Cross-seed results:

```text
CNN_A
  Spearman mean = +0.233705
  Spearman std = 0.103928
  positive seeds = 5/5
  top20 lift mean = +0.004189
  top20 lift std = 0.001429
  positive lift seeds = 5/5
  MAE mean = 0.114506

CNN_A_PLUS_SUMMARY20
  Spearman mean = -0.133411
  Spearman std = 0.231136
  positive seeds = 2/5
  top20 lift mean = +0.000101
  top20 lift std = 0.003473
  positive lift seeds = 2/5
  MAE mean = 0.080978
```

Fold-wise cross-seed Spearman means:

```text
Fold 1: CNN_A +0.202796 | Fusion -0.306839
Fold 2: CNN_A +0.034425 | Fusion -0.058394
Fold 3: CNN_A +0.035332 | Fusion -0.041346
Fold 4: CNN_A +0.662265 | Fusion -0.127065
```

Fold-wise top20 lift means:

```text
Fold 1: CNN_A +0.002844 | Fusion -0.002051
Fold 2: CNN_A +0.000012 | Fusion -0.000083
Fold 3: CNN_A +0.000007 | Fusion +0.000000
Fold 4: CNN_A +0.013894 | Fusion +0.002540
```

## Interpretation

The 20-feature fusion **fails** the predeclared prediction gate.

The fusion model improves MAE from `0.114506` to `0.080978`, but this is a secondary calibration metric. The primary ranking metrics deteriorate sharply:

```text
Spearman: +0.233705 -> -0.133411
positive Spearman seeds: 5/5 -> 2/5
top20 lift: +0.004189 -> +0.000101
positive top20-lift seeds: 5/5 -> 2/5
```

The degradation is not confined to one fold. The fusion has lower mean Spearman than CNN A in all four folds, including the strongest original CNN regime in Fold 4.

Therefore the low-dimensional Summary20 feature set should **not** be concatenated directly into the CNN prediction head under this fixed architecture/training setup.

This result does not invalidate Summary Ridge as a separate causal portfolio baseline. It shows that information useful to a simple linear filter does not automatically improve the CNN when fused directly into its learned representation. The two models can be useful for different decision layers.

Current status:

```text
CNN_A
  remains the primary prediction-ranking model.

CNN_A_PLUS_SUMMARY20
  fail / hold; do not promote to portfolio testing.

SUMMARY_RIDGE
  remains a separate low-dimensional baseline and the strongest observed causal portfolio filter so far, with small-sample caveat.
```

## Run

```bash
futureview-strategy1-summary-fusion
```

# Strategy 1 — CNN + Summary20 Fusion Experiment

This document predeclares the 20-feature fusion test before observing results. It does not change frozen Strategy 1 mechanics or the Oracle definition.

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

## Interpretation gate

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

This is a prediction-layer experiment. It does not promote the fusion model to portfolio testing unless the prediction gate is first supported.

## Run

```bash
futureview-strategy1-summary-fusion
```

# Strategy 1 — Causal OOS Portfolio Result

This document records the first prediction-driven out-of-sample portfolio test for Strategy 1. It is an experimental result only and does not change the frozen Strategy 1 mechanics in `STRATEGY1.md`.

## Fixed setup

- Target: 30D raw Strategy 1 Oracle Value
- Training history: Sliding-260
- CNN: TrendCNNJoint / CNN A
- CNN aggregation: five fixed seeds, ensembled
- OOS folds: four purged chronological folds
- Purge: 60 sessions
- Entry gate: prediction at close `t` can authorize only an Entry1 event at `t+1`
- Gate threshold: 80th percentile of predictions generated from the contemporaneous training window
- Campaign horizon: at most 30 sessions
- Portfolio capital: flat-only; overlapping campaigns are not allowed to reuse capital
- Transaction costs/slippage remain zero in v0

This portfolio test is different from the earlier prediction test. The earlier prediction test asks whether predictions rank future Oracle Value OOS. This portfolio test asks whether a causal rule based on those predictions produces superior realized portfolio economics.

## OOS prediction-gate behavior

Observed OOS signal rates by fold were:

```text
CNN ensemble:
Fold 1 = 3.3%
Fold 2 = 0.0%
Fold 3 = 0.0%
Fold 4 = 8.3%

Summary Ridge:
Fold 1 = 45.0%
Fold 2 = 0.0%
Fold 3 = 0.0%
Fold 4 = 8.3%
```

Although the gate quantile is fixed at 80% on the training prediction distribution, OOS signal rates need not be 20%. The current result shows substantial prediction-scale / distribution shift, especially for the CNN.

## Portfolio results

```text
ALWAYS_ON
campaigns = 10
total_return = 0.045188
annualized_return = 0.042272
max_drawdown = 0.037280
win_rate = 0.500000
avg_campaign_return = 0.004515
exposure_days = 94.166667
exposure_ratio = 0.350062
return_per_exposure_day = 0.000480

SUMMARY_RIDGE_FILTERED
campaigns = 3
total_return = 0.048026
annualized_return = 0.044923
max_drawdown = 0.016140
win_rate = 1.000000
avg_campaign_return = 0.015820
exposure_days = 31.666667
exposure_ratio = 0.117720
return_per_exposure_day = 0.001517

CNN_ENSEMBLE_FILTERED
campaigns = 1
total_return = 0.027515
annualized_return = 0.025754
max_drawdown = 0.016140
win_rate = 1.000000
avg_campaign_return = 0.027515
exposure_days = 13.000000
exposure_ratio = 0.048327
return_per_exposure_day = 0.002117

HINDSIGHT_ENTRY_UPPER
campaigns = 6
total_return = 0.083854
annualized_return = 0.078352
max_drawdown = 0.015665
win_rate = 1.000000
avg_campaign_return = 0.013570
exposure_days = 58.166667
exposure_ratio = 0.216233
return_per_exposure_day = 0.001442
```

`HINDSIGHT_ENTRY_UPPER` is a hindsight reference that selects profitable non-overlapping Entry1 campaigns with future knowledge. It is not a tradable strategy and is not the same object as the per-date Oracle Value label.

## Current interpretation

The first causal portfolio test does **not** establish CNN portfolio superiority.

The CNN retains the strongest prior evidence for OOS ranking of 30D Oracle Value, but the fixed training-distribution 80th-percentile gate produces very sparse OOS signals. Only one CNN-filtered campaign is traded, so its high return per exposure-day is not sufficient evidence of robust economic superiority.

The Summary Ridge filter is currently the strongest realized tradable result in this sample: it slightly exceeds always-on total return while using much less exposure and experiencing a substantially smaller maximum drawdown. However, it contains only three campaigns, so this remains a small-sample result.

The main distinction is now:

```text
Prediction test:
Does the model rank future 30D Oracle Value correctly on unseen dates?

Portfolio test:
Can those predictions be converted causally into entry authorization and superior realized P&L?
```

CNN currently has positive evidence on the first question but has not passed the second.

## Next methodological issue

The main observed failure mode is not obviously the CNN ranking itself; it is the mapping from raw prediction level to a live trading gate. Training-window 80th-percentile thresholds do not preserve an approximately 20% OOS signal rate because prediction distributions shift across regimes.

A future gate comparison should therefore preserve the model, horizon, target, folds, seeds, and predeclared 80% cutoff while comparing the current absolute training-distribution threshold with a fully causal relative-rank / rolling-percentile gate. This comparison must not choose a new cutoff from OOS results.

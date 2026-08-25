# Strategy 1 — Causal OOS Portfolio Result

This document records prediction-driven out-of-sample portfolio tests for Strategy 1. It is an experimental result only and does not change the frozen Strategy 1 mechanics in `STRATEGY1.md`.

## Fixed setup

- Target: 30D raw Strategy 1 Oracle Value
- Training history: Sliding-260
- CNN: TrendCNNJoint / CNN A
- CNN aggregation: five fixed seeds, ensembled
- OOS folds: four purged chronological folds
- Purge: 60 sessions
- Entry gate: prediction at close `t` can authorize only an Entry1 event at `t+1`
- Gate quantile: fixed at 80%
- Campaign horizon: at most 30 sessions
- Portfolio capital: flat-only; overlapping campaigns are not allowed to reuse capital
- Transaction costs/slippage remain zero in v0

This portfolio test is different from the earlier prediction test. The earlier prediction test asks whether predictions rank future Oracle Value OOS. This portfolio test asks whether a causal rule based on those predictions produces superior realized portfolio economics.

## First gate: absolute training-distribution P80

The first CNN gate used the 80th percentile of predictions generated from the contemporaneous training window as an absolute score threshold for the whole subsequent OOS fold.

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

Although the gate quantile is fixed at 80% on the training prediction distribution, OOS signal rates need not be 20%. The result shows substantial prediction-scale / distribution shift, especially for the CNN.

## First portfolio results

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

## Causal rolling-rank P80 gate result

The second gate experiment preserved the same Daily CNN A model, target, training history, folds, seeds, Strategy 1 mechanics, and fixed 80% cutoff. Only the mapping from raw prediction level to gate decision changed.

For each OOS prediction `j` inside a fold, the causal rank reference was:

```text
fold training predictions
+ OOS predictions 0 ... j-1
```

The current OOS prediction and all future OOS predictions were excluded. The gate authorized next-session Entry1 when the causal percentile was at least 80%.

Observed signal rates were:

```text
Fold 1: absolute = 3.3% | causal rank = 3.3% | mean rank percentile = 0.370
Fold 2: absolute = 0.0% | causal rank = 0.0% | mean rank percentile = 0.351
Fold 3: absolute = 0.0% | causal rank = 0.0% | mean rank percentile = 0.435
Fold 4: absolute = 8.3% | causal rank = 10.0% | mean rank percentile = 0.382
```

The causal-rank gate therefore did not materially restore OOS signal frequency. In three folds it was identical to the absolute gate; in Fold 4 it increased the signal rate only from 8.3% to 10.0%.

Portfolio results were exactly the same for the two CNN gates:

```text
CNN_ABSOLUTE_TRAIN_P80
campaigns = 1
total_return = 0.027515
annualized_return = 0.025754
max_drawdown = 0.016140
win_rate = 1.000000
avg_campaign_return = 0.027515
exposure_days = 13.000000
holding_days = 26
exposure_ratio = 0.048327
return_per_exposure_day = 0.002117

CNN_CAUSAL_RANK_P80
campaigns = 1
total_return = 0.027515
annualized_return = 0.025754
max_drawdown = 0.016140
win_rate = 1.000000
avg_campaign_return = 0.027515
exposure_days = 13.000000
holding_days = 26
exposure_ratio = 0.048327
return_per_exposure_day = 0.002117
```

Both gates selected only the same campaign:

```text
start = 2026-04-13
end = 2026-05-19
return = 0.027515
exposure_days = 13.0
```

The baselines remained:

```text
ALWAYS_ON
campaigns = 10
total_return = 0.045188
max_drawdown = 0.037280
return_per_exposure_day = 0.000480

SUMMARY_RIDGE_FILTERED
campaigns = 3
total_return = 0.048026
max_drawdown = 0.016140
return_per_exposure_day = 0.001517

HINDSIGHT_ENTRY_UPPER
campaigns = 6
total_return = 0.083854
max_drawdown = 0.015665
return_per_exposure_day = 0.001442
```

## Updated interpretation

The causal rolling-rank normalization **does not pass** the gate-mapping test.

The result rules out a simple version of the calibration-drift explanation: replacing a fixed absolute training P80 threshold with an expanding causal percentile rank over training predictions plus prior OOS predictions does not materially change the authorization pattern or portfolio economics.

This does not prove that calibration is irrelevant. The causal rank reference is still dominated by the 260 training predictions at the start of each fold, and the observed mean OOS percentiles remain well below 0.50 in every fold. However, under the predeclared gate tested here, relative-rank normalization is insufficient.

The current strongest conclusions are:

```text
Prediction layer:
Daily CNN A still has positive prior evidence for OOS ranking of 30D Oracle Value.

Gate layer:
Absolute P80 and causal expanding-rank P80 both remain too sparse.

Portfolio layer:
CNN portfolio superiority is still not established.
Summary Ridge remains the strongest realized tradable filter in this sample,
although it has only three campaigns and therefore remains small-sample evidence.
```

The single CNN campaign has attractive return per exposure-day, but one campaign is not enough to support a robust economic claim.

## Next experiment: recent-OOS-only rolling P80

The next gate experiment is predeclared before observing its result. It keeps the Daily CNN A model, 30D raw Oracle target, Sliding-260 training, four OOS folds, five seeds, Strategy 1 mechanics, and fixed 80% cutoff unchanged.

The new reference deliberately excludes training predictions. OOS predictions are treated as one chronological stream across fold boundaries.

Fixed rule:

```text
recent_oos_window = 60 predictions
global OOS warm-up = first 60 OOS predictions
training predictions excluded from rank reference
current prediction excluded
future predictions excluded
```

For OOS prediction `j >= 60`, define:

```text
history_j = OOS predictions[j-60 : j]
percentile_j = mean(history_j <= prediction_j)
```

The gate authorizes next-session Entry1 only when:

```text
percentile_j >= 0.80
```

The first 60 OOS predictions are strict warm-up and cannot authorize an entry. The 60-observation window is fixed in advance because it corresponds to one complete existing OOS fold and avoids tuning a new short lookback from results.

This design tests whether a genuinely recent OOS-relative calibration rule can restore useful signal frequency when the training-score distribution is removed from the rank reference.

Interpretation is predeclared:

```text
If recent-OOS rank materially increases signal frequency and improves portfolio economics:
  recent prediction-scale adaptation is a plausible gate bottleneck.

If signal frequency increases but economics do not improve:
  calibration was suppressing activity, but CNN ranking is not sufficient for entry selection.

If signal frequency remains sparse or portfolio remains one-campaign driven:
  recent relative calibration does not solve the portfolio conversion problem.

If results depend mainly on one fold:
  treat as regime-specific, not a pass.
```

Run:

```bash
futureview-strategy1-oos-portfolio-recent-rank
```

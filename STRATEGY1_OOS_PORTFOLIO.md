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

## Causal expanding-rank P80 result

For each OOS prediction, the causal rank reference used the fold training predictions plus prior OOS predictions, excluding the current and future OOS predictions.

Observed signal rates were:

```text
Fold 1: absolute = 3.3% | causal rank = 3.3% | mean rank percentile = 0.370
Fold 2: absolute = 0.0% | causal rank = 0.0% | mean rank percentile = 0.351
Fold 3: absolute = 0.0% | causal rank = 0.0% | mean rank percentile = 0.435
Fold 4: absolute = 8.3% | causal rank = 10.0% | mean rank percentile = 0.382
```

The causal-rank gate did not materially restore OOS signal frequency. Portfolio results were exactly the same as the absolute gate: one campaign, total return `0.027515`, and return per exposure-day `0.002117`.

## Recent-OOS-only rolling P80 result

The third gate experiment removed training predictions from the rank reference entirely. OOS predictions were treated as one chronological stream across folds.

Fixed rule:

```text
recent_oos_window = 60 predictions
global OOS warm-up = first 60 OOS predictions
training predictions excluded
current prediction excluded
future predictions excluded
P80 cutoff unchanged
```

Observed signal behavior:

```text
Fold 1: eligible 0/60  | recent-rank signal rate = 0.000
Fold 2: eligible 60/60 | recent-rank signal rate = 0.100 | mean percentile = 0.401944
Fold 3: eligible 60/60 | recent-rank signal rate = 0.300 | mean percentile = 0.562778
Fold 4: eligible 60/60 | recent-rank signal rate = 0.267 | mean percentile = 0.431111
```

This gate **did restore activity** relative to the absolute and expanding-rank gates. The key question is therefore no longer whether recent relative calibration can increase signal frequency; it can. The question is whether the extra signals are economically useful.

Portfolio result:

```text
CNN_RECENT_OOS_RANK60_P80
campaigns = 3
total_return = 0.016356
annualized_return = 0.015314
max_drawdown = 0.017216
win_rate = 0.333333
avg_campaign_return = 0.005544
exposure_days = 26.666667
holding_days = 49
exposure_ratio = 0.099133
return_per_exposure_day = 0.000613
```

Selected campaigns:

```text
2025-12-04 -> 2025-12-31   return = -0.008027
2026-01-27 -> 2026-02-03   return = -0.002856
2026-04-13 -> 2026-05-19   return = +0.027515
```

The two incremental campaigns admitted by recent-rank normalization were both losing campaigns. The gate retained the same profitable April 2026 campaign that the absolute gate had already selected.

Baseline comparison:

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

CNN_ABSOLUTE_TRAIN_P80
campaigns = 1
total_return = 0.027515
max_drawdown = 0.016140
return_per_exposure_day = 0.002117

CNN_RECENT_OOS_RANK60_P80
campaigns = 3
total_return = 0.016356
max_drawdown = 0.017216
return_per_exposure_day = 0.000613

HINDSIGHT_ENTRY_UPPER
campaigns = 6
total_return = 0.083854
max_drawdown = 0.015665
return_per_exposure_day = 0.001442
```

## Updated interpretation

The recent-OOS-only rank gate **fails the portfolio-conversion test**.

It successfully addresses the sparse-activity symptom, but the added activity is not economically selective. This is the strongest gate-layer result so far because it separates two hypotheses:

```text
Hypothesis A:
CNN gates are sparse only because prediction scale drifts.
Result: partially supported. Recent OOS-relative ranking restores signal frequency.

Hypothesis B:
Once signal frequency is restored, CNN ranking can authorize better Entry1 campaigns.
Result: not supported. The extra admitted campaigns are losses and total portfolio return falls.
```

Therefore the main bottleneck is no longer best described as simple calibration drift. Under the tested fixed P80 policies, Daily CNN A's OOS ranking signal does not reliably translate into useful Strategy 1 Entry1 authorization.

Current status:

```text
Prediction layer:
Daily CNN A retains prior positive evidence for ranking 30D Oracle Value.

Gate layer:
Absolute P80 = too sparse.
Expanding causal-rank P80 = too sparse.
Recent-OOS rank60 P80 = restores activity but adds losing campaigns.

Portfolio layer:
CNN portfolio superiority is not established.
Summary Ridge remains the strongest realized tradable filter in this sample,
with 3 campaigns, +0.048026 total return, lower drawdown, and higher exposure efficiency than always-on.
```

The recent-rank gate should be marked fail/hold. Further gate tuning on this same OOS sample would risk turning into post-hoc threshold/lookback optimization and should not be treated as fresh validation.

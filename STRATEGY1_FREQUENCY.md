# Strategy 1 — Input Frequency Experiment

This document records the controlled comparison of daily versus higher-frequency causal OHLCV inputs for Strategy 1 prediction. It is an experimental result only and does not modify the frozen Strategy 1 mechanics or Oracle definition in `STRATEGY1.md`.

## Research question

> Holding approximately the same 50 trading-session historical span fixed, does increasing observation frequency / data density improve Model A's OOS ranking of future 30-session Strategy 1 Oracle Value?

The target remains daily Strategy 1 `OracleValue30`. Intraday data is used only as model input. Strategy 1 entry, add-on, exit, spacing, and Oracle-label mechanics remain daily and unchanged.

## Fixed prediction setup

- Instrument: SPY
- Target: 30D raw Strategy 1 Oracle Value
- Training: Sliding-260
- Model family: CNN A / joint OHLCV
- Seeds: `20260821, 20260822, 20260823, 20260824, 20260825`
- Epochs: 20
- Learning rate: `3e-3`
- Huber delta: `0.01`
- Purge: 60 sessions
- Test size: 60 sessions when full folds are available
- Primary metrics: OOS Spearman, top-20% realized Oracle Value lift, cross-seed stability
- MAE: secondary calibration diagnostic

Input variants:

```text
DAILY_50_K5_10_20
  50 daily observations
  kernels = 5 / 10 / 20

RTH2_100_K5_10_20
  50 sessions x 2 regular-session observations = 100 observations
  kernels = 5 / 10 / 20

RTH2_100_K10_20_40
  same 100 intraday observations
  kernels = 10 / 20 / 40
```

The two intraday observations per regular session are:

```text
09:30-13:30 ET
13:30-16:00 ET
```

The second bar is 2.5 hours because the US regular cash session is 6.5 hours. The experiment therefore uses two session-aware intraday observations rather than pretending that both are full four-hour bars.

## Massive limited-history pilot

Massive Basic history entitlement produced only enough common Daily/Intraday data for one limited-history OOS block.

```text
common_windows = 366
train = Sliding-260
purge = 60
OOS test = 46 sessions
OOS period = 2026-03-24 through 2026-05-28
folds = 1
```

Cross-seed results:

```text
DAILY_50_K5_10_20
  Spearman mean = +0.708543
  Spearman std  = 0.273169
  positive seeds = 5/5
  top20 lift mean = +0.013785
  top20 lift std  = 0.004493
  positive lift seeds = 5/5
  MAE mean = 0.118978

RTH2_100_K5_10_20
  Spearman mean = +0.864708
  Spearman std  = 0.013241
  positive seeds = 5/5
  top20 lift mean = +0.016180
  top20 lift std  = 0.001167
  positive lift seeds = 5/5
  MAE mean = 0.119895

RTH2_100_K10_20_40
  Spearman mean = -0.631144
  Spearman std  = 0.315782
  positive seeds = 0/5
  top20 lift mean = -0.009253
  top20 lift std  = 0.009591
  positive lift seeds = 1/5
  MAE mean = 0.047939
```

This was a preliminary pass only. The single 46-session 2026 regime was already known to be unusually favorable for CNN A, so the strong RTH2 result was never treated as a long-run estimate.

## Alpaca matched-feed multi-fold replication

The canonical replication uses Alpaca IEX 30-minute SPY data for both input variants:

```text
Alpaca IEX 30m RTH bars
  -> aggregate complete regular session -> DAILY_50_K5_10_20 input
  -> aggregate into 09:30-13:30 / 13:30-16:00 -> RTH2_100 input
```

This removes the input-source confound. Daily and Intraday inputs come from the same provider/feed and differ primarily in sampling frequency / observation density. Oracle labels remain the same frozen daily Strategy 1 labels.

Observed matched sample:

```text
common_windows = 613
folds = 3
first common window = 2023-12-05
last common window = 2026-05-28
train = Sliding-260
purge = 60
test size = 60
provider = Alpaca
feed = IEX
timeframe = 30Min
```

Cross-seed results across the three OOS folds:

```text
DAILY_50_K5_10_20
  Spearman mean = +0.067405
  Spearman std  = 0.151288
  positive seed summaries = 3/5
  top20 lift mean = +0.000358
  top20 lift std  = 0.000728
  positive lift seed summaries = 3/5
  MAE mean = 0.112047

RTH2_100_K5_10_20
  Spearman mean = +0.072512
  Spearman std  = 0.164803
  positive seed summaries = 3/5
  top20 lift mean = +0.000094
  top20 lift std  = 0.000870
  positive lift seed summaries = 3/5
  MAE mean = 0.111104

RTH2_100_K10_20_40
  Spearman mean = -0.074563
  Spearman std  = 0.046404
  positive seed summaries = 0/5
  top20 lift mean = +0.000465
  top20 lift std  = 0.000789
  positive lift seed summaries = 3/5
  MAE mean = 0.043536
```

Fold-seed mean Spearman:

```text
Fold 1:
  Daily K5/10/20 = +0.043709
  RTH2 K5/10/20  = +0.101321
  RTH2 K10/20/40 = +0.166569

Fold 2:
  Daily K5/10/20 = +0.045867
  RTH2 K5/10/20  = +0.029268
  RTH2 K10/20/40 = -0.107643

Fold 3:
  Daily K5/10/20 = +0.112637
  RTH2 K5/10/20  = +0.086947
  RTH2 K10/20/40 = -0.282613
```

Fold-seed mean top20 lift:

```text
Fold 1:
  Daily K5/10/20 = +0.000108
  RTH2 K5/10/20  = -0.000715
  RTH2 K10/20/40 = +0.002584

Fold 2:
  Daily K5/10/20 = -0.000113
  RTH2 K5/10/20  = -0.000128
  RTH2 K10/20/40 = -0.000254

Fold 3:
  Daily K5/10/20 = +0.001080
  RTH2 K5/10/20  = +0.001124
  RTH2 K10/20/40 = -0.000936
```

## Interpretation after Alpaca replication

The frequency hypothesis is **not established** under the current fixed setup.

`RTH2_100_K5_10_20` has only a negligible mean Spearman advantage over the matched-feed daily baseline:

```text
+0.067405 -> +0.072512
```

but it does not improve seed stability:

```text
Spearman std: 0.151288 -> 0.164803
```

and its mean top20 lift is lower:

```text
+0.000358 -> +0.000094
```

Both Daily and RTH2 K5/10/20 have only `3/5` positive seed summaries for both Spearman and top20 lift. Fold-level results are mixed: RTH2 is better on mean Spearman only in Fold 1, while Daily is better in Folds 2 and 3. Top20 lift is likewise mixed and does not show a stable RTH2 advantage.

Therefore the strong Massive one-fold result is best interpreted as regime-specific rather than evidence that doubling observation count generally improves prediction.

`RTH2_100_K10_20_40` remains a fail/hold configuration for ranking. Its lower MAE again does not imply better usefulness because the primary ranking objective is negative across all five seed summaries. Its parameter count is also larger (`4164` vs `2764`), so it is not a clean one-variable control.

## Current conclusion

Current evidence supports:

```text
Frequency hypothesis: HOLD / NOT ESTABLISHED

Daily-50 K5/10/20:
  remains the primary input baseline.

RTH2-100 K5/10/20:
  does not outperform Daily consistently across Alpaca matched-feed OOS folds.
  keep as research variant, not promoted.

RTH2-100 K10/20/40:
  fail / hold.
```

The earlier Massive pilot remains useful as evidence that intraday information can become highly informative in some regimes, but it does not survive the broader matched-feed replication as a general advantage.

## Provider and caching policy

The default frequency runner uses Alpaca Historical Market Data with the IEX feed. Historical chunks are cached locally under:

```text
.cache/futureview/alpaca/
```

Cache files are compressed CSV and are excluded from Git.

Required environment variables:

```bash
APCA_API_KEY_ID
APCA_API_SECRET_KEY
```

Commands:

```bash
futureview-alpaca-data-smoke
futureview-strategy1-frequency-compare
```

The prior Massive implementation is retained only for reproducibility:

```bash
futureview-strategy1-frequency-compare-massive
```

## Next decision

Do not tune the frequency architecture based on these results yet. The clean result is that simply doubling observations from 50 daily bars to 100 two-per-session bars does not produce a reproducible improvement for 30D Strategy 1 Oracle ranking under Model A.

If frequency is revisited later, a better-controlled next experiment would isolate receptive-field scaling while holding parameter count fixed, for example with dilation rather than larger convolution kernels. That should be treated as a new experiment rather than as a rescue tuning step for the current failed/hold frequency hypothesis.

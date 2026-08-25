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
- Primary metrics: OOS Spearman, top-20% realized Oracle Value lift, cross-seed stability
- MAE: secondary calibration diagnostic
- No random split

## Input variants

```text
DAILY_50_K5_10_20
  50 daily observations
  kernels = 5 / 10 / 20
  params = 2764

RTH2_100_K5_10_20
  50 sessions x 2 regular-session observations = 100 observations
  kernels = 5 / 10 / 20
  params = 2764

RTH2_100_K5_10_20_DILATION2
  same 100 intraday observations
  kernels = 5 / 10 / 20
  dilation = 2
  effective widths = 9 / 19 / 39 intraday bars ~= 4.5 / 9.5 / 19.5 sessions
  params = 2764

RTH2_100_K10_20_40
  same 100 intraday observations
  kernels = 10 / 20 / 40
  params = 4164
```

The two intraday observations per regular session are:

```text
09:30-13:30 ET
13:30-16:00 ET
```

The second bar is 2.5 hours because the US regular cash session is 6.5 hours. The experiment therefore uses two session-aware intraday observations rather than pretending that both are full four-hour bars.

## Massive limited-history result

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

This was a preliminary frequency pass only. It contained one favorable 2026 regime and was not sufficient for a general conclusion.

## Alpaca matched-feed multi-fold replication

The canonical replication uses Alpaca IEX 30-minute SPY data for both Daily and Intraday model inputs:

```text
Alpaca IEX 30m RTH bars
  -> aggregate complete regular session -> DAILY_50_K5_10_20 input
  -> aggregate into 09:30-13:30 / 13:30-16:00 -> RTH2_100 input
```

The Oracle labels remain the frozen daily Strategy 1 labels from the existing daily Oracle pipeline. Thus the input source is matched while the target definition remains unchanged.

Observed canonical setup:

```text
common_windows = 613
folds = 3
first common date = 2023-12-05
last common date = 2026-05-28
train = Sliding-260
purge = 60
test size = 60 sessions per fold
provider = Alpaca
feed = IEX
input timeframe = 30Min
```

Cross-seed results before the dilation control:

```text
DAILY_50_K5_10_20
  Spearman mean = +0.067405
  Spearman std  = 0.151288
  positive seeds = 3/5
  top20 lift mean = +0.000358
  top20 lift std  = 0.000728
  positive lift seeds = 3/5
  MAE mean = 0.112047

RTH2_100_K5_10_20
  Spearman mean = +0.072512
  Spearman std  = 0.164803
  positive seeds = 3/5
  top20 lift mean = +0.000094
  top20 lift std  = 0.000870
  positive lift seeds = 3/5
  MAE mean = 0.111104

RTH2_100_K10_20_40
  Spearman mean = -0.074563
  Spearman std  = 0.046404
  positive seeds = 0/5
  top20 lift mean = +0.000465
  top20 lift std  = 0.000789
  positive lift seeds = 3/5
  MAE mean = 0.043536
```

Fold-level cross-seed Spearman means:

```text
Fold 1: Daily +0.043709 | RTH2 K5/10/20 +0.101321 | RTH2 K10/20/40 +0.166569
Fold 2: Daily +0.045867 | RTH2 K5/10/20 +0.029268 | RTH2 K10/20/40 -0.107643
Fold 3: Daily +0.112637 | RTH2 K5/10/20 +0.086947 | RTH2 K10/20/40 -0.282613
```

The matched-feed multi-fold result did not establish a general higher-frequency advantage. `RTH2_100_K5_10_20` had almost the same mean Spearman as the Daily baseline, slightly worse seed dispersion, and lower top-20% Oracle lift.

## Parameter-matched dilation control

To test whether the raw RTH2 model failed because K5/10/20 spans shorter calendar time in intraday coordinates, a predeclared parameter-matched dilation control was added:

```text
RTH2_100_K5_10_20_DILATION2
  input = same Alpaca IEX RTH2-100 tensor
  kernels = 5 / 10 / 20
  dilation = 2
  params = 2764
```

The implementation contains a runtime guard requiring the dilation model parameter count to equal the Daily Model A parameter count exactly.

Observed cross-seed result:

```text
RTH2_100_K5_10_20_DILATION2
  Spearman mean = +0.048054
  Spearman std  = 0.099043
  positive seeds = 3/5
  top20 lift mean = +0.000014
  top20 lift std  = 0.000584
  positive lift seeds = 3/5
  MAE mean = 0.112242
```

Comparison:

```text
DAILY_50_K5_10_20
  Spearman = +0.067405
  top20 lift = +0.000358

RTH2_100_K5_10_20
  Spearman = +0.072512
  top20 lift = +0.000094

RTH2_100_K5_10_20_DILATION2
  Spearman = +0.048054
  top20 lift = +0.000014
```

Fold-level dilation Spearman means were:

```text
Fold 1 = -0.084361
Fold 2 = +0.065523
Fold 3 = +0.162999
```

Fold-level dilation top20-lift means were:

```text
Fold 1 = -0.000860
Fold 2 = -0.000246
Fold 3 = +0.001148
```

The dilation control therefore **fails to establish a higher-frequency advantage**. Matching the approximate calendar receptive field while holding parameter count fixed does not improve the intraday model over either the raw RTH2 condition or the Daily baseline.

This materially weakens the hypothesis that the earlier RTH2 result was limited mainly because the undilated intraday kernels covered too little calendar time.

## Current conclusion

The frequency hypothesis is now **HOLD / NOT ESTABLISHED**.

The strongest supported interpretation is:

> Under the current Model A, 30D RAW_ORACLE target, Sliding-260 training policy, and 50-session historical context, doubling the number of observations from 50 daily bars to 100 intraday RTH bars does not produce a reproducible multi-fold OOS ranking or top-quantile advantage.

The strong Massive one-fold result is best treated as regime-specific. Neither same-parameter raw RTH2 nor the parameter-matched dilation control reproduces that advantage across the Alpaca matched-feed folds.

Current model status:

```text
1. CNN A / Daily-50 / K5-10-20
   Primary validated baseline.

2. CNN A / RTH2-100 / K5-10-20
   Hold / research variant; no reproducible frequency advantage established.

3. CNN A / RTH2-100 / K5-10-20 / dilation=2
   Fail / hold as a calendar-receptive-field control.

4. RTH2-100 / K10-20-40
   Fail / hold; parameter count is larger and ranking is negative on average.

5. CNN B
   Fail / hold for ranking and top20 lift.
```

MAE remains secondary. The K10/20/40 model again illustrates that lower point error can coexist with poor ranking quality.

## Commands

Alpaca data is cached locally under `.cache/futureview/alpaca/` and is not committed to Git.

Required environment variables:

```bash
export APCA_API_KEY_ID='...'
export APCA_API_SECRET_KEY='...'
```

Run the canonical comparison:

```bash
futureview-strategy1-frequency-compare
```

The prior Massive implementation is retained only for reproducibility:

```bash
futureview-strategy1-frequency-compare-massive
```

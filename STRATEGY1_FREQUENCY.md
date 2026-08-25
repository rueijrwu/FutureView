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

## Input variants tested so far

```text
DAILY_50_K5_10_20
  50 daily observations
  kernels = 5 / 10 / 20
  params = 2764

RTH2_100_K5_10_20
  50 sessions x 2 regular-session observations = 100 observations
  kernels = 5 / 10 / 20
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

Cross-seed results:

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

## Current interpretation

The matched-feed multi-fold result does **not** establish a general higher-frequency advantage.

`RTH2_100_K5_10_20` has almost the same mean Spearman as the Daily baseline (`+0.072512` vs `+0.067405`), but slightly worse seed dispersion and lower top-20% Oracle lift. The direction is not stable across folds: RTH2 is better in Fold 1, while Daily is better in Folds 2 and 3.

Therefore the strong Massive one-fold result is best treated as regime-specific rather than evidence that doubling observation density generally improves prediction.

`RTH2_100_K10_20_40` remains fail/hold for ranking. Its larger kernels also increase parameter count from 2764 to 4164, so it is not a clean receptive-field control.

Current status:

```text
1. CNN A / Daily-50 / K5-10-20
   Primary validated baseline.

2. CNN A / RTH2-100 / K5-10-20
   Hold / research variant; no reproducible frequency advantage established.

3. RTH2-100 / K10-20-40
   Fail / hold.

4. CNN B
   Fail / hold for ranking and top20 lift.
```

## Next experiment: parameter-matched dilation control

The next experiment is predeclared before observing its results.

Add one new model condition:

```text
RTH2_100_K5_10_20_DILATION2
  input = same Alpaca IEX RTH2-100 tensor
  kernels = 5 / 10 / 20
  dilation = 2
  params = 2764 (must exactly match Daily Model A and RTH2 K5/10/20)
```

For a dilated convolution, effective temporal width is:

```text
effective_width = dilation * (kernel_size - 1) + 1
```

Therefore the three branches cover approximately:

```text
K5,  dilation 2 -> 9 intraday bars  ~= 4.5 sessions
K10, dilation 2 -> 19 intraday bars ~= 9.5 sessions
K20, dilation 2 -> 39 intraday bars ~= 19.5 sessions
```

This approximately restores the Daily model's 5/10/20-session calendar receptive fields without increasing the number of convolution weights.

Everything else remains frozen:

```text
same Alpaca IEX matched input feed
same common dates
same 50-session historical span
same RTH2-100 observations
same 30D RAW_ORACLE target
same Sliding-260 training
same 60-session purge
same 60-session OOS folds
same five seeds
same epochs / LR / Huber delta
same Model-A topology
```

The implementation contains a runtime parameter-count guard. The dilation-control run must abort if the dilated model does not have exactly the same parameter count as the Daily Model A baseline.

### Predeclared interpretation

```text
If DILATION2 > Daily and DILATION2 > raw RTH2 across folds/seeds:
  higher-frequency input may help when calendar receptive field is preserved.

If DILATION2 ~= raw RTH2 ~= Daily:
  extra observation density has no material benefit under the current setup.

If Daily > both RTH2 variants:
  daily compression is more appropriate for the current target/model.

If DILATION2 is strong only in one fold:
  treat as regime-specific, not a pass.
```

Primary evidence remains fold-wise Spearman, cross-seed stability, and top-20% realized Oracle Value lift. MAE remains secondary.

## Commands

Alpaca data is cached locally under `.cache/futureview/alpaca/` and is not committed to Git.

Required environment variables:

```bash
export APCA_API_KEY_ID='...'
export APCA_API_SECRET_KEY='...'
```

Run the canonical comparison, now including the dilation control:

```bash
futureview-strategy1-frequency-compare
```

The prior Massive implementation is retained only for reproducibility:

```bash
futureview-strategy1-frequency-compare-massive
```

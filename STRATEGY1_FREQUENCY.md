# Strategy 1 — Input Frequency Experiment

This document records the first controlled comparison of daily versus higher-frequency causal OHLCV inputs for Strategy 1 prediction. It is an experimental result only and does not modify the frozen Strategy 1 mechanics or Oracle definition in `STRATEGY1.md`.

## Research question

The question is deliberately narrow:

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

## First result: Massive limited-history run

Massive Basic history entitlement produced only enough common Daily/Intraday data for one limited-history OOS block.

Observed setup:

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

## Interpretation

The first frequency test is a **preliminary pass**, not a formal multi-regime pass.

Within this single 2026 OOS regime, `RTH2_100_K5_10_20` improves both ranking level and seed stability relative to the 50-daily-bar baseline:

```text
Spearman:     +0.708543 -> +0.864708
Spearman std:  0.273169 ->  0.013241
Top20 lift:   +0.013785 -> +0.016180
Lift std:      0.004493 ->  0.001167
```

The strongest signal is not only the higher mean Spearman; it is the large reduction in initialization sensitivity. All five intraday K5/10/20 seeds cluster tightly between approximately `0.844` and `0.884` Spearman.

This supports the hypothesis that higher-frequency input may expose short-horizon price/volume path structure that is compressed inside daily bars.

However, the evidence is regime-limited. The test contains only one 46-session OOS block, and prior work already showed that the 2026 regime is especially favorable for CNN A. Therefore the value `0.864708` must not be treated as an estimate of long-run expected Spearman.

`RTH2_100_K10_20_40` fails strongly. Its lower MAE does not rescue it because ranking and top-quantile separation are the primary objectives. This is another example of lower point-error coexisting with poor or inverted ranking.

The K10/20/40 comparison also changes parameter count (`4164` vs `2764`), so its failure should not be interpreted as a clean proof that calendar-matched receptive fields are intrinsically bad. The current actionable conclusion is simply to retain the original K5/10/20 Model-A topology for the next replication.

## Current model status

```text
1. CNN A / RTH2-100 / K5-10-20
   Strongest preliminary frequency result; one-regime evidence only.

2. CNN A / Daily-50 / K5-10-20
   Current formally validated multi-fold prediction baseline.

3. RTH2-100 / K10-20-40
   Fail / hold.

4. CNN B
   Fail / hold for ranking and top20 lift.
```

The intraday configuration does not replace the daily baseline until it survives the same multi-fold OOS evaluation.

## Data-provider decision: Alpaca IEX

Future frequency replication will use Alpaca Historical Market Data rather than Massive.

Reasons:

- Alpaca Basic is sufficient for the required multi-year SPY history.
- The experiment needs only one instrument, SPY.
- The historical bars API supports 30-minute bars.
- The free/basic equities feed is IEX; this is acceptable for the current frequency feasibility test.
- Historical intraday chunks are cached locally under `.cache/futureview/alpaca/` as compressed CSV and are not committed to Git.

Required environment variables:

```bash
export APCA_API_KEY_ID='...'
export APCA_API_SECRET_KEY='...'
```

Offline aggregation smoke:

```bash
futureview-alpaca-data-smoke
```

Canonical frequency comparison:

```bash
futureview-strategy1-frequency-compare-alpaca
```

The canonical Alpaca run should restore the original research standard:

```text
same common OOS dates across Daily and Intraday
Sliding-260
purge = 60
60-session test folds
five fixed seeds
30D RAW_ORACLE
CNN A
no random split
```

## Replication gate

The frequency hypothesis becomes materially stronger only if `RTH2_100_K5_10_20` preserves its advantage across multiple chronological OOS regimes.

The next decision rule is therefore qualitative but fixed in direction:

- compare Daily-50 and RTH2-100 on identical Alpaca-supported common dates;
- prioritize mean fold Spearman, positive-fold consistency, cross-seed stability, and top20 lift;
- do not tune architecture, thresholds, target, seeds, purge, or training history based on the Massive one-fold result;
- keep K5/10/20 fixed for the primary replication;
- retain MAE as secondary only.

Only after this multi-fold replication should intraday Model A be promoted above the daily Model A baseline for subsequent causal portfolio testing.

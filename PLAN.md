# FutureView Phase-1 Plan

Last updated: 2026-08-24

## 1. Phase-1 question

FutureView is currently a CPU-first feasibility study on SPY only.

The primary question is now:

> Can causal SPY price/volume structure predict the future Oracle Value of one fixed trading strategy over an approximately 3-week to 3-month horizon?

This replaces the earlier assumption that the CNN must first predict one universal geometric definition of trend.

The working framework is strategy-relative:

```text
fixed strategy S
+ future SPY path
+ complete future knowledge for label construction only
        -> OracleValue(S)

causal historical OHLCV
        -> CNN
        -> predicted OracleValue(S)
```

The Oracle baseline is deterministic once the strategy and future path are fixed. Statistical confidence belongs to the predictive model, not to the Oracle baseline.

See `STRATEGY_FRAMEWORK.md` for the conceptual framework and `DEFINITION.md` for literature-based trend/path descriptors.

---

## 2. Scope

Phase 1 is deliberately narrow:

- SPY only
- daily OHLCV first
- raw technical information only: Open, High, Low, Close, Volume
- CNN as the primary predictive model
- CPU first
- intended strategy horizon: roughly 15-60 trading sessions
- strict chronological / purged out-of-sample validation
- no fundamentals, news, macro, sentiment, options, breadth, or alternative data
- no QQQ, sectors, or individual equities until SPY feasibility is demonstrated

Later work may add 4-hour and 1-hour OHLCV as multi-resolution inputs, but not before the daily strategy-value pipeline is validated.

---

## 3. Why OHLCV is the model input

Most classical technical indicators are deterministic transformations or filters of price and volume.

The Phase-1 hypothesis is therefore that a CNN can learn useful time-scale and pattern transformations directly from causal OHLCV instead of requiring a large hand-designed indicator set.

This is an empirical hypothesis, not an assumption of success.

Later interpretability work may compare:

- raw OHLCV CNN
- explicitly interpretable multi-scale filters / moving averages
- hybrid models

but Phase 1 first asks whether the raw OHLCV -> strategy value mapping exists at all.

---

## 4. Confirmed SPY data pipeline

The current repository already has a working Yahoo Finance SPY daily pipeline.

Current smoke configuration:

```text
symbol: SPY
period: 3y
interval: 1d
auto_adjust: false
fields: date, open, high, low, close, volume
```

GitHub Actions has repeatedly confirmed live SPY retrieval and validation.

Confirmed result on 2026-08-24:

```text
rows = 751
start = 2023-08-25
end = 2026-08-24
duplicates = 0
missing = 0
```

The same data path successfully feeds causal feature generation, 50-session windows, chronological splits, and CPU training smoke tests.

Important: the current `period="3y"` dataset is suitable for debugging. Formal experiments should eventually use fixed absolute date ranges for reproducibility.

---

## 5. Existing model/pipeline status

Already implemented and smoke-tested:

- canonical SPY OHLCV loading and validation
- causal OHLCV-derived features
- 50-session input windows
- horizons 15 / 30 / 45 / 60
- Model A: joint OHLCV CNN
- Model B: separate price / volume CNN
- purged chronological smoke split
- CPU synthetic model smoke
- CPU real-data training smoke

The current old `trend_h` labels and loose/strict success labels are provisional pipeline-validation labels only. They are no longer treated as the final Phase-1 research target.

Do not use their current loss values to claim strategy predictability.

---

## 6. Strategy-relative Oracle baseline

For each timestamp `t` and fixed strategy `S`, define a future path over horizon `h`.

The Oracle Value is:

```text
OracleValue(S, future_path)
    = maximum final profit achievable
      with complete future knowledge
      while obeying every rule and resource constraint of S.
```

The Oracle may choose which legal candidate events to use, but it may not alter:

- capital weights
- allowed number of entries
- allowed number of exits
- event definitions
- exit rules
- horizon
- transaction-cost assumptions

If a candidate event is skipped, its allocation is effectively zero.

This keeps the baseline tied to a real fixed strategy instead of an unconstrained buy-the-low / sell-the-high hindsight number.

---

## 7. Strategy 1 — initial fixed prototype

Strategy 1 is intentionally simple. The goal is to create one unambiguous Oracle baseline before adding more technical rules.

### Direction

```text
long only
```

### Capital structure

```text
maximum entries: 3 total
initial entry + 2 add-ons
fixed capital allocation per entry
initial default: 1/3 + 1/3 + 1/3
```

The weights are part of the strategy and must not be optimized separately for each future path.

### First entry condition

Use daily close.

The first entry candidate occurs when price closes above all three moving averages:

```text
Close > MA5
Close > MA10
Close > MA20
```

and the moving averages are in bullish order:

```text
MA5 > MA10 > MA20
```

For a discrete new-entry event, require that the full condition was not already true on the previous trading session.

### Add-on 1 and Add-on 2

Initial simple rule:

```text
add on a new breakout high after the previous entry/add-on
```

This rule still requires one precise implementation choice before coding the Oracle: the exact definition of "prior high / breakout high" (for example rolling N-day high versus post-entry swing high).

Until that is frozen, do not add gap, volume-contraction, RSI, MACD, or other confirmation rules.

### Exit structure

Use staged exits based on daily close:

```text
Close < MA5  -> reduce current position by 50%
Close < MA10 -> exit all remaining position
```

The MA10 rule has precedence if both conditions first become true on the same session.

The exact re-entry/reset behavior after a full exit still needs to be frozen for Oracle implementation.

### Intended holding / evaluation horizon

```text
15-60 trading sessions
```

We should first compute Oracle Values separately for 15D / 30D / 45D / 60D rather than collapsing them into one weighted target.

---

## 8. Immediate implementation sequence

### Step 1 — freeze Strategy 1 semantics

Before coding, resolve only the remaining ambiguous rules:

1. exact breakout-high definition for the two add-ons
2. whether a 5-day partial exit can trigger only once per campaign or repeatedly
3. reset/re-entry behavior after a full MA10 exit
4. treatment of an open position at the horizon boundary
5. transaction cost / slippage assumption for the first prototype

Do not add additional indicators yet.

### Step 2 — implement Strategy 1 event engine

Create deterministic causal event calculations for:

- MA5 / MA10 / MA20
- first-entry event
- add-on candidate events
- MA5 partial-exit event
- MA10 full-exit event

The event engine itself must not use future information.

### Step 3 — implement Strategy 1 Oracle

For each future 15/30/45/60-day path:

- enumerate only legal Strategy-1 action sequences
- obey fixed entry/exit counts and weights
- select the legal sequence producing maximum final profit
- store Oracle Value and selected action sequence

The search should operate on strategy-defined candidate events rather than arbitrary timestamps whenever possible.

### Step 4 — Oracle smoke validation

Check hand-constructed paths:

- steady uptrend
- early dip then strong trend
- choppy oscillation
- sharp spike
- failed breakout
- trend followed by MA5 then MA10 breakdown

Verify that the Oracle never changes strategy parameters path by path.

### Step 5 — generate SPY Oracle labels

Using the already validated SPY daily dataset, generate:

```text
oracle_15
oracle_30
oracle_45
oracle_60
```

plus action metadata such as entry/add-on/exit dates and realized capital-weighted return.

### Step 6 — replace provisional trend target in a new experiment path

Do not delete the existing smoke labels immediately.

Add a strategy-value experiment path so the existing mechanical smoke tests remain available while the new target is validated.

### Step 7 — CNN feasibility test

Train Model A and Model B on causal OHLCV to predict Strategy-1 Oracle Value.

The first scientific question is not whether training loss decreases. It is whether out-of-sample predictions discriminate high-value from low-value future Strategy-1 opportunities.

---

## 9. Validation

Random splitting is forbidden.

Formal evaluation must use purged chronological walk-forward folds:

```text
past -> train
next block -> validation
purge future-label overlap
later block -> test
roll forward
```

For early CPU debugging, the current simple chronological split may remain as a smoke test only.

Formal results should use multiple seeds and identical test dates for Model A/B comparisons.

---

## 10. What model confidence means

Confidence is a property of the mapping:

```text
historical OHLCV -> future Strategy-1 Oracle Value
```

Candidate measurements later include:

- out-of-sample prediction error
- rank correlation between predicted and realized Oracle Value
- top-quantile realized Oracle Value
- probability that Oracle Value exceeds a practical threshold
- fold-to-fold stability
- seed / ensemble dispersion
- calibration

For multiple future strategies, strategy separation will also matter:

```text
predicted value of best strategy
minus
predicted value of alternatives
```

If all strategy models are weak or indistinguishable, `no trade` should remain a valid eventual decision.

No final confidence score is fixed yet.

---

## 11. Phase-1 success criterion

Phase 1 succeeds only if causal SPY OHLCV contains reproducible out-of-sample information about Strategy-1 future Oracle Value.

Useful evidence should include:

```text
higher predicted StrategyValue
-> higher realized OracleValue
```

with:

- meaningful separation across prediction buckets
- stable walk-forward folds
- enough samples / coverage
- reproducibility across seeds
- improvement beyond simple technical baselines

If this relation does not hold, do not expand to more securities merely to find a favorable example. First revisit the strategy definition, Oracle semantics, input representation, model, or history window.

---

## 12. Later phases — explicitly deferred

Only after Strategy 1 on SPY is understood:

1. define Strategy 2 / 3 / 4, each with its own Oracle baseline
2. compare which strategy values are most predictable from SPY OHLCV
3. investigate model interpretability and learned time scales
4. test explicit MA/filter branches versus raw OHLCV
5. add multi-resolution daily + 4H, then possibly 1H
6. compare SPY with QQQ / sector ETFs / individual equities
7. study security-specific strategy suitability
8. construct a strategy-selection and confidence layer

The long-term objective is not one universally best technical strategy. It is to estimate which fixed strategy is predictably compatible with the current price/volume structure of a given security.

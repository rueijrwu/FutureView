# FutureView Phase-1 Plan

Last updated: 2026-08-24

## 1. Phase-1 question

FutureView is currently a CPU-first feasibility study on SPY only.

The primary question is:

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

See `STRATEGY_FRAMEWORK.md` for the conceptual framework, `STRATEGY1.md` for the frozen first strategy, and `DEFINITION.md` for literature-based trend/path descriptors.

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

The repository already has a working Yahoo Finance SPY daily pipeline.

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

If no legal campaign is profitable, no trade is a valid Oracle choice:

```text
OracleValue = max(0, best legal campaign return)
```

This keeps the baseline tied to a real fixed strategy instead of an unconstrained buy-the-low / sell-the-high hindsight number.

---

## 7. Strategy 1 v0 — frozen prototype

Strategy 1 is intentionally simple. It is now frozen for the first Oracle feasibility test.

The canonical rule specification is maintained in `STRATEGY1.md`.

### Direction

```text
long only
```

### Capital structure

```text
maximum entries: 3 total
initial entry + 2 add-ons
fixed capital allocation: 1/3 + 1/3 + 1/3
maximum one campaign per future window
```

The weights and trade counts are part of the strategy and cannot be optimized separately for each future path.

### Entry 1

A new first-entry event occurs when the full bullish condition becomes true after not being true on the previous session:

```text
Close > MA5
Close > MA10
Close > MA20
MA5 > MA10 > MA20
```

All decisions use daily close.

### Add-on 1 and Add-on 2

Use a fixed breakout rule:

```text
Close > previous 20-session highest close
```

After Entry 1, the first eligible new breakout triggers Add-on 1. A later eligible new breakout triggers Add-on 2.

Each add-on contributes another fixed 1/3 capital allocation.

### Exit 1

```text
Close < MA5
-> sell 50% of the current position
```

This staged partial exit may occur only once within the campaign.

### Exit 2

```text
Close < MA10
-> sell all remaining position
-> campaign ends
```

If both MA5 and MA10 exit conditions are newly satisfied on the same session, the MA10 full exit takes precedence.

### Re-entry / cycle rule

After a full exit, the same future window does not start a second campaign.

### Horizon boundary

If a position remains open at the end of the 15D / 30D / 45D / 60D future window, all remaining shares are marked out / liquidated at the final close for Oracle-value calculation.

### Transaction cost assumption

Strategy 1 v0 uses zero transaction cost and zero slippage for the first mechanical feasibility pass.

Costs will be introduced only after the Oracle mechanics and label distribution are validated.

---

## 8. Oracle implementation status

The first Strategy-1 Oracle implementation now exists on `cnn-trend-reset`.

Implemented components:

- deterministic moving-average state calculation
- Entry-1 candidate event generation
- rolling-20D breakout add-on candidates
- MA5 partial exit
- MA10 full exit
- one-campaign simulation
- Oracle search over legal Entry-1 candidates inside each future window
- 15D / 30D / 45D / 60D Oracle Value calculation
- no-trade floor at zero
- Strategy-1 Oracle smoke command
- GitHub Actions step for Strategy-1 Oracle smoke

Important semantic rule:

> The Oracle may use future knowledge to choose which legal Entry-1 candidate starts the campaign, but after that choice it must follow the fixed Strategy-1 rules. It cannot invent arbitrary local minima/maxima, change weights, or alter exits path by path.

This is the key distinction between a strategy-constrained Oracle and unconstrained hindsight optimization.

---

## 9. Current implementation sequence

### Step 1 — freeze Strategy 1 semantics

Status: **completed for v0**.

The first prototype now has fixed:

- Entry 1
- two add-on rules
- capital weights
- MA5 partial exit
- MA10 full exit
- one campaign per window
- horizon-end liquidation
- zero-cost first-pass assumption

Do not add gap, volume-contraction, RSI, MACD, or other confirmation rules before evaluating this version.

### Step 2 — implement Strategy 1 event engine

Status: **implemented**.

The event engine is causal by construction. Future information is used only by the Oracle layer to choose among already-defined legal future candidate events.

### Step 3 — implement Strategy 1 Oracle

Status: **implemented first pass**.

For each future horizon, the Oracle evaluates legal Strategy-1 campaigns and keeps the maximum final capital return, including the no-trade option.

### Step 4 — Oracle smoke validation

Status: **CI smoke added; validation in progress**.

Required mechanical checks include:

- steady uptrend
- early dip then strong trend
- choppy oscillation
- sharp spike
- failed breakout
- trend followed by MA5 then MA10 breakdown
- no legal Entry-1 event
- no profitable legal campaign
- horizon boundary with an open position

The objective here is code correctness, not model-quality inference.

### Step 5 — inspect SPY Oracle label distribution

This is the **immediate next analytical step** after the smoke passes.

Before training any CNN on the new target, calculate for each horizon:

```text
15D
30D
45D
60D
```

at least:

```text
number of eligible prediction dates
fraction with OracleValue = 0
fraction with OracleValue > 0
mean OracleValue
median OracleValue
standard deviation
10th / 25th / 50th / 75th / 90th / 95th percentiles
maximum OracleValue
Entry-1 candidate count distribution
campaign length distribution
number of campaigns using 1 / 2 / 3 entries
partial-exit frequency
full-exit frequency
horizon-forced-exit frequency
```

This distribution must be understood before calling the Oracle Value a useful CNN target.

Questions to answer:

1. Does Strategy 1 generate enough non-zero opportunities?
2. Is the target dominated by zero/no-trade windows?
3. Are most gains concentrated in a tiny number of extreme windows?
4. Does the Oracle produce meaningful variation across 15/30/45/60D?
5. Does the strategy structurally favor one horizon?
6. Are add-ons and staged exits actually being used, or are they mostly irrelevant?

If the Oracle label distribution is pathological, revise Strategy 1 before training the CNN.

### Step 6 — validate Oracle sequences visually / manually

For selected SPY windows representing low, median, and high Oracle Value, inspect the selected action sequence:

```text
prediction date
Entry 1
Add-on 1
Add-on 2
MA5 partial exit
MA10 full exit / horizon liquidation
Oracle return
```

The purpose is to verify that the label corresponds to an intuitively valid Strategy-1 execution rather than a coding artifact.

### Step 7 — add Strategy-1 labels to the research dataset

Only after Steps 5-6 pass, create the formal target columns:

```text
oracle_s1_15
oracle_s1_30
oracle_s1_45
oracle_s1_60
```

plus action metadata for debugging and interpretation.

Keep the old trend labels available only as legacy smoke diagnostics until the new path is stable.

### Step 8 — CNN feasibility test

Train Model A and Model B on causal OHLCV to predict Strategy-1 Oracle Value.

The first question is not whether training loss decreases. It is whether out-of-sample predictions discriminate high-value from low-value future Strategy-1 opportunities.

---

## 10. CNN target and evaluation

For Strategy 1, the CNN target becomes horizon-specific Oracle Value:

```text
Past 50D causal OHLCV
        -> CNN
        -> predicted OracleValue_15
        -> predicted OracleValue_30
        -> predicted OracleValue_45
        -> predicted OracleValue_60
```

Do not collapse these into one manually weighted score in the first experiment.

Useful out-of-sample evaluation should include:

```text
MAE / Huber loss
Spearman rank correlation
Pearson correlation as a secondary diagnostic
realized Oracle Value by predicted-score quantile
Top 50% / 30% / 20% / 10% predicted groups
coverage / sample count
fold stability
seed stability
```

The central desired relationship is:

```text
higher predicted Strategy-1 value
-> higher realized Strategy-1 Oracle Value
```

Because the target is economic value rather than a geometric trend score, quantile/ranking discrimination is at least as important as raw regression error.

---

## 11. Validation

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

The same-date unconditional Oracle distribution on each test fold should be used as the reference population when evaluating model-selected subsets.

---

## 12. What model confidence means

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

## 13. Phase-1 success criterion

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

A weak result is still informative. If OHLCV cannot predict Strategy-1 Oracle Value, we should first ask whether:

- Strategy 1 creates a sensible target distribution
- the strategy is too rigid or too permissive
- the horizon is mismatched
- the CNN representation is inadequate
- the available history is insufficient

Do not expand to more securities merely to search for a favorable example.

---

## 14. Later strategy iteration

Only after Strategy 1 is fully characterized should we define Strategy 2 / 3 / 4.

Each new strategy should change explicit trading rules, not hidden weights inside a universal success formula.

Potential future strategy dimensions include:

- alternative first-entry condition
- alternative add-on event
- different fixed allocation schedule
- gap / breakout structure
- volume contraction / expansion confirmation
- alternative MA exit scales
- filtered local-extrema candidate events

For each strategy:

```text
fixed rules
-> independent Oracle baseline
-> independent CNN predictability test
```

Then compare both economic Oracle potential and predictive reliability.

---

## 15. Later interpretability work — deferred

If the raw OHLCV model shows useful predictability, investigate what temporal structures it relies on.

Possible comparisons:

- inspect first-layer convolution filters
- frequency/time-scale response analysis
- explicit MA5/10/20/50 channels
- fixed low-pass/filter bank front-end
- learned filter bank
- raw OHLCV versus interpretable-filter versus hybrid model

This may reveal whether a specific security/strategy combination is particularly sensitive to certain time scales or moving-average-like structures.

Interpretability is valuable for later strategy refinement, but it is not required to prove the first feasibility hypothesis.

---

## 16. Later phases — explicitly deferred

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

# Strategy 1 v0 — SPY Long Trend Prototype

This file freezes the first strategy used to build a strategy-relative Oracle baseline.

The purpose is feasibility testing, not claiming that this is an optimal trading strategy.

## 1. Scope

- Instrument: SPY
- Direction: long only
- Data frequency: daily
- Future horizons: 15, 30, 45, 60 trading sessions
- Maximum campaigns per future window: 1
- Maximum entries in that campaign: 3
- Entry capital weights: 1/3, 1/3, 1/3 of initial capital
- Entry/exit spacing: 3 trading sessions
- Transaction costs/slippage: 0 for v0 smoke testing
- Execution price: event-day close
- Remaining position at horizon end: forced close at final horizon-day close
- No-trade is always allowed and has Oracle Value 0

A full MA10 exit terminates the only allowed campaign. No second campaign may start inside the same Oracle horizon.

## 2. First entry event

A legal first-entry event occurs when all of the following are true on the current close:

```text
Close > MA5
Close > MA10
Close > MA20
MA5 > MA10 > MA20
```

and the complete condition was false on the previous trading session.

This makes the first entry a discrete transition event rather than a condition that remains continuously active for many days.

At the selected first-entry event, invest 1/3 of initial capital.

## 3. Add-on events

The second and third entries use a 20-session close breakout event.

Define:

```text
Prior20High[t] = max(Close[t-20], ..., Close[t-1])
AbovePrior20[t] = Close[t] > Prior20High[t]
```

A breakout event occurs when:

```text
AbovePrior20[t] = true
AbovePrior20[t-1] = false
```

After the first entry:

- first later eligible breakout event -> invest the second 1/3
- next later eligible breakout event -> invest the final 1/3
- no more entries after three total entries

Continuous new highs while the breakout state remains true do not consume repeated add-on entries. A new breakout event requires the breakout state to reset and become true again.

After an MA5 partial exit, add-ons are blocked for the next three trading sessions. If the partial exit occurs on session `t`, then add-ons are blocked on `t+1`, `t+2`, and `t+3`; add-on eligibility resumes on `t+4`.

## 4. Exit events and three-session spacing

All exit rules use daily close.

### Partial exit

A 5-day moving-average exit event occurs when price crosses from not-below MA5 to below MA5:

```text
Close[t] < MA5[t]
```

with the previous session not below MA5.

At the first eligible such event after entry:

```text
sell 50% of the current shares
```

Only one MA5 partial exit is allowed in the campaign.

### Full exit

A 10-day moving-average exit event occurs when price crosses from not-below MA10 to below MA10.

At the first eligible such event:

```text
sell all remaining shares
terminate the campaign
```

If MA5 and MA10 exit events occur on the same eligible session, the MA10 full exit has priority.

No add-on is performed on a session used for an exit event.

### Three-session spacing after entry/add-on

Any entry or add-on blocks MA5 and MA10 strategy exits for the next three trading sessions.

If an entry/add-on occurs on trading session `t`, then:

```text
t+1: MA5/MA10 strategy exit blocked
t+2: MA5/MA10 strategy exit blocked
t+3: MA5/MA10 strategy exit blocked
t+4: exit eligibility resumes
```

An MA5/MA10 crossover event that occurs inside the blocked interval is skipped rather than deferred. A later new eligible crossover event is required.

The mandatory horizon-end liquidation is exempt from this spacing rule because it is imposed by the label-window boundary rather than by a strategy exit signal.

### Three-session spacing after partial exit

An MA5 partial exit blocks add-ons for the next three trading sessions:

```text
t+1: no add-on
t+2: no add-on
t+3: no add-on
t+4: add-on eligibility resumes
```

The remaining shares continue to be held during this interval, and MA10 full-exit logic remains available subject to the entry/add-on-to-exit spacing above.

After an MA10 full exit, the campaign is finished and no re-entry is allowed inside the same Oracle horizon.

## 5. Oracle choice

For prediction date `t` and horizon `h`, the future window is:

```text
(t+1) ... (t+h)
```

The Oracle has complete knowledge of this future window only for label construction.

It may choose which legal first-entry event within that window starts the single Strategy 1 campaign.

Once a first-entry event is chosen, all subsequent add-ons, exits, and spacing rules are deterministic under the fixed rules above.

The Oracle may not alter:

- entry weights
- event definitions
- maximum three entries
- maximum one campaign
- three-session spacing
- exit rules
- execution prices
- horizon

The Oracle Value is:

```text
max(0, best final capital return among all legal first-entry candidates)
```

The zero option represents choosing not to trade.

## 6. Exposure-adjusted Oracle efficiency

Oracle Value remains the optimization criterion and learning target. Exposure-adjusted metrics are diagnostic measures for comparing how efficiently the selected Oracle campaign uses market exposure across different horizons.

All actions execute at the daily close. Exposure is therefore measured close-to-close: after actions at close `i`, the remaining position is the exposure carried into the interval ending at close `i+1`.

Define the position fraction relative to initial capital after close `i` as `w_i`. Entry weights add 1/3 each. An MA5 half exit halves the current exposure fraction. A full exit sets it to zero.

Capital-weighted exposure days are:

```text
ExposureDays = sum(w_i over close-to-close intervals with an open position)
```

For example, if a campaign carries 1/3 exposure for 3 intervals, 2/3 for 4 intervals, and full exposure for 5 intervals:

```text
ExposureDays = 3*(1/3) + 4*(2/3) + 5*1 = 8.6667
```

Holding days are the number of close-to-close intervals with any positive position, regardless of position size.

The exposure-adjusted Oracle efficiency is:

```text
OracleReturnPerExposureDay = OracleValue / ExposureDays
```

For no-trade cases, `ExposureDays`, `HoldingDays`, and `OracleReturnPerExposureDay` are all zero.

Important: the Oracle does **not** maximize `OracleReturnPerExposureDay`. It still selects the legal campaign with the highest Oracle Value. The efficiency metric is calculated only after that campaign has been selected.

## 7. Phase-1 learning target

For each prediction date, create:

```text
OracleValue15
OracleValue30
OracleValue45
OracleValue60
```

The next research question is whether causal OHLCV history can predict these values out of sample.

The old return/MAE/efficiency TrendScore remains only a legacy pipeline smoke target and is not the final Strategy 1 research label.

## 8. Explicit v0 simplifications

The following are deliberately excluded until the basic Oracle-value hypothesis is tested:

- volume-confirmation entry rules
- gaps
- local extrema filters
- intraday execution
- 4-hour / 1-hour inputs
- transaction costs and slippage
- variable spacing duration
- repeated campaigns inside one horizon
- variable entry weights
- strategy-specific stop losses beyond MA exits

Each future modification should be treated as a new strategy version so its effect can be measured rather than hidden inside the baseline.

## 9. Current research status

This section records experimental conclusions only. It does not change the frozen Strategy 1 mechanics above.

### 9.1 Oracle horizon statistics

On the current 3-year SPY sample, the mean Oracle Value increases with horizon because longer windows contain more opportunities to find and complete a legal Strategy 1 campaign:

```text
15D mean Oracle Value = 0.004218
30D mean Oracle Value = 0.009038
45D mean Oracle Value = 0.012736
60D mean Oracle Value = 0.015308
```

The corresponding positive/traded frequencies are approximately:

```text
15D = 47.5%
30D = 64.1%
45D = 75.0%
60D = 83.8%
```

This means the higher 60D Oracle Value should not be interpreted as higher daily capital efficiency.

### 9.2 Exposure efficiency reverses the horizon ordering

For traded Oracle campaigns only, mean return per capital-weighted exposure day is:

```text
15D = 0.002155  (0.2155% per exposure-day)
30D = 0.001785  (0.1785% per exposure-day)
45D = 0.001671  (0.1671% per exposure-day)
60D = 0.001620  (0.1620% per exposure-day)
```

Thus:

```text
Exposure efficiency: 15D > 30D > 45D > 60D
Opportunity frequency: 60D > 45D > 30D > 15D
```

The current interpretation is that longer horizons accumulate more total Oracle Value primarily because they provide more opportunity and more exposure time, not because each unit of market exposure is more productive.

### 9.3 Training-history comparison

Using CNN A with identical OOS dates, expanding history and recent sliding histories were compared.

A single seed initially suggested horizon-dependent preferences, but the subsequent five-seed stability test materially changed the conclusion.

The strongest reproducible configuration is currently:

```text
Target horizon = 30D
Training history = Sliding-260
Model = CNN A
Target = raw Oracle Value
```

Across five fixed seeds, the 30D Sliding-260 configuration produced:

```text
mean fold Spearman = 0.233705
Spearman std across seeds = 0.103928
positive mean-Spearman seeds = 5/5
mean top-20% Oracle lift = 0.004189
positive top-20% lift seeds = 5/5
```

The earlier apparent 60D advantage did not survive seed testing. 15D, 45D, and 60D are therefore not treated as having established reproducible predictive signal at this stage.

### 9.4 Raw Oracle Value remains the preferred learning target

A direct head-to-head comparison used the same 30D Sliding-260 setup, same CNN A architecture, same OOS folds, and same five seeds for two targets:

```text
RAW_ORACLE = OracleValue
EXPOSURE_EFFICIENCY = OracleValue / ExposureDays
```

Cross-seed results were:

```text
RAW_ORACLE:
  mean Spearman = 0.233705
  Spearman std = 0.103928
  positive Spearman seeds = 5/5
  raw Oracle top-20% lift = 0.004189
  positive raw-lift seeds = 5/5
  exposure-efficiency lift = 0.000192
  positive efficiency-lift seeds = 5/5

EXPOSURE_EFFICIENCY:
  mean Spearman = 0.059946
  Spearman std = 0.163474
  positive Spearman seeds = 3/5
  raw Oracle top-20% lift = 0.002534
  positive raw-lift seeds = 4/5
  exposure-efficiency lift = -0.000009
  positive efficiency-lift seeds = 3/5
```

Therefore raw Oracle Value remains the primary training target. Exposure-adjusted return is retained as a secondary economic-efficiency evaluation metric rather than replacing the learning target.

This conclusion is conditional on the current fixed optimization setup. The efficiency target is much smaller in scale, so the present experiment does not prove that exposure efficiency is intrinsically unpredictable; it only shows that it does not outperform raw Oracle Value under the frozen comparison.

### 9.5 Low-dimensional causal baseline

A fixed 20-dimensional causal summary ridge baseline was constructed from the same 50-session OHLCV input. For each of 5/10/20/50-session lookbacks it uses:

```text
close_sum
close_std
range_mean
abs_close_mean
volume_z_mean
```

The ridge uses training-fold-only standardization and fixed alpha = 0.01, with no OOS hyperparameter tuning.

For 30D Sliding-260 raw Oracle Value:

```text
CNN A cross-seed mean Spearman = 0.233705
CNN A cross-seed Spearman std = 0.103928
CNN A positive mean-Spearman seeds = 5/5
CNN A mean top-20% lift = 0.004189

Summary Ridge mean Spearman = 0.020159
Summary Ridge positive folds = 1/4
Summary Ridge mean top-20% lift = 0.004975
```

Fold-level Spearman comparison:

```text
Fold 1: CNN mean +0.202796 vs Ridge -0.041317
Fold 2: CNN mean +0.034425 vs Ridge -0.213299
Fold 3: CNN mean +0.035332 vs Ridge -0.169144
Fold 4: CNN mean +0.662265 vs Ridge +0.504396
```

The current conclusion is:

- CNN A passes the low-dimensional baseline gate for **ranking stability**.
- CNN A has not yet demonstrated a higher average top-quantile Oracle lift than Summary Ridge.
- The CNN signal therefore appears to contain ranking information beyond these simple momentum/volatility/range/volume summaries, but the economic advantage of that ranking is not yet established.

### 9.6 MAE is secondary

The current experiment continues to show poor CNN point calibration despite useful ranking behavior:

```text
Constant mean MAE = 0.009914
Summary Ridge mean MAE = 0.012723
CNN A cross-seed mean MAE = 0.114506
```

For this phase, primary evidence is therefore:

```text
fold-wise Spearman / rank correlation
cross-seed stability
top-quantile realized Oracle Value separation
exposure-adjusted economic efficiency
```

MAE is retained as a diagnostic but is not the primary model-selection criterion.

### 9.7 Current research conclusion

The strongest claim supported so far is:

> Past 50-session causal OHLCV contains reproducible OOS ranking information for future 30-session Strategy 1 Oracle Value under a Sliding-260 training policy. CNN A ranks the target materially better than a fixed low-dimensional causal summary ridge baseline, but a superior realized portfolio P&L has not yet been demonstrated.

The feasibility question is therefore not yet closed. The predictive-ranking gate has meaningful positive evidence, but the economic-value gate remains open.

### 9.8 Next gate: causal OOS portfolio backtest

The next experiment should stop evaluating only overlapping Oracle-label windows and convert the ranking signal into an actual causal trading decision process.

The planned fixed comparison is:

```text
1. Strategy 1 always-on
2. Summary-Ridge-filtered Strategy 1
3. CNN-filtered Strategy 1
4. Oracle-selection upper bound
```

The CNN path should use:

```text
30D raw Oracle Value
Sliding-260 training
CNN A
five-seed ensemble or another predeclared aggregation rule
```

A live-like entry threshold must be derived only from the training window, for example a training-prediction percentile. It must not use an OOS fold's future predictions to define a retrospective top-20% cutoff.

The backtest should report at least:

```text
cumulative return
annualized return / CAGR
maximum drawdown
number of campaigns
average campaign return
market exposure
return per exposure-day
```

Only this stage can answer whether the observed OOS ranking signal converts into superior realized portfolio economics.

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

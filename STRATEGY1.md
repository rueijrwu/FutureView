# Strategy 1 v0 — SPY Long Trend Prototype

This file freezes the first strategy used to build a strategy-relative Oracle baseline.

The purpose is feasibility testing, not claiming that this is an optimal trading strategy.

## 1. Scope

- Instrument: SPY
- Direction: long only
- Data frequency: daily
- Future horizons: 15, 30, 45, 60 trading sessions
- Maximum trade cycles per future window: 1
- Maximum entries per cycle: 3
- Entry capital weights: 1/3, 1/3, 1/3 of initial capital
- Transaction costs/slippage: 0 for v0 smoke testing
- Execution price: event-day close
- Remaining position at horizon end: forced close at final horizon-day close
- No-trade is always allowed and has Oracle Value 0

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

- first later breakout event -> invest the second 1/3
- next later breakout event -> invest the final 1/3
- no more entries after three total entries

Continuous new highs while the breakout state remains true do not consume repeated add-on entries. A new breakout event requires the breakout state to reset and become true again.

## 4. Exit events

All exit rules use daily close.

### Partial exit

A 5-day moving-average exit event occurs when price crosses from not-below MA5 to below MA5:

```text
Close[t] < MA5[t]
```

with the previous session not below MA5.

At the first such event after entry:

```text
sell 50% of the current shares
```

Only one MA5 partial exit is allowed in the cycle.

### Full exit

A 10-day moving-average exit event occurs when price crosses from not-below MA10 to below MA10.

At that event:

```text
sell all remaining shares
terminate the cycle
```

If MA5 and MA10 exit events occur on the same session, the MA10 full exit has priority.

No add-on is performed on a session used for an exit event.

After a full exit, no new cycle may start inside the same Oracle horizon in Strategy 1 v0.

## 5. Oracle choice

For prediction date `t` and horizon `h`, the future window is:

```text
(t+1) ... (t+h)
```

The Oracle has complete knowledge of this future window only for label construction.

It may choose which legal first-entry event within that window starts the single Strategy 1 cycle.

Once a first-entry event is chosen, all subsequent add-ons and exits are deterministic under the fixed rules above.

The Oracle may not alter:

- entry weights
- event definitions
- number of allowed entries
- exit rules
- execution prices
- horizon

The Oracle Value is:

```text
max(0, best final capital return among all legal first-entry candidates)
```

The zero option represents choosing not to trade.

## 6. Phase-1 learning target

For each prediction date, create:

```text
OracleValue15
OracleValue30
OracleValue45
OracleValue60
```

The next research question is whether causal OHLCV history can predict these values out of sample.

The old return/MAE/efficiency TrendScore remains only a legacy pipeline smoke target and is not the final Strategy 1 research label.

## 7. Explicit v0 simplifications

The following are deliberately excluded until the basic Oracle-value hypothesis is tested:

- volume-confirmation entry rules
- gaps
- local extrema filters
- intraday execution
- 4-hour / 1-hour inputs
- transaction costs and slippage
- minimum spacing between entries beyond the discrete breakout-event rule
- repeated trade cycles inside one horizon
- variable entry weights
- strategy-specific stop losses beyond MA exits

Each future modification should be treated as a new strategy version so its effect can be measured rather than hidden inside the baseline.

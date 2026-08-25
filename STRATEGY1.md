# Strategy 1 v0 — SPY Long Trend Prototype

This file freezes the first strategy used to build a strategy-relative Oracle baseline.

The purpose is feasibility testing, not claiming that this is an optimal trading strategy.

## 1. Scope

- Instrument: SPY
- Direction: long only
- Data frequency: daily
- Future horizons: 15, 30, 45, 60 trading sessions
- Maximum entries per campaign: 3
- Entry capital weights: 1/3, 1/3, 1/3 of capital available at the start of that campaign
- Post-exit cooldown: 3 trading sessions
- Transaction costs/slippage: 0 for v0 smoke testing
- Execution price: event-day close
- Remaining position at horizon end: forced close at final horizon-day close
- No-trade is always allowed and has Oracle Value 0

A future window may contain more than one campaign. A new campaign is allowed only after a full exit, the three-session cooldown has expired, and a new legal Entry-1 event occurs.

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

At a campaign's first-entry event, invest 1/3 of the capital available at the start of that campaign.

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

After the first entry in a campaign:

- first later eligible breakout event -> invest the second 1/3
- next later eligible breakout event -> invest the final 1/3
- no more entries after three total entries in that campaign

Continuous new highs while the breakout state remains true do not consume repeated add-on entries. A new breakout event requires the breakout state to reset and become true again.

An add-on event that occurs during a post-exit cooldown is not eligible and is skipped.

## 4. Exit events and cooldown

All exit rules use daily close.

### Partial exit

A 5-day moving-average exit event occurs when price crosses from not-below MA5 to below MA5:

```text
Close[t] < MA5[t]
```

with the previous session not below MA5.

At the first such event after entry in a campaign:

```text
sell 50% of the current shares
```

Only one MA5 partial exit is allowed per campaign.

### Full exit

A 10-day moving-average exit event occurs when price crosses from not-below MA10 to below MA10.

At that event:

```text
sell all remaining shares
end the current campaign
```

If MA5 and MA10 exit events occur on the same session, the MA10 full exit has priority.

No add-on is performed on a session used for an exit event.

### Three-session post-exit cooldown

Any MA5 partial exit or MA10 full exit starts a cooldown covering the next three trading sessions.

If an exit occurs on trading session `t`, then:

```text
t+1: no entry / no add-on
t+2: no entry / no add-on
t+3: no entry / no add-on
t+4: entry/add-on eligibility resumes
```

During a cooldown after a partial exit, the remaining shares continue to be held and normal exit rules remain active; only new entry/add-on actions are blocked.

After a full exit, the strategy remains flat through the cooldown. Beginning on the fourth trading session after that exit, the first new legal Entry-1 transition event may start a new campaign. A legal Entry-1 event that occurs inside the cooldown is skipped rather than deferred.

Each new campaign resets its own three-entry allowance and its one-time MA5 partial-exit allowance. Its 1/3 + 1/3 + 1/3 allocation is measured against capital available when that campaign begins.

## 5. Oracle choice

For prediction date `t` and horizon `h`, the future window is:

```text
(t+1) ... (t+h)
```

The Oracle has complete knowledge of this future window only for label construction.

It may choose which legal first-entry event within that window starts the first Strategy 1 campaign.

Once that first-entry event is chosen, all subsequent add-ons, exits, cooldowns, and later eligible re-entry campaigns are deterministic under the fixed rules above.

The Oracle may not alter:

- entry weights
- event definitions
- number of allowed entries per campaign
- cooldown length
- exit rules
- execution prices
- horizon

The Oracle Value is:

```text
max(0, best final capital return among all legal first-campaign start candidates)
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
- variable cooldown duration
- variable entry weights
- strategy-specific stop losses beyond MA exits

Each future modification should be treated as a new strategy version so its effect can be measured rather than hidden inside the baseline.

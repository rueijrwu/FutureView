# FutureView Strategy-Relative Oracle Framework

This document records the current research conclusion reached during strategy-definition discussion. It is intentionally separate from `DEFINITION.md`, which remains a literature-oriented library of candidate trend measures.

The key shift is that FutureView should not begin by imposing one universal geometric definition of `trend`. Instead, it should ask whether price/volume structure can predict the future value of a **fixed trading strategy**.

---

## 1. Core research idea

For a fixed strategy `S`, define the future path over horizon `h` as `P_(t:t+h)`.

The strategy has fixed rules and constraints, for example:

- allowed number of entries
- allowed number of exits
- fixed entry/add-on weights
- fixed exit weights
- long-only or long/short constraint
- transaction-cost assumptions
- timing / spacing constraints if applicable
- candidate event definitions if applicable

Given complete knowledge of the future path, the **Oracle Value** of that strategy is:

```text
OracleValue(S, P_(t:t+h))
    = maximum profit achievable over that future path
      while obeying every rule of strategy S.
```

This is a deterministic optimization result, not an expectation and not a probability.

The Oracle is not allowed to violate the strategy. It may use future knowledge only to choose the best legal sequence of actions under the strategy.

---

## 2. Baseline becomes strategy-relative

There is no longer one universal baseline.

For strategies `S1, S2, S3, ...`:

```text
Baseline_1(t,h) = OracleValue(S1, future_path)
Baseline_2(t,h) = OracleValue(S2, future_path)
Baseline_3(t,h) = OracleValue(S3, future_path)
...
```

Each strategy therefore produces its own ground-truth future value.

A different stock or ETF may also have a different distribution of Oracle Values for the same strategy. That is not a problem; it is part of the research question.

---

## 3. Two core hypotheses

### Hypothesis A — Price/volume structure predicts strategy value

Given only information available at time `t`, especially causal price and volume history:

```text
X_t = causal OHLCV history
```

can a model learn:

```text
X_t -> OracleValue(S, future_path)
```

for a fixed strategy `S`?

This is the primary technical-analysis question.

It does not ask whether the model predicts the exact future price path. It asks whether current price/volume structure contains information about whether a particular strategy will have a valuable future opportunity.

### Hypothesis B — Different securities favor different strategies

Different stocks and ETFs may possess different price/volume structures and therefore different strategy suitability.

Conceptually:

```text
security / market structure
        -> strategy-specific predictability
        -> strategy selection
```

The long-term goal is therefore not to discover one universally best strategy, but to estimate which fixed strategy is most compatible with the current market structure of a particular security.

---

## 4. The model predicts strategy value, not an abstract trend score

For strategy `S_k`, a dedicated model can estimate:

```text
PredictedOracleValue_k = f_k(current OHLCV history)
```

Possible future architecture:

```text
OHLCV history
   |
   +--> Model S1 --> predicted future value of strategy S1
   +--> Model S2 --> predicted future value of strategy S2
   +--> Model S3 --> predicted future value of strategy S3
   +--> Model S4 --> predicted future value of strategy S4
```

These models do not need to share one arbitrary weighted trend definition.

The thing we are allowed to change is the **strategy**, not a hidden subjective weighting formula used to manufacture a target.

---

## 5. Confidence belongs to the predictive model, not to the Oracle baseline

The Oracle baseline is deterministic once the strategy and future path are known.

Therefore the baseline itself does not have statistical confidence.

Confidence becomes meaningful only when we ask:

```text
How reliably can today's OHLCV predict this strategy's future Oracle Value?
```

Possible confidence concepts to investigate later include:

- out-of-sample prediction error
- calibration of predicted value ranges
- dispersion across seeds / ensembles
- fold-to-fold stability
- probability that realized strategy value exceeds a useful threshold
- ranking stability between competing strategies
- separation between the best predicted strategy and alternatives

No final confidence formula is selected yet.

A low-confidence state may mean:

```text
No available strategy is reliably favored by the current OHLCV structure.
```

In that case, `do not trade` can eventually be treated as a valid decision.

---

## 6. Oracle search should obey fixed resource constraints

Trading opportunities are not free resources.

If a strategy permits only a fixed number of entries/exits, using one opportunity consumes part of the strategy's finite action budget.

For example, if the strategy permits three entries total, the Oracle must choose which candidate opportunities are worth consuming those entries on.

It must not greedily trade every local fluctuation.

The optimization question is therefore:

```text
Among all legal trade sequences under this fixed action budget,
which sequence produces the maximum final strategy profit?
```

This naturally handles the concern that an Oracle could otherwise waste all trade opportunities on short-lived noise before a larger move occurs.

---

## 7. Candidate-event reduction: local minima/maxima and technical events

A brute-force Oracle that considers every possible action on every day may be unnecessarily expensive and may exploit unrealistically precise high-frequency fluctuations.

A practical reduction is to generate a finite set of candidate events first.

Candidate events may include:

- local minima
- local maxima
- moving-average breakout / breakdown
- prior-high breakout
- prior-low breakdown
- other strategy-defined technical events

These are **candidate action points**, not mandatory trades.

A zero allocation / zero weight means the Oracle skips that event.

This turns the optimization problem into selecting or weighting a much smaller number of meaningful events rather than searching every possible timestamp.

Important: the definition of candidate events must be part of the strategy specification and must be fixed before evaluating the Oracle.

---

## 8. Weights and number of actions should be fixed inside a strategy

Current conclusion:

- entry weights should not be optimized separately for every future path
- exit weights should not be optimized separately for every future path
- allowed trade counts should not change path by path

Otherwise the Oracle would quietly change the strategy itself.

Instead, define several separate strategies if we want to test several allocations.

Example:

```text
Strategy A:
3 entries with fixed weights [w1, w2, w3]
2 staged exits with fixed rules

Strategy B:
2 entries with different fixed weights
1 full exit

Strategy C:
1 entry / 1 exit
```

Each one gets its own Oracle baseline and its own predictability study.

---

## 9. Why raw lowest-price / highest-price profit is not enough

Simply buying the absolute future minimum and selling the absolute future maximum is usually too unconstrained.

It can exploit:

- one-day spikes
- one-day crashes
- extremely narrow timing windows
- high-frequency noise that a real strategy was never designed to capture

That number describes hindsight opportunity, but not necessarily the value of the actual strategy being studied.

The correct Oracle must therefore maximize profit **subject to the strategy's own timing, action-count, event, and allocation constraints**.

---

## 10. Relation to the earlier concept of trend

The working interpretation is now:

```text
A "useful trend" is strategy-relative.
```

Instead of first declaring that a path is a trend because it has a certain slope, R^2, efficiency, MAE, or curvature, we ask:

```text
Did this future path contain exploitable structure for strategy S?
```

The Oracle Value quantifies how valuable that structure was under strategy `S`.

Classical trend descriptors such as slope, R^2, efficiency, curvature, MAE, MFE, and filtered-price structure remain useful for analysis and interpretation, but they do not need to be the primary training target.

They may later help explain **why** a strategy's Oracle Value was high or low.

---

## 11. Current FutureView research pipeline concept

For each timestamp `t`:

```text
1. Observe causal historical OHLCV X_t.

2. Look forward only for label construction.

3. For each fixed strategy S_k:
       compute OracleValue_k(t, h)
       under complete future knowledge
       while strictly respecting S_k.

4. Train a separate predictive model:
       X_t -> OracleValue_k

5. Evaluate strictly out of sample:
       prediction accuracy
       ranking / calibration
       realized strategy performance
       confidence / stability

6. Compare strategies:
       Which strategy is most predictable and valuable
       for this market structure?
```

Future expansion can compare the same strategy set across SPY, QQQ, sectors, and individual equities.

---

## 12. What is NOT decided yet

The following remain open research questions:

- exact first strategy specification
- exact number of strategies, likely around 3–4 initially
- exact entry weights
- exact exit weights
- exact number of entries/exits per strategy
- exact candidate-event detector
- whether to use local extrema directly or filtered extrema
- whether a low-pass filter should define the strategy's effective time scale
- minimum spacing between candidate actions
- transaction-cost assumptions
- Oracle horizon(s)
- Oracle objective: raw return, log growth, capital-weighted return, etc.
- normalization needed to compare Oracle Values across securities
- final statistical definition of model confidence
- strategy-selection rule when several models are similar

These should be fixed one by one before formal training.

---

## 13. Immediate next research step

Do **not** modify the CNN target yet.

First specify one strategy completely and without ambiguity.

A strategy specification should answer at minimum:

```text
1. What constitutes an entry candidate?
2. How many entries are allowed?
3. What fixed capital weight is used at each entry?
4. What constitutes an add-on candidate?
5. What constitutes a partial exit?
6. What constitutes a full exit?
7. How many exits are allowed?
8. Are minimum time gaps required between actions?
9. What transaction costs/slippage are assumed?
10. What horizon ends the Oracle optimization?
11. What happens to remaining positions at the horizon boundary?
12. What exact objective is maximized?
```

Only after Strategy 1 is frozen should we implement its Oracle baseline.

---

## 14. Current concise research statement

> FutureView studies whether causal price/volume structure can predict the future maximum attainable value of a fixed trading strategy, where that value is computed by a strategy-constrained Oracle with complete future knowledge. Multiple fixed strategies produce multiple independent baselines. The eventual goal is to determine which strategy is both valuable and predictably compatible with the current price/volume structure of a given security.

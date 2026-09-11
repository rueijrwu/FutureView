# FutureView — Current Research Handoff

Last rewritten: 2026-09-11
Branch: `layer2-price-distribution-v1`

This handoff marks a major research pivot. The previous TSLA daily Strategy-1 / Layer1 C-Q-U / Layer2 line is **frozen as historical work**. It is not the active research direction unless explicitly revived.

Do not silently carry old TSLA assumptions, Layer1 labels, W30 definitions, memory rules, target definitions, or model architecture into the new intraday-futures project.

---

# 0. New research direction

The new target is **intraday futures trading**, with the primary candidates:

```text
1. MES — Micro E-mini S&P 500 futures
2. Taiwan Index Futures / Mini Taiwan Index Futures
```

The intended trading style is:

```text
intraday swing / day trading
technical-analysis driven
flat by session end unless explicitly redefined
```

The first implementation target should preferably be **MES**, because it provides a clean first market for building and testing the framework. Taiwan index futures can be studied as a separate market later. Do not mix the two datasets or assume identical session/microstructure behavior.

This is a **new strategy family**, not a parameter change to the TSLA Strategy-1 system.

---

# 1. Research philosophy to preserve

The useful principle from the earlier FutureView work remains:

```text
first define the opportunity/outcome space
then verify statistical structure
then train a model only if the structure exists
```

Do not begin with a CNN, Transformer, classification target, or large indicator set.

The new minimal research question is:

> Given only information available up to intraday time t, does a clearly defined technical setup correspond to a meaningfully different distribution of future intraday opportunity?

The model comes later.

---

# 2. Initial market/data scope

Working starting point:

```text
Instrument: MES
Bar frequency: 1 minute
Primary session: RTH first
Position policy: intraday flat
Input family: price + volume first
```

Potential later aggregation:

```text
3-minute
5-minute
```

Do not add order book, options flow, macro data, sentiment, or external alternative data in the first phase.

RTH vs overnight must be treated as separate regimes unless an explicit experiment proves they should be combined.

For Taiwan index futures, the session structure must be defined separately before reuse of the MES framework.

---

# 3. Technical-analysis role

The project remains primarily technical-analysis based.

However, technical indicators should initially be used mainly to define **candidate setups / events**, not indiscriminately injected as model features.

Candidate setup families may include, but are not yet approved as formal strategy rules:

```text
VWAP relation / reclaim / rejection
opening-range breakout or failure
short/medium momentum alignment
volume expansion
pullback and continuation
breakout / failed breakout
local intraday trend reversal
```

The first task is to choose a small, interpretable setup definition and test it statistically.

Do not introduce a large indicator library before the base event definition is validated.

---

# 4. New outcome-space concept

A plain future close-to-close return is likely insufficient for intraday trading.

For an observation / candidate entry at time `t` and horizon `h`, define at minimum:

```text
R_h   = return from t to t+h
MFE_h = maximum favorable excursion within (t, t+h]
MAE_h = maximum adverse excursion within (t, t+h]
```

For a long-side normalized formulation:

```text
R_h   = P[t+h] / P[t] - 1
MFE_h = max(P[t+1:t+h] / P[t] - 1)
MAE_h = min(P[t+1:t+h] / P[t] - 1)
```

Equivalent tick/point or volatility-normalized forms may later be compared.

Why this matters:

A setup can create a highly tradable move during the horizon even if the final `R_h` is small. MFE/MAE preserve information about the actual intraday trading opportunity and path risk.

Initial candidate horizons:

```text
5 min
15 min
30 min
60 min
120 min
```

These are experiment candidates, not yet locked values.

---

# 5. Proposed first statistical question

Before training any model, answer a very small question such as:

> After technical setup X occurs in MES RTH, is the future 30/60/120-minute MFE/MAE distribution materially different from an appropriate baseline?

For each setup, inspect at least:

```text
sample count
MFE distribution
MAE distribution
R_h distribution
MFE/MAE ratio or tradeoff
conditional hit rates for practical move thresholds
session-time dependence
stability across chronological periods
```

The goal is not initially to maximize strategy PnL. The goal is to establish whether a repeatable conditional opportunity distribution exists.

---

# 6. Causality / leakage rule

All candidate-entry/setup definitions must use only information available at or before time `t`.

Future bars may be used only to construct outcomes/labels such as MFE, MAE, and future return.

Explicitly separate:

```text
causal setup/input definition
vs
retrospective outcome measurement
```

Do not repeat the earlier mistake of silently modifying research semantics under the label of "causal correction". Any purge, embargo, overlap handling, session boundary, target maturity rule, or event de-duplication rule must be explicitly discussed and recorded before becoming baseline behavior.

---

# 7. Pre-training implementation policy

Before actual model training:

```text
use NumPy / Pandas / SciPy / Numba as appropriate
avoid PyTorch dependency
keep event construction and statistical audits lightweight
```

PyTorch or another ML framework should be introduced only after a statistically meaningful setup/outcome relation is demonstrated.

Where performance matters, prefer vectorized NumPy or Numba over Python loops.

---

# 8. Model direction — intentionally undecided

No model architecture is currently approved.

Potential later model input may be raw or normalized intraday price/volume history rather than hand-engineered technical indicators, but this is not yet locked.

Possible future prediction target:

```text
P(MFE_h, MAE_h, R_h | past intraday price/volume, setup context)
```

Possible outputs could include:

```text
quantiles of MFE / MAE
probability of reaching a move threshold before a stop threshold
expected excursion
rank score for opportunity quality
```

Do not assume the prior daily Layer2 quantile + BCE architecture should be reused.

---

# 9. What is frozen from the previous project

The following belong to the previous TSLA daily research line and are **not active definitions for the new project**:

```text
TSLA as target instrument
daily bars
Strategy-1 MA5/MA10/MA20 Entry
5D/10D retrospective extrema path construction
60D campaign horizon
W30 complete-path Layer1 windows
U / B / C / Q labels
H / N / L Layer1 states
90D daily normalized P/V input
30D Layer2 training lookback
15D retrain cadence
legacy memory=150
old Layer2 CNN / quantile / BCE experiments
```

These results should be preserved for historical reference, not deleted.

Most recent verified old-line observation before pivot:

```text
W30 complete-path TSLA audit
run 33936283146
commit dc69088f0c3c15c977a7fa5ba2345b2834d6db8c
```

Its C/Q/U findings remain valid only for that old definition.

---

# 10. Immediate next discussion

Do **not** start model training yet.

The next research discussion should define one minimal legal intraday setup for MES.

Decisions needed, in order:

1. Exact market/session: MES RTH first?
2. Exact bar representation: 1-minute baseline?
3. Long only first, or symmetric long/short?
4. What constitutes one legal candidate entry event?
5. How to prevent near-duplicate events during the same local move?
6. Which first horizons to evaluate: e.g. 30/60/120 min?
7. Outcome units: raw return, points/ticks, or volatility-normalized excursion?
8. What baseline distribution should the setup be compared against?

Only after these are locked should data acquisition and the first statistical audit be implemented.

---

# 11. Recommended first experiment

A reasonable first candidate, pending explicit approval, is:

```text
Market: MES
Session: RTH only
Bars: 1 minute
Direction: long-only first for simplicity
Setup family: one simple VWAP / opening-range / momentum event
Outcomes: MFE, MAE, R_h
Horizons: 30, 60, 120 minutes
Model: none
Evaluation: conditional-distribution separation + chronological stability
```

This is only a proposed starting experiment. The exact setup definition must be discussed before implementation.

---

# 12. Handoff rule

The next agent/session should treat this document as a **research reset**.

Do not continue the old TSLA Layer2 implementation by default.

The first objective is now:

```text
define a causal intraday technical setup
-> measure its future MFE/MAE/return distribution
-> verify whether useful structure exists
-> only then design the predictive model
```

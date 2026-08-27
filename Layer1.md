# Strategy 1 Layer-1 State Model

## Objective

The first predictive question is deliberately narrow:

> Using only price-volume information available now, can the model distinguish a favorable Strategy state, a neutral state, and an unfavorable Strategy state?

The fixed Strategy is not changed or optimized.

## Outcome quantities

For each retrospective evaluation window W of 30 trading sessions,

\[
U_W=\max_{e\in I_W}E(e)
\]

is the best realized outcome among all legal Entries in W under the fixed deterministic Strategy.

The periodic baseline is \(B_{p,W}\). The current excess-opportunity quantity is

\[
\boxed{C_W=U_W-B_{p,W}}.
\]

For a later Entry-level model, the normalized distance to the upper bound is

\[
\boxed{Q=\frac{U-P_E}{C}},
\]

where \(P_E\) is the realized deterministic Strategy profit for that legal Entry. Q is not a Layer-1 target yet.

## Layer-1 labels

Thresholds are local percentile thresholds, never hard-coded return percentages.

The current reference length is locked to

\[
R=60\text{ trading sessions}=2W.
\]

For every target time t, construct a causal local reference set from historical Strategy-window outcomes whose complete outcome dependency is already observable before t. Within the preceding 60 trading sessions, compute

\[
C_{40}(t),C_{60}(t),U_{40}(t),U_{60}(t).
\]

Then define

\[
y_t=+1\quad\text{if}\quad C_t>C_{60}(t)\ \land\ U_t>U_{60}(t),
\]

\[
y_t=-1\quad\text{if}\quad C_t<C_{40}(t)\ \land\ U_t<U_{40}(t),
\]

and

\[
y_t=0\quad\text{otherwise}.
\]

Thus the classes are:

- +1: favorable / high-opportunity state;
- 0: neutral or mixed state;
- -1: unfavorable / low-opportunity state.

The 40/60 percentiles deliberately make the neutral region narrower than the previous 25/75 definition.

The reference thresholds are recomputed causally at each target time from the rolling 60-session historical reference set. Future outcomes are never used to define the current threshold.

## Locked price-volume input

Only the previously agreed causal normalization is used. For N in {5,10,20,60},

\[
price_N(t)=\frac{P_t}{\sum_{i=1}^{N}P_{t-i}},
\]

\[
volume_N(t)=\frac{V_t}{\sum_{i=1}^{N}V_{t-i}}.
\]

Each day has eight channels:

```text
price_5, price_10, price_20, price_60,
volume_5, volume_10, volume_20, volume_60
```

The model input is the most recent 60 trading sessions:

\[
X_t\in\mathbb R^{8\times60}.
\]

No future rows, technical indicators, U, C, Q, baseline values, or other label-derived quantities are inputs.

## Time alignment

For a prediction made after session t closes, the input ends at t.

The corresponding W=30 label window begins on the next session:

\[
W_t=[t+1,t+30].
\]

Therefore the 60-row input is entirely earlier than the outcome window.

A historical U label can depend on a Strategy path beginning near the end of W and continuing for the fixed 60-session Strategy horizon. A historical outcome can enter the rolling reference set only after that complete dependency is observable. This rule keeps the rolling percentile labels causal.

## Current execution order

1. audit the 60-day rolling 40/60 state definition and its chronological class distribution;
2. if all three states remain sufficiently represented, use the locked 8 x 60 price-volume input to test whether those states are learnable;
3. start with a simple baseline classifier before increasing model capacity;
4. only after Layer 1 is established, proceed to the later C/Q estimation layer.

## Evaluation

Accuracy alone is not sufficient. Report at least:

- class counts and rates;
- chronological class stability;
- balanced accuracy;
- macro F1;
- per-class precision and recall;
- confusion matrix;
- high-state probability ranking diagnostics.

Because stride-1 W=30 windows overlap strongly, rows are not independent trials. Metrics describe chronological discrimination on the historical sequence, not an independent-sample probability estimate.

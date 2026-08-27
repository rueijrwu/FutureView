# Strategy 1 Layer-1 State Model

## Objective

The first predictive question is deliberately narrow:

> Using only price-volume information available now, can the model distinguish a rare favorable Strategy state, a neutral state, and a rare unfavorable Strategy state?

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

Thresholds are percentile based, never hard-coded return percentages.

For the training split only, estimate

\[
C_{25},C_{75},U_{25},U_{75}.
\]

Then define the three states

\[
y=+1\quad\text{if}\quad C>C_{75}\ \land\ U>U_{75},
\]

\[
y=-1\quad\text{if}\quad C<C_{25}\ \land\ U<U_{25},
\]

and

\[
y=0\quad\text{otherwise}.
\]

Thus the classes are:

- +1: rare favorable / high-opportunity state;
- 0: neutral or mixed state;
- -1: rare unfavorable / low-opportunity state.

Validation and test labels use the training thresholds unchanged. Percentiles are never recomputed on validation/test data.

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

Therefore the 60-row input is entirely earlier than the outcome window. This prevents the model from seeing price-volume rows that are part of the retrospective target window.

The historical U label can depend on a Strategy path that starts near the end of W and continues for the fixed 60-session Strategy horizon. Chronological partitions therefore purge observations whose target dependency can cross into the next partition.

## First test model

The first experiment is intentionally a baseline classifier, not the final CNN.

- flatten the locked 8 x 60 input;
- train a multinomial logistic classifier with class balancing;
- preserve chronology;
- fit all percentile thresholds and model parameters on the training set only;
- use validation and test only as forward held-out data.

This answers the smallest question: whether the locked normalized price-volume representation contains any forward information about the three Layer-1 states before adding CNN capacity.

## Evaluation

Accuracy alone is not sufficient because neutral states are expected to dominate. Report at least:

- class counts;
- balanced accuracy;
- macro F1;
- per-class precision and recall;
- confusion matrix;
- high-state probability ranking diagnostics.

Because stride-1 W=30 windows overlap strongly, rows are not independent trials. Metrics describe chronological discrimination on the historical sequence, not an independent-sample probability estimate.

## Decision after Layer 1

If the baseline shows no chronological separation beyond trivial baselines, do not proceed to Q prediction yet.

If the high/neutral/low states show reproducible forward separation, keep the same labels and input definition and then test a small 1-D CNN as the next representation model. The later second layer will estimate C and Q inside informative states; it is not part of this first experiment.

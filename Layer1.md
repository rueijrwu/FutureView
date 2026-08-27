# Strategy 1 — Deterministic Gate

## Purpose

Layer 1 is **not a learned classifier**.

Its role is to use already-observed historical Strategy statistics to decide whether a historical/current context should be passed to the probabilistic C/Q model.

The fixed Strategy is never changed or optimized.

The conceptual separation is:

\[
\boxed{\text{known past statistics} \rightarrow \text{deterministic gate}}
\]

followed by

\[
\boxed{\text{gate-passed price-volume context} \rightarrow \text{model future }p(C,Q\mid X,G)}.
\]

The model must not spend capacity relearning a state that can already be computed from completed historical data.

## Known historical quantities

For a retrospective evaluation window \(W\),

\[
U_W=\max_{e\in I_W}E(e),
\]

where every legal Entry \(e\) follows exactly one deterministic fixed-Strategy path.

The periodic baseline is \(B_{p,W}\), and

\[
\boxed{C_W=U_W-B_{p,W}}.
\]

For legal Entry \(e\), with realized fixed-Strategy outcome \(P_E=E(e)\),

\[
\boxed{Q_e=\frac{U_W-P_E}{C_W}}.
\]

These are retrospective outcome quantities. Once their complete Strategy dependencies have finished historically, they are known data and may be used to characterize the historical environment. They are not model inputs for predicting their own future realization.

## Local historical state

The current local reference length is

\[
\boxed{R=60\text{ trading sessions}=2W},\qquad W=30.
\]

At historical time \(t\), construct the reference set only from Strategy-window outcomes whose complete outcome dependency was already observable by \(t\). From completed outcomes in the preceding 60 trading sessions compute

\[
C_{40}(t),\ C_{60}(t),\ U_{40}(t),\ U_{60}(t).
\]

The deterministic historical state is

\[
\text{High}_t:\quad C_t>C_{60}(t)\ \land\ U_t>U_{60}(t),
\]

\[
\text{Low}_t:\quad C_t<C_{40}(t)\ \land\ U_t<U_{40}(t),
\]

and Neutral otherwise.

This state is descriptive. It is computed from known historical outcomes; there is no Layer-1 neural network.

## Gate — locked pass rule

The gate is deterministic:

\[
\boxed{G_t=\text{High}\ \text{or}\ \text{Low} \Rightarrow \text{PASS}}
\]

\[
\boxed{G_t=\text{Neutral} \Rightarrow \text{FILTER}}
\]

Thus the 40/60 rolling thresholds are used to remove the neutral/mixed region. Both tails are retained because they represent informative historical regimes of opposite direction.

The gate state itself is retained as known conditioning information:

\[
\boxed{G_t\in\{\text{High},\text{Low}\}}.
\]

High and Low must not be silently pooled into one unlabeled pass state. The downstream model/audit should preserve this distinction and may estimate separate conditional future distributions.

The gate is explicit and auditable. It must never be replaced by a classifier that attempts to infer the already-computable historical state from price-volume data.

## Price-volume context passed downstream

For every gate-eligible modeling context, the only market input remains the locked causal normalization. For \(N\in\{5,10,20,60\}\),

\[
price_N(t)=\frac{P_t}{\sum_{i=1}^{N}P_{t-i}},
\]

\[
volume_N(t)=\frac{V_t}{\sum_{i=1}^{N}V_{t-i}}.
\]

The eight channels are

```text
price_5, price_10, price_20, price_60,
volume_5, volume_10, volume_20, volume_60
```

and the causal context is

\[
\boxed{X_t\in\mathbb R^{8\times60}}.
\]

No future price-volume rows, technical indicators, future \(U\), future \(C\), future \(Q\), or future baseline values may be included in \(X_t\).

## What Layer 1 does not learn

Layer 1 does not learn or predict:

- High / Neutral / Low;
- whether the fixed Strategy is good;
- optional Strategy actions;
- future \(C\) or \(Q\).

Its only job is to provide an explicit historical gate and known gate state for the downstream probabilistic model.

## Next layer

For gate-passed historical contexts, training pairs a causal \(8\times60\) price-volume context with outcomes that occurred later historically. Because the historical record contains both sides, those future-at-the-time outcomes can be used as supervised targets.

The next-layer target is the conditional future distribution

\[
\boxed{p(C,Q\mid X,G)},\qquad G\in\{\text{High},\text{Low}\}.
\]

The first audit must therefore report High and Low separately before choosing a specific probabilistic model family.

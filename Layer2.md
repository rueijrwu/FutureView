# Strategy 1 — Layer 2 Centered-2W C/Q Prediction

## Research question

Layer 1 is a deterministic historical gate. Layer 2 does **not** relearn the gate.

The Layer 2 question is:

> Given the price-volume structure observed during the previous W sessions and the current fixed-Strategy decision point, can the model predict the C/Q outcome that will be realized when the corresponding centered 2W region is completed?

For the current decision session t and W=30, define

\[
\boxed{R_t=[t-W+1,\ t+W]}.
\]

At decision time t only the left half is observable. The right half is future. Historical training can use the complete realized region after it has occurred.

The modeling relation is

\[
\boxed{X_{t-W+1:t},D_t,G_t\rightarrow p(C_t,Q_t)}.
\]

Here D_t is the fixed current decision. In the first baseline, samples are legal Strategy Entries, so the decision is represented by sample selection rather than by an engineered technical-indicator channel.

## Target definition

For the centered region R_t, enumerate all legal Entries whose initial Entry lies in R_t and execute the fixed Strategy exactly once for each.

\[
U_t=\max_{e\in I_{R_t}}E(e).
\]

With the periodic baseline over the same centered 2W region,

\[
\boxed{C_t=U_t-B_{p,t}}.
\]

For the current legal Entry decision t, its unique fixed-Strategy return is

\[
P_{E,t}=E(t),
\]

and

\[
\boxed{Q_t=U_t-P_{E,t}}.
\]

Thus one decision sample has exactly one C and one Q target:

\[
\boxed{1\ \text{legal Entry}\rightarrow1\ C+1\ Q}.
\]

This removes the previous one-anchor-to-many-Q ambiguity.

## Interpretation

C measures how much fixed-Strategy opportunity exists in the completed centered 2W region relative to the periodic baseline. Larger C is better.

Q measures how far the current Entry decision lies below the best legal Entry available in that same centered region. Smaller Q is better and Q=0 means the current Entry attains the region upper bound.

The desired region is

\[
\boxed{C\text{ high},\quad Q\text{ small}}.
\]

## Layer 1 gate used by Layer 2

The current gate definition is locked provisionally as:

- short reference: rolling 90 trading sessions;
- short High threshold: C at/above the rolling 60th percentile and Q at/below the rolling 60th percentile;
- short Low threshold: C at/below the rolling 40th percentile and Q at/above the rolling 40th percentile;
- long reference: trailing 3 years, operationalized as 756 trading sessions;
- long confirmation: 50th percentile (median) for both C and Q.

High requires both short-relative and long-term confirmation:

\[
\boxed{C\ge C^{90}_{60}\land Q\le Q^{90}_{60}\land C>C^{3Y}_{50}\land Q<Q^{3Y}_{50}}.
\]

Low requires

\[
\boxed{C\le C^{90}_{40}\land Q\ge Q^{90}_{40}\land C<C^{3Y}_{50}\land Q>Q^{3Y}_{50}}.
\]

Neutral is filtered. If later training proves too difficult, the neutral region may be widened, but thresholds are not changed before that evidence exists.

High and Low remain distinct gate states and are passed downstream as conditioning information.

## Model input

Only causal price-volume information is allowed.

For N in {5,10,20,60},

\[
price_N(t)=\frac{P_t}{\sum_{i=1}^{N}P_{t-i}},\qquad
volume_N(t)=\frac{V_t}{\sum_{i=1}^{N}V_{t-i}}.
\]

The eight channels are

```text
price_5, price_10, price_20, price_60,
volume_5, volume_10, volume_20, volume_60
```

For the current baseline the temporal input is the previous W=30 sessions:

\[
\boxed{X_t\in\mathbb R^{8\times30}}.
\]

The 60-session denominator needed for the longest normalization remains causal and is computed from history preceding each row.

No realized future C/Q, future price rows, technical indicators, baseline values, or percentile thresholds are injected into X.

## First training baseline

The first model is intentionally small and diagnostic:

- multi-scale 1D CNN with kernel sizes 5/10/20;
- gate state High/Low retained as a one-dimensional condition;
- two continuous outputs, C and Q;
- Smooth-L1 loss on train-set standardized C/Q targets;
- chronological train/validation/test split;
- a 2W purge gap between partitions to reduce overlap leakage from centered targets.

This is not yet the final probabilistic head. Its purpose is to test whether the causal left-half price-volume structure contains learnable information about the completed centered-2W C/Q outcome. A distributional head should only be selected after this baseline and target-support audit are understood.

# Strategy 1 — Layer 2 Centered-2W C/Q Prediction

## Research question

Layer 1 is a deterministic historical gate. Layer 2 does **not** relearn, recompute, or inherit the gate.

The Layer 2 question is:

> Among legal Strategy Entries that have already passed Layer 1 as High or Low, can the causal price-volume structure observed during the previous W sessions predict the C/Q outcome that will be realized when the corresponding centered 2W region is completed?

For the current legal Entry session t and W=30, define

\[
\boxed{R_t=[t-W+1,\ t+W]}.
\]

At decision time t only the left half is observable. The right half is future. Historical training can use the complete realized region after it has occurred.

Layer 1 first determines sample eligibility. Layer 2 then learns only

\[
\boxed{X_{t-W+1:t}\rightarrow p(C_t,Q_t)\qquad\text{for Entries with }G_t\in\{High,Low\}}.
\]

The legal Entry condition and Layer 1 PASS are represented by sample selection, not by engineered input channels.

## Layer 1 handoff

Layer 1 remains unchanged and produces the rolling W30 High/Neutral/Low state table using its existing 90-session and 3-year references.

For a legal Entry at session t, Layer 2 uses an **exact same-session handoff**:

\[
\boxed{\text{Layer1.end\_index}=t}.
\]

There is no search for the latest previous Gate state and no inheritance of an older High/Low state.

- High: keep the Entry for Layer 2.
- Low: keep the Entry for Layer 2.
- Neutral: filter the Entry.
- No exact Layer 1 state at t: the Entry is not a Layer 2 sample.

High/Low labels may be retained for support counts and stratified evaluation, but they are **not model inputs**.

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

## Interpretation

C measures how much fixed-Strategy opportunity exists in the completed centered 2W region relative to the periodic baseline. Larger C is better.

Q measures how far the current Entry decision lies below the best legal Entry available in that same centered region. Smaller Q is better and Q=0 means the current Entry attains the region upper bound.

The desired region is

\[
\boxed{C\text{ high},\quad Q\text{ small}}.
\]

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

No Gate value, realized future C/Q, future price rows, technical indicators, baseline values, or percentile thresholds are injected into X.

## First training baseline

The first model is intentionally small and diagnostic:

- multi-scale 1D CNN with kernel sizes 5/10/20;
- **no Gate input feature**;
- two continuous outputs, C and Q;
- Smooth-L1 loss on train-set standardized C/Q targets;
- chronological train/validation/test split;
- purge/embargo between partitions to reduce overlap leakage from centered targets;
- High/Low retained only for support and stratified reporting.

This is not yet the final probabilistic head. Its purpose is to test whether the causal left-half price-volume structure contains learnable information about the completed centered-2W C/Q outcome after Layer 1 has already selected the Entry population.

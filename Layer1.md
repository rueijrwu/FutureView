# Strategy 1 — Deterministic Gate

## Purpose

Layer 1 is **not a learned classifier**. It is a deterministic retrospective state filter used to select informative High/Low historical contexts for Layer 2.

The fixed Strategy is never changed or optimized.

The current separation is

\[
\boxed{\text{historical C/Q statistics}\rightarrow\text{deterministic High/Neutral/Low gate}}
\]

followed by

\[
\boxed{\text{High/Low price-volume context}\rightarrow\text{Layer 2 centered-2W C/Q prediction}}.
\]

## C and Q

For any retrospective evaluation region R,

\[
U_R=\max_{e\in I_R}E(e),
\]

\[
\boxed{C_R=U_R-B_{p,R}}.
\]

For a legal Entry e in the same region,

\[
\boxed{Q_e=U_R-E(e)}.
\]

C is larger-is-better. Q is smaller-is-better and Q is non-negative by construction.

## Current gate reference structure

The gate uses two time scales.

### Short reference: rolling 90 sessions

For each evaluable historical state, use a rolling 90-trading-session reference and compute

\[
C^{90}_{40},\ C^{90}_{60},\ Q^{90}_{40},\ Q^{90}_{60}.
\]

The short-relative conditions are

\[
ShortHigh:\quad C\ge C^{90}_{60}\land Q\le Q^{90}_{60},
\]

\[
ShortLow:\quad C\le C^{90}_{40}\land Q\ge Q^{90}_{40}.
\]

The 90-session reference rolls continuously; it is not split into fixed non-overlapping blocks.

### Long reference: rolling 3 years

Use a trailing 3-year reference, operationalized as 756 trading sessions. The long reference uses the 50th percentile (median):

\[
C^{3Y}_{50},\ Q^{3Y}_{50}.
\]

Long-term confirmation is

\[
LongHigh:\quad C>C^{3Y}_{50}\land Q<Q^{3Y}_{50},
\]

\[
LongLow:\quad C<C^{3Y}_{50}\land Q>Q^{3Y}_{50}.
\]

This removes a locally relative High that is still poor on a longer historical scale, and removes a locally relative Low that is still strong on that longer scale.

## Locked provisional classification

\[
\boxed{High=ShortHigh\land LongHigh}
\]

\[
\boxed{Low=ShortLow\land LongLow}
\]

Everything else is Neutral.

The current TSLA audit using rolling 90D plus rolling 3Y produced a clean ordering in which High had higher C and lower Q than Neutral, and Low had lower C and higher Q than Neutral. The current thresholds remain unchanged for the first Layer 2 training experiment. If training later proves difficult, widening the Neutral region may be considered explicitly rather than silently changing the gate.

## Gate pass rule

\[
\boxed{High\rightarrow PASS}
\]

\[
\boxed{Low\rightarrow PASS}
\]

\[
\boxed{Neutral\rightarrow FILTER}
\]

High and Low must remain distinct downstream states.

## Relationship to Layer 2

For a current decision point t with W=30, Layer 2 uses the previous W sessions of causal price-volume information and asks what C/Q outcome will be realized after the centered 2W region

\[
R_t=[t-W+1,t+W]
\]

is completed historically.

Layer 1 therefore selects the two informative extremes. Layer 2 performs the actual price-volume prediction problem. Layer 1 itself has no neural network.

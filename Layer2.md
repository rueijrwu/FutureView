# Strategy 1 — Probabilistic C/Q Layer

## Research question

After a deterministic historical gate has accepted the current context, what distribution of future fixed-Strategy outcomes is compatible with the observed causal price-volume structure?

The model target is

\[
\boxed{p(C,Q\mid X,G)},\qquad G\in\{\text{High},\text{Low}\}.
\]

The model is not asked to predict the gate state.

## Time structure

At an anchor session \(t\):

1. all price-volume information through \(t\) is known;
2. all historical Strategy outcomes whose complete dependency ended by \(t\) are known;
3. the deterministic gate is computed only from those completed historical outcomes;
4. the causal model input is the locked previous 60-session tensor \(X_t\in\mathbb R^{8\times60}\);
5. the future evaluation window is \(W_t=[t+1,t+30]\);
6. after history has unfolded, the realized future \(C\) and legal-Entry \(Q\) values inside \(W_t\) become supervised targets.

Thus training uses historical pairs of information that would have been available at the anchor and outcomes that were future from that anchor, even though both are known to us today.

## Deterministic gate

The gate uses the most recently completed historical Strategy-window outcome available at anchor \(t\). Call it \(g_t\), with known \(C_{g_t}\) and \(U_{g_t}\).

Compare that completed outcome with completed historical outcomes from the preceding 60 trading sessions and compute the local 40/60 percentiles.

The locked pass rule is

\[
\boxed{G_t=\text{High or Low}\Rightarrow \text{PASS}},
\]

\[
\boxed{G_t=\text{Neutral}\Rightarrow \text{FILTER}}.
\]

High and Low are retained separately as known conditioning states. The gate is deterministic and auditable; it is not a learned classifier.

## Future C target

For the future W30 window,

\[
U_W=\max_{e\in I_W}E(e),
\]

and

\[
\boxed{C_W=U_W-B_{p,W}}.
\]

Every legal Entry in the same future window shares the same window-level C target.

## Future Q targets

For every legal Entry \(e\in I_W\), the fixed Strategy produces exactly one realized outcome

\[
P_E=E(e).
\]

The Entry's distance below the window upper bound is

\[
\boxed{Q_e=U_W-P_E}.
\]

Because \(U_W\) is the maximum legal-Entry outcome in the same window,

\[
\boxed{Q_e\ge 0}.
\]

\(Q_e=0\) means that Entry attains the upper bound. Larger Q means the Entry outcome is farther below the best legal Entry outcome in that window. Q is not normalized by C.

Therefore one accepted anchor can correspond to multiple realized \((C_W,Q_e)\) pairs, one for each legal Entry in the future window. This is intentional: the future is represented as a distribution over legal Entry outcomes, not as one arbitrarily selected path.

A future window with \(C_W=0\) remains a valid target window because Q no longer divides by C.

## Model input

Only the locked causal eight-channel normalization is allowed:

\[
price_N(t)=\frac{P_t}{\sum_{i=1}^{N}P_{t-i}},\qquad
volume_N(t)=\frac{V_t}{\sum_{i=1}^{N}V_{t-i}},
\]

for \(N\in\{5,10,20,60\}\), over the latest 60 sessions.

No gate statistics, realized future C/Q, future prices, or technical indicators are injected into the price-volume tensor.

## Output contract

The fundamental output remains the joint conditional distribution

\[
\boxed{p(C,Q\mid X,G)}.
\]

C and Q retain distinct meanings:

- \(C=U-B_p\): window-level opportunity relative to the periodic baseline; larger is better.
- \(Q=U-P_E\): Entry-level distance from the window upper bound; smaller is better.

No particular parametric family (Gaussian, mixture, fixed bins, etc.) is locked yet. The first implementation step audits the empirical target support after correct causal gating before choosing the probability head.

# FutureView Profitability Learning Theory

## 1. Objective

FutureView studies a **fixed trading strategy**. The strategy itself is not the object to be learned or optimized in the present framework.

The fundamental research objective is:

> Given only a fixed window of historical price and volume information available before a legal strategy Entry, estimate the probability that the Entry is profitable and estimate its realized profit.

The historical price-volume structure determines which legal Strategy outcomes occurred in the past. Those realized outcomes form the learning target.

Let the fixed strategy be \(S\). For a legal Entry \(i\), let

\[
X_i = \text{price-volume information available before Entry } i
\]

and let

\[
E_i = \text{realized profit associated with legal Entry } i.
\]

The desired mapping is therefore conceptually

\[
X_i \longmapsto \left(P(E_i>0\mid X_i,S),\; \mathbb{E}[E_i\mid X_i,S]\right).
\]

Because \(S\) is fixed, later notation may suppress explicit conditioning on \(S\).

## 2. Historical Outcome Space

For a fixed historical evaluation window \(W\), apply the fixed strategy without using any additional market filter. The resulting legal Entries and their realized profits define the empirical Strategy outcome set

\[
\mathcal{E}_W = \{E_1,E_2,\ldots,E_n\}.
\]

These outcomes are consequences of applying the fixed Strategy to the historical price-volume environment. They are not manually selected examples.

The precise representation of Entry/Add1/Add2/Exit evolution and the independence structure of outcomes remain subjects for formal definition. No learned representation should silently redefine which historical Strategy outcomes belong to the sample space.

## 3. Profitability Bounds

Within a fixed historical window \(W\), define the observed minimum and maximum Strategy profits as

\[
L_W = \min_{i\in W} E_i,
\]

\[
U_W = \max_{i\in W} E_i.
\]

Here:

- \(L_W\) is the lowest realized profit produced by a legal Strategy Entry in the window;
- \(U_W\) is the highest realized profit produced by a legal Strategy Entry in the window.

These are empirical realized-profit bounds. They are not labels such as good, bad, bullish, or bearish.

Define the observed profitability range

\[
C_W = U_W-L_W.
\]

For \(C_W>0\), define the normalized distance of Entry \(i\) from the observed upper-profit bound as

\[
Q_i = \frac{U_W-E_i}{C_W}.
\]

Therefore

\[
E_i=U_W \Rightarrow Q_i=0,
\]

and

\[
E_i=L_W \Rightarrow Q_i=1.
\]

Thus smaller \(Q_i\) means that the realized Entry outcome lies closer to the best observed Strategy outcome within the corresponding window.

## 4. Baseline Family

A single baseline is not sufficient to answer all research questions. For each historical evaluation window \(W\), the same historical price-volume path can be used to compute a family of null or reference outcomes alongside the Strategy outcomes.

Let

\[
\mathcal{B}_W = \{B_W^{(1)},B_W^{(2)},\ldots,B_W^{(k)}\}
\]

be a set of explicitly defined baselines.

The baseline family may include at least the following conceptual classes.

### 4.1 Market baseline

A market baseline \(B_W^{\mathrm{market}}\) measures the return available from the underlying market without Strategy timing, for example by buy-and-hold or a fixed periodic-investment rule.

It answers:

> How much profit was available from the market itself during this window?

### 4.2 Random-entry baseline

A random-entry baseline \(B_W^{\mathrm{random}}\) replaces the Strategy's Entry timing with random Entry timing under a fixed and explicitly defined sampling rule.

It answers:

> How much profit would have been obtained without Strategy-specific Entry selection?

### 4.3 Strategy-null baseline

A Strategy-null baseline preserves downstream Strategy mechanics, such as Add or Exit rules, while randomizing or otherwise neutralizing the Entry-selection rule.

It answers:

> How much of the observed profitability comes from the Strategy's Entry-selection structure rather than from the rest of the execution framework?

### 4.4 Matched random baseline

A matched random baseline restricts random Entry opportunities to a comparable historical context, such as the same evaluation window or another explicitly defined matched sample space.

It answers:

> Does the Strategy outperform a null Entry process under comparable market conditions?

The exact members of \(\mathcal{B}_W\) are not frozen by this document. Each baseline must be deterministic or probabilistically well-defined, reproducible, and computed from the same historical information used to construct the Strategy outcome space.

## 5. Profit Opportunity Relative to Baseline

For any selected baseline \(B_W^{(j)}\), define the observed upper-profit opportunity above that baseline as

\[
A_W^{(j)} = U_W-B_W^{(j)}.
\]

This quantity answers:

> How much additional realized profit was available at the best legal Strategy outcome relative to baseline \(j\)?

Different baselines therefore produce different notions of opportunity.

For example:

\[
A_W^{\mathrm{market}}=U_W-B_W^{\mathrm{market}}
\]

measures the maximum observed Strategy upside relative to passive market participation, while

\[
A_W^{\mathrm{random}}=U_W-B_W^{\mathrm{random}}
\]

measures the maximum observed Strategy upside relative to a null Entry process.

This is distinct from

\[
C_W=U_W-L_W,
\]

which measures the spread between the best and worst observed Strategy outcomes rather than opportunity relative to a baseline.

## 6. Information and Tradable-Value Space

The framework distinguishes **information strength** from **tradable value**.

A neutral or uncertain market state is one for which the Strategy's profitable-outcome probability is near

\[
P(\mathrm{win})\approx 0.5.
\]

A strongly informative state may lie on either side of neutrality:

\[
P(\mathrm{win})\gg 0.5
\]

or

\[
P(\mathrm{win})\ll 0.5.
\]

Separately, tradable value depends on how much economic opportunity is available relative to an appropriate baseline, for example

\[
U_W-B_W^{(j)}.
\]

This produces four conceptual regions:

1. high information, high tradable value;
2. low information, high tradable value;
3. low information, low tradable value;
4. high information, low tradable value.

The role of a first-stage gate, if adopted, is not simply to remove losing states. Strongly negative states can still be highly informative. The main motivation for gating is to prevent a large population of weakly informative, near-neutral observations from dominating learning while preserving economically meaningful and informative regions.

Whether low-tradable-value but informative regions should be learned with full weight, reduced weight, or only retained for validation remains an open research question.

## 7. Price-Volume Information as the Primitive Market Input

All conventional technical indicators are transformations of underlying market observations, principally price and volume. The framework therefore treats historical price-volume information as the primitive market input rather than assuming a large manually selected technical-indicator set.

Let a fixed lookback representation before Entry \(i\) be

\[
X_i = \{P,V\}_{i-T:i},
\]

where \(P\) denotes price information, \(V\) denotes volume information, and \(T\) denotes the historical lookback horizon.

The exact normalization, channels, sampling convention, and tensor representation of \(X_i\) are intentionally not defined in this theory document.

## 8. Learned Market Representation

The central representation problem is to learn a compact mapping

\[
f: X_i \rightarrow Z_i,
\]

where

\[
Z_i=(z_{i1},z_{i2},\ldots,z_{im})
\]

is a learned representation of the historical price-volume state relevant to the profitability of the fixed Strategy.

The representation is not required to reproduce named technical indicators. It should preserve information useful for estimating Strategy profitability while reducing dependence on manually engineered and potentially redundant transformations of price and volume.

At this stage, the dimensionality \(m\), semantic interpretation of each component, and learning objective used to obtain \(Z_i\) are deliberately left open.

## 9. Profitability Estimation

Given a learned representation \(Z_i\), the eventual profitability estimator should address at least two quantities:

### 9.1 Probability of profitable Entry

\[
p_i = P(E_i>0\mid Z_i).
\]

This is the estimated probability that a legal Entry under the fixed Strategy produces positive realized profit.

### 9.2 Expected profit

\[
\mu_i = \mathbb{E}[E_i\mid Z_i].
\]

This estimates the expected realized Strategy profit conditional on the historical market representation.

The normalized upper-bound distance may additionally be estimated:

\[
q_i = \mathbb{E}[Q_i\mid Z_i].
\]

Whether \(Q\) should be a direct learning target, an evaluation quantity, or a derived diagnostic remains open.

## 10. Conditional Strategy Decision States

A Strategy may contain sequential decision points such as Entry followed by one or more Add decisions and Exit decisions.

These decision states are nested rather than independent. If \(S_A\) denotes the set of paths reaching Add and \(S_E\) the set of legal Entry paths, then

\[
S_A\subseteq S_E.
\]

Therefore profitability questions at later Strategy decisions are conditional questions.

At Entry, the framework may consider quantities such as

\[
P(\mathrm{win}\mid \mathrm{Entry},Z_E),
\]

\[
\mathbb{E}[E\mid \mathrm{Entry},Z_E],
\]

and

\[
P(\mathrm{Add}\mid \mathrm{Entry},Z_E).
\]

If Add later occurs, the relevant state is updated and the corresponding questions become conditional on both the earlier Entry and the observed Add event.

A realized Add path may be compared both with the best outcome in the full Entry population and with the best outcome within the Add subset. These are different comparisons and should use separately defined bounds.

## 11. Conceptual Separation of Representation and Profitability

Two conceptual functions should be distinguished:

\[
X_i \xrightarrow{f} Z_i
\]

and

\[
Z_i \xrightarrow{g} \text{Strategy profitability estimates}.
\]

The first asks:

> What compact information in historical price-volume data is relevant to the fixed Strategy?

The second asks:

> Given that information, what is the probability and expected magnitude of Strategy profitability?

This conceptual separation does **not** require two independently trained machine-learning models. The representation and profitability estimator may ultimately be learned separately or jointly. That choice is an empirical modeling question.

A separate two-stage research design may also be considered in which an initial information/opportunity gate suppresses large neutral regions before detailed profitability estimation. This gating interpretation is distinct from the representation-versus-profitability separation above.

## 12. Information Boundary

For any Entry-time prediction, the model input may contain only information available at or before the prediction time.

Future information may be used only to construct historical training outcomes such as \(E_i\), \(L_W\), \(U_W\), baseline outcomes, and derived quantities such as \(Q_i\).

This establishes the fundamental temporal boundary:

\[
\text{past information} \rightarrow \text{future Strategy outcome}.
\]

No future-derived quantity may enter the predictive input representation.

## 13. Current Open Question

The next theoretical task is **representation definition**.

Specifically:

> What should \(Z\) represent, what information should it be required to preserve, and what learning objective can produce that representation from raw historical price-volume information without merely reconstructing a manually chosen collection of technical indicators?

No CNN architecture, latent dimension, loss function, or implementation choice is fixed by this document yet.

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

## 4. Strategy-Independent Baseline

For the same historical window \(W\), define a baseline profit

\[
B_W,
\]

computed without Strategy timing, for example from a fixed periodic-investment rule.

The role of \(B_W\) is to describe the profitability available from the underlying market over the same period independently of the Strategy's Entry/Add/Exit decisions.

Consequently, \(B_W\) provides a reference against which Strategy-dependent profitability may later be interpreted. Its exact baseline rule must be fixed before empirical comparison.

## 5. Price-Volume Information as the Primitive Market Input

All conventional technical indicators are transformations of underlying market observations, principally price and volume. The framework therefore treats historical price-volume information as the primitive market input rather than assuming a large manually selected technical-indicator set.

Let a fixed lookback representation before Entry \(i\) be

\[
X_i = \{P,V\}_{i-T:i},
\]

where \(P\) denotes price information, \(V\) denotes volume information, and \(T\) denotes the historical lookback horizon.

The exact normalization, channels, sampling convention, and tensor representation of \(X_i\) are intentionally not defined in this theory document.

## 6. Learned Market Representation

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

## 7. Profitability Estimation

Given a learned representation \(Z_i\), the eventual profitability estimator should address at least two quantities:

### 7.1 Probability of profitable Entry

\[
p_i = P(E_i>0\mid Z_i).
\]

This is the estimated probability that a legal Entry under the fixed Strategy produces positive realized profit.

### 7.2 Expected profit

\[
\mu_i = \mathbb{E}[E_i\mid Z_i].
\]

This estimates the expected realized Strategy profit conditional on the historical market representation.

The normalized upper-bound distance may additionally be estimated:

\[
q_i = \mathbb{E}[Q_i\mid Z_i].
\]

Whether \(Q\) should be a direct learning target, an evaluation quantity, or a derived diagnostic remains open.

## 8. Conceptual Separation of Representation and Profitability

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

## 9. Information Boundary

For any Entry-time prediction, the model input may contain only information available at or before the prediction time.

Future information may be used only to construct historical training outcomes such as \(E_i\), \(L_W\), \(U_W\), and derived quantities such as \(Q_i\).

This establishes the fundamental temporal boundary:

\[
\text{past information} \rightarrow \text{future Strategy outcome}.
\]

No future-derived quantity may enter the predictive input representation.

## 10. Current Open Question

The next theoretical task is **representation definition**.

Specifically:

> What should \(Z\) represent, what information should it be required to preserve, and what learning objective can produce that representation from raw historical price-volume information without merely reconstructing a manually chosen collection of technical indicators?

No CNN architecture, latent dimension, loss function, or implementation choice is fixed by this document yet.

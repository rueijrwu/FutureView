# FutureView Profitability Learning Theory

## 1. Objective

FutureView studies a **fixed trading strategy**. The Strategy is not being optimized in the present framework.

Before attempting any CNN or raw price-volume prediction problem, the current research stage asks a more basic question:

> How should one historical Strategy outcome environment be represented, and does that representation contain a stable low-dimensional structure?

No CNN, gate, or predictive mapping from price-volume is assumed at this stage.

## 2. Historical Strategy outcomes

For a fixed historical evaluation window \(W\), let

\[
\mathcal E_W=\{E_1,E_2,\ldots,E_n\}
\]

be the realized profits of the legal Strategy outcomes observed in that window.

These outcomes are consequences of applying the fixed Strategy to the historical price-volume environment. They are not manually selected examples.

## 3. Profitability bounds and normalized path position

Define

\[
L_W=\min_i E_i,
\]

\[
U_W=\max_i E_i,
\]

and

\[
C_W=U_W-L_W.
\]

For \(C_W>0\), define

\[
Q_i=\frac{U_W-E_i}{C_W}.
\]

Thus \(Q_i=0\) corresponds to the observed upper-profit bound and \(Q_i=1\) corresponds to the observed lower-profit bound.

The collection \(\{Q_i\}\) is a distribution over legal Strategy outcomes within a historical window.

## 4. Baseline family

A historical window may also be described by a family of reference outcomes

\[
\mathcal B_W=\{B_W^{(1)},B_W^{(2)},\ldots,B_W^{(k)}\}.
\]

Possible members include:

- market / buy-and-hold baseline;
- fixed periodic-investment baseline;
- random-entry baseline;
- Strategy-null baseline in which Entry selection is neutralized while downstream rules are retained;
- matched-random baseline under comparable market conditions.

Each baseline must have a clear null/reference interpretation and be reproducible.

For baseline \(j\), the upper-profit opportunity relative to that baseline is

\[
A_W^{(j)}=U_W-B_W^{(j)}.
\]

This is distinct from

\[
C_W=U_W-L_W.
\]

## 5. Candidate Representation A: minimal direct statistics

The first candidate representation is

\[
Y_W^{(A)}=
[L_W,\ U_W,\ B_W^{(1)},\ldots,B_W^{(k)}].
\]

Representation A deliberately excludes quantities that are exact algebraic functions of these variables, such as

\[
C_W=U_W-L_W
\]

and

\[
U_W-B_W^{(j)}.
\]

The purpose of Representation A is not to train an Autoencoder. It is the direct statistical baseline for the research.

Before introducing a learned latent space, analyze the historical distribution and dependence structure of

\[
L,\ U,\ B_1,\ldots,B_k.
\]

The first questions are therefore empirical and descriptive:

1. how do \(L\) and \(U\) vary across historical windows;
2. how strongly are the different baselines related to each other;
3. how strongly are the baselines related to \(L\) and \(U\);
4. whether several baselines provide genuinely different information or mostly repeat the same historical structure;
5. whether chronological periods show materially different statistical structure.

Representation A provides the simplest reference against which any later Autoencoder result must be compared.

## 6. Candidate Representation B: bounds, baselines, and normalized outcome shape

Representation A does not distinguish two windows that have the same \(L\), \(U\), and baselines but very different distributions of legal Strategy outcomes between those bounds.

Representation B therefore augments A with a fixed-length summary of the \(Q\) distribution.

A first candidate is

\[
Y_W^{(B)}=
[
L_W,
U_W,
B_W^{(1)},\ldots,B_W^{(k)},
Q_{10,W},
Q_{25,W},
Q_{50,W},
Q_{75,W},
Q_{90,W}
].
\]

The exact quantile set is not frozen yet. The important distinction is that Representation B contains two kinds of information:

- \(L,U,B_i\): absolute profitability scale and baseline context;
- \(Q\)-distribution summaries: the normalized shape of legal Strategy outcomes between the observed lower and upper bounds.

Representation B is the first candidate for an unsupervised Autoencoder test.

## 7. Why B may require an Autoencoder

As more meaningful baselines and distribution summaries are added, the descriptor vector can contain substantial empirical redundancy.

For example, two different baselines may have no exact algebraic relationship but may historically move together because they respond to the same underlying market environment.

The role of the Autoencoder is therefore to test whether the richer descriptor space

\[
Y_W^{(B)}
\]

admits a smaller representation

\[
Y_W^{(B)}
\xrightarrow{\text{Encoder}}
Z_W
\xrightarrow{\text{Decoder}}
\hat Y_W^{(B)},
\]

with

\[
\hat Y_W^{(B)}\approx Y_W^{(B)}.
\]

No semantic meaning is assigned to the coordinates of \(Z\) in advance.

## 8. Algebraic redundancy must not be mistaken for discovered structure

A low-dimensional reconstruction is not meaningful if it is achieved mainly by supplying exact copies of the same information.

Therefore quantities such as

\[
C=U-L
\]

and

\[
U-B_i
\]

should not be simultaneously treated as independent inputs when \(L\), \(U\), and \(B_i\) are already present.

The research must distinguish:

- **derived redundancy**: relationships true by definition;
- **empirical redundancy**: relationships that emerge from historical data but are not mathematically required.

Only the latter is evidence that the historical Strategy outcome environment may live on a lower-dimensional manifold.

## 9. Profit relationships are examined only after Z is formed

The Autoencoder is not trained to maximize profit prediction, win-rate separation, information strength, tradable value, or any predefined interpretation of \(Z\).

The research order is:

\[
Y_W^{(B)}
\rightarrow
Z_W
\rightarrow
\text{post-hoc observation of profitability relationships}.
\]

No relationship between \(Z\) and later profit statistics is assumed beforehand.

Only after a low-dimensional \(Z\) is established should the research ask whether different regions or coordinates of \(Z\) show stable relationships with realized profitability.

## 10. Current research sequence

The current sequence is:

1. generate historical legal Strategy outcomes and meaningful baselines;
2. construct Representation A: \([L,U,B_i]\);
3. analyze A directly with descriptive and chronological statistics, without an Autoencoder;
4. construct Representation B by adding fixed-length summaries of the \(Q\) distribution;
5. test whether B admits a stable low-dimensional \(Z\) using an unsupervised Autoencoder;
6. only after \(Z\) is formed, examine its relationship with withheld profitability statistics;
7. only if that structure is meaningful, return to the question of how raw price-volume information may map into it.

No CNN architecture, gate, latent semantic interpretation, or profitability prediction head is assumed before these steps are established empirically.

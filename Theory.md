# FutureView Profitability Learning Theory

## 1. Objective

FutureView studies a **fixed trading strategy**. The Strategy is not being optimized in the present framework.

Before attempting any CNN or raw price-volume prediction problem, the current research stage asks a more basic question:

> How should one historical Strategy outcome environment be represented, and does that representation contain a stable low-dimensional structure?

No CNN, gate, or predictive mapping from price-volume is assumed at this stage.

## 2. Deterministic Strategy path definition

All Strategy calculations in the current historical experiment use **daily close prices only**.

Over the complete five-year historical sample, first identify:

- all legal Entry dates under the fixed Strategy Entry rule;
- all legal 5-day and 10-day Exit events under the fixed Strategy Exit rule;
- the complete union of 5-day and 10-day local minima;
- the complete union of 5-day and 10-day local maxima.

For this retrospective outcome-space experiment, a 5-day local extremum is a close that is the extremum relative to the preceding five and following five trading sessions. A 10-day local extremum is defined analogously using the preceding ten and following ten trading sessions. This retrospective definition is used only to define historical outcomes; any later tradable/predictive experiment must separately handle confirmation delay.

For a legal Entry at index \(e\) with close \(P_e\), let \(m_b\) be the most recent 5-day or 10-day local minimum before \(e\). Define the campaign's fixed base distance

\[
D_b=P_e-P_{m_b}.
\]

A campaign is eligible for deterministic path construction only when such a prior local minimum exists and \(D_b>0\).

The initial Entry deploys one third of the total campaign capital.

After Entry, Addon candidates are restricted to the chronological union of **5-day and 10-day local maxima**. An Addon may occur only at a candidate local maximum \(a_i\) whose close is more than \(D_b\) above the previous actual Entry/Addon price:

\[
P_{a_i}-P_{i-1}>D_b.
\]

The first chronological candidate satisfying this inequality becomes the next Addon. The same fixed \(D_b\) is reused for every Addon. Each Addon deploys another one third of total campaign capital, and the Strategy permits at most three total capital deployments:

\[
\text{Entry}+\text{Addon1}+\text{Addon2}.
\]

Therefore Addon levels are **not enumerated as alternative reference configurations**. For a given legal Entry, the Strategy produces one deterministic Addon sequence.

Exit logic is also deterministic. Once a campaign is active:

- the first legal 5-day exit event sells 40% of the then-current position;
- a legal 10-day exit event liquidates all remaining shares (the remaining 60% when the 5-day exit has already occurred);
- no new Addon is allowed after the first exit event;
- any position still open at the fixed campaign horizon is liquidated at the horizon close.

Each Entry/Add-on purchase uses one third of the original total-capital denominator. Unused capital remains cash. Campaign profit is measured relative to that same total-capital denominator.

## 3. Historical evaluation windows and Strategy outcomes

For a fixed historical evaluation window

\[
W=[t_0,t_1],
\]

let the legal Entry set be

\[
\mathcal I_W=\{e:\ t_0\le e\le t_1,\ e\text{ is a legal Entry}\}.
\]

Window membership is determined by the **initial Entry date only**. The deterministic Strategy path that begins at \(e\) may continue beyond \(t_1\) until its Exit or fixed campaign horizon.

Let

\[
\mathcal E_W=\{E(e):e\in\mathcal I_W\}
\]

be the realized profits of the deterministic Strategy paths whose initial Entries lie in the window.

Thus one legal Entry contributes at most one Strategy outcome. Historical windows do not enumerate alternative Addon-reference configurations.

## 4. Profitability bounds and normalized path position

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

The collection \(\{Q_i\}\) is a distribution over legal deterministic Strategy outcomes within a historical window.

## 5. Baseline family

The current minimal baseline family contains two references.

### 5.1 Periodic baseline

\(B_{\text{periodic}}\) uses the same maximum of three capital deployments. One third of total capital is invested at each of three evenly spaced dates inside the evaluation window; all three tranches are valued at the common window end. Unused capital remains cash until deployed.

### 5.2 Random indicator

\(B_{\text{random}}\) is only a coarse descriptive indicator, not a separate research target. A small fixed-seed sample chooses one to three random Entry dates within the window, each deploying one third of total capital, and values all positions at the common window end. The sample mean is retained.

For baseline \(j\), define the signed upper-bound difference

\[
A_W^{(j)}=U_W-B_W^{(j)}.
\]

This quantity is allowed to be negative. A negative value means that even the best observed deterministic Strategy Entry in that window underperformed the baseline.

This is distinct from

\[
C_W=U_W-L_W.
\]

## 6. Candidate Representation A: minimal direct statistics

The first candidate representation is

\[
Y_W^{(A)}=
[L_W,\ U_W,\ B_{\text{periodic},W},\ B_{\text{random},W}].
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
L,\ U,\ B_{\text{periodic}},\ B_{\text{random}}.
\]

The first questions are therefore empirical and descriptive:

1. how do \(L\) and \(U\) vary across historical windows;
2. how strongly are the baselines related to each other;
3. how strongly are the baselines related to \(L\) and \(U\);
4. whether chronological periods show materially different statistical structure;
5. how often and by how much \(U\) exceeds or falls below \(B_{\text{periodic}}\).

Representation A provides the simplest reference against which any later Autoencoder result must be compared.

## 7. Candidate Representation B: bounds, baselines, and normalized outcome shape

Representation A does not distinguish two windows that have the same \(L\), \(U\), and baselines but very different distributions of legal Strategy outcomes between those bounds.

Representation B therefore augments A with a fixed-length summary of the \(Q\) distribution.

A first candidate is

\[
Y_W^{(B)}=
[
L_W,
U_W,
B_{\text{periodic},W},
B_{\text{random},W},
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

## 8. Why B may require an Autoencoder

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

## 9. Algebraic redundancy must not be mistaken for discovered structure

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

## 10. Profit relationships are examined only after Z is formed

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

## 11. Current research sequence

The current sequence is:

1. generate historical legal Entries, local extrema, deterministic Strategy paths, and meaningful baselines;
2. verify directly whether the deterministic Strategy upper bound \(U\) can exceed \(B_{\text{periodic}}\) in historical windows;
3. construct Representation A: \([L,U,B_{\text{periodic}},B_{\text{random}}]\);
4. analyze A directly with descriptive and chronological statistics, without an Autoencoder;
5. construct Representation B by adding fixed-length summaries of the \(Q\) distribution;
6. test whether B admits a stable low-dimensional \(Z\) using an unsupervised Autoencoder;
7. only after \(Z\) is formed, examine its relationship with withheld profitability statistics;
8. only if that structure is meaningful, return to the question of how raw price-volume information may map into it.

No CNN architecture, gate, latent semantic interpretation, or profitability prediction head is assumed before these steps are established empirically.

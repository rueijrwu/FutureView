# Strategy 1 — Temporary Entry-Centered C/Q Experiment

## Status

This document describes an experimental architecture on the temporary branch `tmp-entry-centered-cq`.

The original Layer 1 definition on the baseline branch is not changed by this experiment.

The purpose here is to answer one small question:

> If each legal Entry t is assigned a C/Q target from a region centered on that Entry, what can actually be known at t, what is only a historical label, and where can a causal Gate exist?

---

## 1. Entry-centered target

For a legal Entry at session t and W=30, define

\[
\boxed{R_t=[t-W+1,\ t+W]}.
\]

The left half is already known at Entry time:

\[
H_t=[t-W+1,t].
\]

The right half is future:

\[
F_t=[t+1,t+W].
\]

After the future has occurred, enumerate all legal Entries in the completed centered region and execute the fixed Strategy for each:

\[
U_t=\max_{e\in I_{R_t}}E(e).
\]

With the periodic baseline over the same centered region,

\[
\boxed{C_t=U_t-B_{p,t}}.
\]

For the current Entry t,

\[
\boxed{Q_t=U_t-E(t)}.
\]

Interpretation:

- C_t describes the total Strategy opportunity of the local region surrounding Entry t.
- Q_t describes how far Entry t is from the best legal Entry in that same local region.
- C_t is not a direct future-return quantity.
- Q_t is not known at Entry time because both U_t and the completed outcome E(t) depend on future prices.

Thus one historical sample is

\[
\boxed{1\ legal\ Entry\ t\rightarrow1\ centered\ C_t+1\ centered\ Q_t}.
\]

---

## 2. Historical Entry-centered C/Q audit

Using TSLA 5y history with W=30:

- legal Entries: 250;
- usable centered Entries with a complete left/right region: 230.

Therefore the current historical supervised population is

\[
\boxed{230\ Entry\ decision\ samples}.
\]

Each sample is

\[
\boxed{(X_t,C_t,Q_t)}
\]

where X_t is the causal price-volume structure available at that Entry time.

### C distribution

- mean: -8.50%
- median: -7.46%
- P20: -21.68%
- P40: -12.20%
- P60: -3.47%
- P80: +7.57%
- P90: +13.28%

### Q distribution

- mean: 4.67%
- median: 3.42%
- P20: 1.04%
- P40: 2.53%
- P60: 4.69%
- P80: 7.65%
- P90: 11.13%
- Q=0 rate: 6.52%

C and Q are related but are not redundant:

\[
Pearson(C,Q)=-0.144,
\]

\[
Spearman(C,Q)=-0.275.
\]

The highest C quintile had mean C of +13.67% and median Q of 1.09%, showing that high-opportunity regions are more likely to contain Entries with relatively good timing quality, while the relationship is far from deterministic.

---

## 3. Provisional Good / Bad / Neutral historical labels

For exploratory analysis only, use the 40/60 joint split:

\[
Good:\quad C\ge C_{60}\land Q\le Q_{40},
\]

\[
Bad:\quad C\le C_{40}\land Q\ge Q_{60}.
\]

Everything else is Neutral.

The 230 usable Entry-centered samples produced:

- Good: 55 (23.9%)
- Bad: 44 (19.1%)
- Neutral: 131 (57.0%)

Thus

\[
\boxed{99/230=43.0\%}
\]

of historical legal Entries lie in a clearly favorable or unfavorable joint C/Q region under this provisional split.

This split is not yet the new Layer 1 Gate. It is only a way to inspect how much useful tail structure exists in the Entry-centered labels.

---

## 4. Entry samples remain real decision samples even when temporally clustered

Good and Bad Entries are temporally clustered. That does **not** mean clustered Entries should be collapsed into one training sample.

The research unit is the legal Entry decision itself:

\[
\boxed{1\ legal\ Entry=1\ real\ decision\ opportunity}.
\]

Two nearby legal Entries t and t+1 have different causal states:

\[
X_t\neq X_{t+1},
\]

and different deterministic Strategy outcomes:

\[
E(t)\neq E(t+1)
\]

in general.

They also have different centered regions:

\[
R_t=[t-W+1,t+W],
\]

\[
R_{t+1}=[t-W+2,t+W+1].
\]

Therefore they can legitimately have different C and Q targets.

The temporal cluster audit found strong correlation structure, but its purpose is only to constrain evaluation methodology. It does **not** reduce the 230 decision samples to a handful of regime samples.

Correct interpretation:

\[
\boxed{230\ Entry\ samples\ remain\ 230\ Entry\ decisions}
\]

with temporal dependence between nearby samples.

Consequently:

- retain all Entry samples for learning;
- do not use random train/test splitting;
- use chronological OOS evaluation with appropriate purge/embargo so near-duplicate market contexts and overlapping centered targets do not leak across partitions.

---

## 5. The key causality fact

At deployment time t, the centered target cannot be calculated exactly.

The future half

\[
[t+1,t+W]
\]

has not happened yet. Therefore

\[
\boxed{C_t\text{ and }Q_t\text{ are historical labels, not causal Entry-time features.}}
\]

Historical training may use future data only to construct the label. Model inputs must remain causal.

This is standard supervised-learning structure.

### Historical training

For historical legal Entry t:

1. freeze the information that was available at t;
2. construct causal input X_t only from data at or before t;
3. after the future region is complete, calculate realized centered target (C_t,Q_t);
4. learn the relationship between the Entry-time structure and the later realized target.

Formally,

\[
\boxed{X_{t-W+1:t}\rightarrow p(C_t,Q_t)}.
\]

### Deployment

For a new legal Entry t, only X_t exists. The realized target does not yet exist.

The system therefore estimates

\[
\boxed{p(C_t,Q_t\mid X_t)}.
\]

It does not calculate the true centered C_t or Q_t.

---

## 6. Why centered C/Q cannot itself be the pre-model Gate

A Gate applied at Entry time must use information available at Entry time t.

If the Gate requires the realized centered target,

\[
G_t=f(C_t,Q_t),
\]

then it requires future information and is not deployable.

Therefore this architecture is invalid for real-time use:

\[
\boxed{\text{true centered C/Q}\rightarrow Gate\rightarrow Model}.
\]

The historical Good/Bad/Neutral labels above can be targets for analysis or supervision, but they cannot be directly known at Entry time.

---

## 7. Important issue with the original retrospective Layer 1 Gate

The original Layer 1 remains valid as a retrospective historical-state classifier. It classifies rolling W30 regions using realized C/Q and 90-session plus 3-year references.

However, a separate causality question exists for real-time deployment.

The realized C/Q of a W30 region depends on deterministic Strategy outcomes E(e) for Entries inside that region. An Entry near the end of the W30 can remain active after the W30 end because the Strategy path has a longer horizon.

Therefore, at session t, the apparent past-W30 C/Q may still require prices after t before every E(e) is complete.

Consequently:

\[
\boxed{\text{original Layer 1 is presently a retrospective state label, not yet proven to be a causal real-time Gate.}}
\]

This does not invalidate the original Layer 1 analysis. It only limits what role it can play at deployment time.

---

## 8. Next research question: how should Layer 1 Gate work?

This is now the next question and should be answered before training a larger model:

> A legal Entry occurs at t. The true centered C_t and Q_t do not yet exist. What causal, past-only information should Layer 1 use to decide whether this Entry should be passed to the C/Q prediction model?

The Gate must satisfy all of the following:

1. It must be computable at Entry time t.
2. It must not use realized centered C_t or Q_t.
3. It must not use incomplete Strategy outcomes that require prices after t.
4. It should remove genuinely low-information / ambiguous Entries rather than merely reproducing the target definition.
5. It should preserve enough samples that useful Entry-level signal is not discarded.
6. Its purpose must be explicit: sample selection, not target prediction disguised as a Gate.

Three candidate directions remain logically valid and must now be compared.

### Candidate A — no pre-model Gate

Every legal Entry is passed:

\[
Entry_t\rightarrow X_t\rightarrow p(C_t,Q_t).
\]

The final decision Gate is applied to the predicted C/Q distribution.

### Candidate B — causal learned Gate

Use historical centered C/Q only as the target for a separate causal classifier:

\[
X_t\rightarrow p(Good/Neutral/Bad).
\]

This would make Layer 1 learned rather than deterministic.

### Candidate C — deterministic past-only Gate

Build a new causal state statistic using only information fully observable by t, such as completed historical Strategy outcomes or purely price-volume state variables.

This keeps Layer 1 deterministic but creates a new definition that must be audited separately from the original retrospective Layer 1.

No candidate is selected yet.

The immediate next task is therefore:

\[
\boxed{\text{design and audit candidate causal Gate definitions using only information available at Entry time}}.
\]

Do not train Layer 2 until this Gate question is resolved conceptually.

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

## 2. The key causality fact

At deployment time t, the centered target cannot be calculated exactly.

The future half

\[
[t+1,t+W]
\]

has not happened yet. Therefore

\[
\boxed{C_t\text{ and }Q_t\text{ are historical labels, not causal Entry-time features.}}
\]

This is the central distinction of the experiment.

Historical training is allowed to use future data only to construct the label. Model inputs must remain causal.

This is standard supervised-learning structure:

### Historical training

For historical legal Entry t:

1. freeze the information that was available at t;
2. construct causal input X_t only from data at or before t;
3. wait historically until the future region is complete;
4. calculate the realized centered target (C_t,Q_t);
5. train a mapping from causal Entry-time information to the later realized label.

Formally,

\[
\boxed{X_{t-W+1:t}\rightarrow p(C_t,Q_t)}.
\]

### Deployment

For a new legal Entry t, only X_t exists. The realized target does not yet exist.

The system therefore produces an estimate or distribution:

\[
\boxed{p(C_t,Q_t\mid X_t)}.
\]

It does not calculate the true centered C_t or Q_t.

---

## 3. Why centered C/Q cannot be used by a causal pre-model Gate

A Gate applied before prediction must use information available at Entry time t.

If the Gate requires the centered target itself,

\[
G_t=f(C_t,Q_t),
\]

then the Gate requires future information and is not deployable.

Therefore the following architecture is invalid for real-time use:

\[
\boxed{\text{true centered C/Q}\rightarrow Gate\rightarrow Model}
\]

because the first arrow already uses future information.

This is true even if the centered C/Q is perfectly well-defined historically.

---

## 4. Important issue with the original retrospective Layer 1 Gate

The original Layer 1 is still valid as a retrospective historical-state classifier. It classifies rolling W30 regions using their realized C/Q and 90-session plus 3-year references.

However, a separate causality question exists for real-time deployment.

The realized C/Q of a W30 region depends on deterministic Strategy outcomes E(e) for Entries inside that region. An Entry near the end of the W30 can remain active after the W30 end because the Strategy path has a longer horizon.

Therefore, at session t, the apparent "past W30 C/Q" may still require prices after t before every E(e) is complete.

Consequently:

\[
\boxed{\text{original Layer 1 is presently a retrospective state label, not yet proven to be a causal real-time Gate.}}
\]

This does not invalidate the original Layer 1 analysis. It only limits what role it can play at deployment time.

---

## 5. Three logically valid ways to handle the Gate

### Option A — No causal Gate before the centered-C/Q model

Use every legal Entry as a candidate sample:

\[
Entry_t\rightarrow X_t\rightarrow p(C_t,Q_t).
\]

Then make the decision after prediction, for example using a favorable region such as

\[
C\text{ sufficiently high},\qquad Q\text{ sufficiently low}.
\]

In this architecture, the old Layer 1 remains an offline research/state-analysis tool, not a deployment filter.

This is the cleanest architecture if the research question is simply:

> Can Entry-time information tell us the likely C/Q quality of this Entry-centered region?

### Option B — Learned causal Gate first

Historically derive a Gate label from the completed centered C/Q, but train a separate classifier using only causal past information:

\[
X_t\rightarrow p(G_t).
\]

Only if the predicted Gate passes does the second model estimate detailed C/Q.

This is valid supervised learning, but it changes the meaning of Layer 1: Layer 1 becomes learned rather than the current deterministic retrospective Gate.

This must not be done silently.

### Option C — Define a strictly matured past-only deterministic Gate

Construct a Gate only from Strategy outcomes that are fully completed before t.

For example, include only historical Entries e whose complete deterministic path is already known by t.

This would be causal and deterministic, but introduces lag and changes the current Layer 1 state definition. It may describe an older market state rather than the immediate W30 ending at t.

Again, this would be a new Gate definition and must be evaluated separately.

---

## 6. Current recommendation for this temporary branch

Do not force centered C/Q into the old Layer 1 Gate.

For this experiment, keep the roles separated:

### Offline retrospective analysis

Original Layer 1:

\[
\boxed{realized\ rolling\ W30\ C/Q\rightarrow High/Neutral/Low}
\]

This tells us what kind of Strategy state actually occurred historically and remains useful for interpretation, regime analysis, and audits such as past-W versus next-W behavior.

### Entry-centered supervised question

At every historical legal Entry t:

\[
\boxed{X_{t-W+1:t}\rightarrow(C_t,Q_t)_{centered}}
\]

with future data used only to construct the target.

At deployment:

\[
\boxed{X_t\rightarrow p(C_t,Q_t)}.
\]

Only after this prediction should a deployable decision rule decide whether the Entry is attractive.

This means the temporary centered-C/Q experiment should initially be tested **without the original Layer 1 as a hard deployment Gate**.

The original Layer 1 state can still be attached afterward for retrospective stratified analysis, provided no future-derived state is used as an input to the model.

---

## 7. Why this is useful

This architecture asks a cleaner causal question than trying to calculate C/Q at the Entry itself:

\[
\boxed{\text{Given what I know now, what kind of completed local C/Q region is this Entry likely to belong to?}}
\]

That is exactly what supervised learning can test.

If the answer is no, then past price-volume information does not contain enough information to estimate centered C/Q.

If the answer is yes, then a later decision Gate can be built from the predicted distribution rather than from unavailable future C/Q.

---

## 8. Open question before training

Before changing the architecture further, the next audit should explicitly quantify the time availability of the original Layer 1 metrics:

- for each W30 ending at t, what fraction of Entries inside that W30 have completed deterministic outcomes by t?
- how much later than t is the final information required to compute the original realized C/Q?
- does a matured-only causal approximation preserve the original High/Neutral/Low ordering?

Until that audit is completed, do not call the original realized W30 Gate a deployable real-time Gate.

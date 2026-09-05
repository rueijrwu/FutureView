# FutureView Strategy 1 — Current Research Handoff

Last rewritten: 2026-09-04
Branch: `layer2-price-distribution-v1`

This document is the current authoritative research handoff. It replaces older Strategy 1 / Layer1 / Layer2 assumptions that conflict with the definitions below.

The detailed rule registry is `LAYER2_EXPERIMENT_VARIABLES.md`. No Strategy rule, Layer1 membership rule, Layer2 training boundary, target definition, purge/embargo rule, model input, loss, or evaluation rule may be silently added or changed.

---

# 0. Current research direction

The Strategy itself is fixed. The current task is to rebuild Layer1 under the revised complete-path window rule, re-check the statistical structure of U/C/Q, and only then resume Layer2 model training.

Current working choices / scope:

```text
Ticker: TSLA
History: 8Y
Layer1 W: 30 trading sessions
Layer2 raw input history: 90 trading sessions normalized P/V
Layer2 rolling training lookback: immediately preceding 30 trading sessions
Fresh retrain candidate cadence: 15 trading sessions
Layer2 scope: H-only
```

Important separation of time variables:

```text
W             = Layer1 C/Q window length
MODEL_HISTORY = Layer2 P/V feature-history length (90D)
L2_TRAIN_W    = Layer2 rolling training lookback (30D)
RETRAIN_DAYS  = model refresh cadence (currently 15D candidate)
h             = Layer2 future-return target horizon (experimental)
path horizon  = deterministic Strategy maximum path horizon (60D)
```

Legacy `memory=150` meant “retain the most recent 150 eligible samples.” It was a fixed sample-count memory, not 150 days, and is not the current approved Layer2 training-memory baseline.

---

# 1. Fixed Strategy

## 1.1 Raw legal Entry

A raw legal Entry exists when:

```text
close > MA5 > MA10 > MA20
```

All satisfying sessions are collected first.

## 1.2 3-session forward-anchor cleaning

For sorted same-type raw legal points, use the earliest unconsumed point as anchor and absorb only same-type points satisfying:

```text
pi - p0 <= 3 trading sessions
```

Absorbed points do not extend the group transitively. The same cleaning concept is applied independently to Entry, 5D Exit, and 10D Exit events.

## 1.3 Deterministic path

Each cleaned legal Entry has exactly one deterministic path:

1. Initial Entry deploys 1/3 of original campaign capital.
2. Find the most recent retrospective 5D or 10D local minimum before Entry.
3. Define `D_b = Entry price - base-minimum price`, requiring `D_b > 0`.
4. Addon candidates are later retrospective 5D/10D local maxima.
5. The first chronological candidate satisfying `candidate price - last actual buy price > D_b` becomes the next Addon.
6. Reuse the same Entry-time `D_b` for every Addon.
7. Maximum deployment is Entry + Addon1 + Addon2; each uses 1/3 of original campaign capital.
8. First cleaned 5D Exit sells 40% of then-current shares; this partial exit happens at most once.
9. A 5D partial Exit does not disable later Addons.
10. Cleaned 10D Exit liquidates all remaining shares and terminates the campaign.
11. Same-session priority: `10D Exit > 5D partial Exit > Addon`.
12. Maximum path horizon is 60 trading sessions; remaining shares are liquidated at horizon close.

For Entry `e`:

```text
R(e) = realized return of its unique deterministic Strategy path
```

---

# 2. Retrospective extrema semantics

The 5D/10D local minima/maxima are retrospective historical outcome definitions used to construct deterministic Strategy paths.

They are not Layer2 input indicators.

Do not add:

```text
final_exit + 10D availability shift
cutoff-specific extrema reconstruction
extrema confirmation embargo
```

The earlier assistant-added `+10D` confirmation rule is explicitly rejected.

---

# 3. Revised Layer1 W membership — CURRENT APPROVED RULE

This is the major definition change that invalidates older Entry-cohort Layer1 results.

For a Layer1 window:

```text
W = [start, end]
```

a Strategy path is legal for that W only when the entire path is contained inside W:

```text
start <= entry_index <= final_exit_index <= end
```

Therefore:

```text
Entry inside W but final Exit after W  -> exclude
Exit inside W but Entry before W       -> exclude
unfinished path                        -> exclude
```

Under the current rule, entry-side and exit-side calculations use the same complete-path population unless a future approved definition changes this.

The old rule “Entry inside W is sufficient even if Exit occurs later” is obsolete for the current research branch.

---

# 4. U / B / C / Q definitions

For the legal complete-path set in W:

```text
I_W = { e : start <= entry(e) <= final_exit(e) <= end }
```

Define:

```text
U_W = max_{e in I_W} R(e)
B_W = formal periodic baseline return over the same W
C_W = U_W - B_W
```

Per Entry/path:

```text
Q(e) = U_W - R(e)
```

Current W-level Q:

```text
Q_W = mean_e Q(e)
```

Thus:

```text
Q >= 0
Q = 0 means the path attains U
smaller Q means closer to the best legal path in W
```

A W with no legal complete path has no formal U/C/Q label. Do not invent `C=0`, `Q=0`, or Neutral solely because the window is unlabeled.

---

# 5. Layer1 H/N/L scope

The active Layer2 research scope is H-only. L-region research is currently abandoned.

High remains a retrospective Layer1 opportunity/timing state; it must not be interpreted directly as future bullish direction.

Any change to exact H/N/L thresholds or reference windows requires explicit approval.

---

# 6. Layer2 input and training-memory definition

Layer2 receives only normalized price and volume.

Per sample:

```text
MODEL_HISTORY = 90 trading sessions
price channel  = log(close) - log(last close in the 90D input)
volume channel = within-input z-score of log(volume)
input shape     = 2 x 90
```

Layer2 must not receive retrospective extrema, future Exit, future path return, future C/Q, or any other future-derived Strategy outcome as input features.

At an OOS/retraining date `t`, current approved Layer2 training candidates come from the immediately preceding 30 trading sessions:

```text
t - 30 <= sample_cutoff < t
```

This is a 30-session time lookback, not a fixed count of 30 or 150 samples.

The exact target-maturity / purge / embargo rule is still a separate research boundary and is not approved merely because a conventional causal implementation would use one. Do not silently add `sample_cutoff + h < OOS_start` or related rules without explicit discussion.

Before model training, Layer1 / U/C/Q structural analysis should remain torch-free. PyTorch is introduced only when actual model training starts.

---

# 7. Rebuilt W30 structure audit — VERIFIED

Workflow:

```text
Strategy 1 W30 Structure Audit
run: 33936283146
commit: dc69088f0c3c15c977a7fa5ba2345b2834d6db8c
conclusion: success
```

Configuration:

```text
TSLA
8Y
W = 30
candidate retrain cadence = 15D
candidate Layer2 training lookback = 30D
```

Support:

```text
rows = 2010
Strategy paths = 171
valid complete-path W30 windows = 1273
mean paths/window = 2.695
median paths/window = 3
min = 1
max = 7
```

Distributions:

```text
U mean = 0.005086, std = 0.030654, p10 = -0.023230, p50 = -0.002453, p90 = 0.045119
C mean = -0.047584, std = 0.142922, p10 = -0.236750, p50 = -0.036460, p90 = 0.110297
Q mean = 0.013105, std = 0.018370, p10 = 0.000000, p50 = 0.008263, p90 = 0.041105
```

## 7.1 Same-window U/C/Q correlation

All valid W30 windows:

| Pair | Pearson | Spearman |
|---|---:|---:|
| U vs C | -0.146 | -0.196 |
| U vs Q | 0.932 | 0.846 |
| C vs Q | -0.153 | -0.178 |

Interpretation:

- Across all W30 windows, U and Q are highly coupled.
- This is structurally plausible because `Q_W = mean(U_W - R_i)`.
- C is comparatively weakly related to U and Q.
- Do not treat U and Q as independent information dimensions globally without checking redundancy.

## 7.2 H-only same-window relation

Current classifier produced:

```text
High = 166
Neutral = 429
Low = 150
```

Within High only:

| Pair | Pearson | Spearman |
|---|---:|---:|
| U vs C | 0.342 | 0.291 |
| U vs Q | 0.139 | 0.167 |
| C vs Q | -0.283 | -0.144 |

Important observation:

The global U-Q coupling collapses substantially inside H. Because Layer2 is currently H-only, H-specific structure must be audited separately from all-window structure.

---

# 8. Temporal structure: 15D vs 30D

## 8.1 15D lag

W30 windows separated by 15 sessions still overlap by 15 sessions.

Self-correlation, Spearman:

```text
U_t vs U_t+15 = 0.144
C_t vs C_t+15 = 0.317
Q_t vs Q_t+15 = 0.137
```

C shows the clearest persistence at 15D. U and Q self-persistence are weak.

Strong 15D cross-lag relations:

```text
C_t -> U_t+15 : Pearson -0.641, Spearman -0.548
C_t -> Q_t+15 : Pearson -0.676, Spearman -0.633
```

This suggests a possible local reversion / phase-transition structure rather than simple persistence and deserves a dedicated H-only audit.

## 8.2 30D lag

W30 windows separated by 30 sessions have zero overlap.

Self-correlation, Spearman:

```text
U_t vs U_t+30 = -0.151
C_t vs C_t+30 = 0.004
Q_t vs Q_t+30 = -0.137
```

The W30 U/C/Q structure largely disappears at 30D once the windows no longer overlap.

Supported inference:

```text
W30 U/C/Q structure is predominantly local rather than persistent over a full non-overlapping 30D interval.
```

This gives descriptive support for testing a 15D retrain cadence.

It does **not** yet prove that a 30D Layer2 training lookback is optimal. The 30D lookback remains a working definition that should be validated separately.

---

# 9. Status of older Layer2 model results

Older Layer2 results generated under the previous Entry-cohort Layer1 membership, legacy fixed sample-count memory, unreviewed target boundaries, or other superseded assumptions are historical observations only.

Examples previously observed before the definition rebuild include strong horizon/W Spearman values such as:

```text
W30 / h30  ~ 0.635
W45 / h45  ~ 0.570
W60 / h45  ~ 0.631
```

These values must not be treated as current validated predictive evidence until rerun with the current complete-path Layer1 rule and approved Layer2 definitions.

Likewise, older `memory=150`, 5Y rolling-history, or prior weighted H/N/L CNN results are not the present baseline unless explicitly reintroduced as controlled experiments.

---

# 10. Current supported conclusions

1. The complete-path Layer1 membership rule is now the approved definition.
2. The assistant-added `final_exit + 10D` causal availability rule is rejected.
3. The Strategy retains retrospective 5D/10D extrema semantics for historical outcome construction.
4. Current Layer2 feature input remains 90D normalized price/volume only.
5. Current Layer2 training-memory definition is a 30-session time lookback, not `memory=150 samples`.
6. Before training, structural analysis should be performed without PyTorch.
7. Under rebuilt W30 labels, global U and Q are highly redundant, but that redundancy is much weaker inside H.
8. C has the strongest 15D persistence among U/C/Q.
9. At 30D non-overlapping lag, U/C/Q persistence is approximately absent.
10. A 15D retrain cadence is therefore reasonable to continue testing, but is not yet declared globally optimal.
11. A 30D Layer2 training lookback has not yet been validated as optimal.
12. Old Layer2 predictive scores must be rerun before being used as evidence.

---

# 11. Immediate next step

Before broad Layer2 training or parameter sweep:

1. Run a dedicated H-only W30 temporal structure audit.
2. Re-check 15D and 30D U/C/Q self- and cross-lag relations specifically inside H.
3. Confirm the exact Layer2 target definition / target boundary before training.
4. Then run one minimal Layer2 model configuration first using:

```text
W = 30
MODEL_HISTORY = 90D normalized P/V
L2_TRAIN_W = preceding 30 trading sessions
RETRAIN_DAYS = 15D
Layer2 scope = H-only
```

Only after that minimal run is validated should broader W / horizon / training-lookback / retrain-cadence sweeps resume.

---

# 12. Key current commits

```text
f0ea837b75dfae9f89afb96f9f823dfe457e640a
  Lock Strategy/Layer1/Layer2 research registry

793d264e8fd6c78b38581d5ae16ae9a68f6a1267
  Fix W-level Q to mean(U - R)

0c596e1f0e4e4b8ae6d211eafaf6a3d9ef74a9e4
  Add W30 C/Q/U structure audit

2c552d604fbef30ac4b7d5955e2675f012df53b3
  Add W30 structure audit workflow

0abf88bfbbd4027a851f17abf26f46d0682520e6
  Add numba dependency for structural audit

dc69088f0c3c15c977a7fa5ba2345b2834d6db8c
  Keep pretraining Layer1 pipeline torch-free
```

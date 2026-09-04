# FutureView Strategy 1 — Current Research Handoff

Last rewritten: 2026-09-04

Branch: `strategy-profitability-restart`

This document is the current authoritative research handoff. It intentionally replaces the previous chronological accumulation of experiments with a compact statement of the **current definitions, current implementation, verified results, supported inferences, unsupported inferences, and open decisions**. Older experiments remain useful only as historical context when they do not conflict with this document.

---

# 0. Current research direction

The Strategy is fixed. The present objective is not to optimize Entry, Addon, Exit, capital allocation, or invent a new Strategy.

The current question is:

> Given only historical price and volume available before a future trader-defined interval W, can a causal model estimate the Strategy-opportunity quantities C and Q of that next W, and can the historical H/N/L structure be used as training importance rather than as a trading decision by itself?

The working configuration is:

```text
Ticker: TSLA
Raw history downloaded: 8 years
Trading interval W: 30 trading sessions
Layer2 model history: 90 trading sessions
Training history at retrain: prior 5 years
Final validation period: final 1 year
Fresh retrain frequency: every 15 trading sessions
Epochs per retrain: 300
Layer1 weights: High=1.0, Neutral=0.2, Low=1.0
No-formal-label W: weight=0.0
Model: current small 1D CNN
```

The current research pipeline is:

```text
raw daily market data
→ raw legal Strategy events
→ 3-session forward-anchor event cleaning
→ cleaned legal Entries / Exits
→ deterministic Strategy path for every cleaned Entry
→ realized path return R(e)
→ rolling W30 opportunity regions
→ U / B / C / Q
→ H / N / L / unlabeled + importance weight
→ causal 90-session price/volume input
→ Layer2 CNN
→ predicted C / predicted Q / P(H,N,L)
→ 5Y rolling training, fresh retrain every 15 sessions
→ final-year out-of-sample evaluation
```

All changes to data definitions, label construction, weighting, model architecture, loss, retraining, or evaluation must be discussed and explicitly approved before implementation.

---

# 1. Fixed Strategy and formal data definitions

## 1.1 Raw legal Entry

A raw legal Entry exists when:

```text
close > MA5 > MA10 > MA20
```

All satisfying sessions are collected first. No merging occurs during the raw scan.

## 1.2 Legal-point cleaning

After the complete raw scan, same-type legal points are cleaned using the 3-session forward-anchor rule.

For sorted raw points:

```text
p0 < p1 < p2 < ...
```

Use the earliest unconsumed point as anchor and absorb only same-type points satisfying:

```text
pi - p0 <= 3 trading sessions
```

Absorbed points cannot extend the group transitively.

Example:

```text
raw:     100, 103, 106, 107
cleaned: 100, 106
```

5-day and 10-day Exit events are cleaned independently.

## 1.3 Deterministic Strategy path

Each cleaned legal Entry has exactly one deterministic path:

1. Initial Entry deploys 1/3 of original campaign capital.
2. Find the most recent retrospective 5- or 10-session local minimum before Entry.
3. Define `D_b = Entry price - base-minimum price`, requiring `D_b > 0`.
4. Later retrospective 5/10 local maxima are Addon candidates.
5. A candidate is accepted when `candidate price - last buy price > original D_b`.
6. Reuse the same original `D_b` for every Addon.
7. Maximum deployment is Entry + Addon1 + Addon2.
8. Every deployment uses exactly 1/3 of the original campaign denominator.
9. First cleaned 5-day Exit after Entry sells 40% of then-current shares.
10. The 5-day partial Exit happens at most once and does not disable later Addons.
11. Cleaned 10-day Exit liquidates all remaining shares and terminates the campaign.
12. Same-day priority: `10-day Exit > 5-day partial Exit > Addon`.
13. Maximum path horizon is 60 sessions.
14. Remaining shares at horizon are liquidated at horizon close.
15. There is no 3-day re-entry cooldown in this formal deterministic path.

For Entry `e`:

```text
R(e) = realized return of its unique deterministic Strategy path
```

---

# 2. W, U, B, C, and Q

## 2.1 W is an Entry-cohort opportunity interval

For a trader-defined W:

```text
I_W = {cleaned legal Entries whose initial Entry lies inside W}
```

W membership is determined only by the initial Entry. Addons and Exit may occur after W. The full deterministic path still defines `R(e)`.

Therefore:

```text
W is NOT a holding-period cutoff.
W is the trading opportunity interval chosen by the trader.
```

Current W:

```text
W = 30 trading sessions
stride = 1 session
```

## 2.2 U

```text
U_W = max_{e in I_W} R(e)
```

U is the best realized return among legal fixed-Strategy Entries in that W. It is not an optimized Strategy.

## 2.3 B and C

Let `B_W` be the periodic baseline return over the same W.

```text
C_W = U_W - B_W
```

Interpretation:

```text
C > 0 → W contains a legal Strategy opportunity that outperformed periodic B
C < 0 → even the best legal Entry in W underperformed periodic B
```

C is a region opportunity-quality measure, not a trend-direction score and not the return of the current Entry.

## 2.4 Q

For Entry `e` in W:

```text
Q(e) = U_W - R(e)
```

Therefore:

```text
Q >= 0
Q = 0 means the Entry attains U
smaller Q means closer to the best Entry in the region
larger Q means farther below the best Entry
```

Current W-level Q used downstream is the mean per-Entry Q within W.

Desired semantic combination:

```text
large C + small Q
```

means favorable regional Strategy opportunity plus good Entry timing relative to the best legal Entry in that W.

---

# 3. Layer1 state and training importance

Layer1 is a retrospective importance/filtering layer. It is not the final trading decision and should not itself be interpreted as future direction.

## 3.1 H/N/L definition

Short trailing reference uses 90 sessions:

```text
C90_40, C90_60
Q90_40, Q90_60
```

Short High:

```text
C >= C90_60 and Q <= Q90_60
```

Short Low:

```text
C <= C90_40 and Q >= Q90_40
```

Long trailing reference uses 756 sessions:

```text
C3Y_50, Q3Y_50
```

Long High:

```text
C > C3Y_50 and Q < Q3Y_50
```

Long Low:

```text
C < C3Y_50 and Q > Q3Y_50
```

Final labeled state:

```text
High    = ShortHigh AND LongHigh
Low     = ShortLow  AND LongLow
Neutral = otherwise among formally labeled W
```

High does not mean future bullish. Low does not mean future bearish.

## 3.2 Current weights

```text
High      = 1.0
Neutral   = 0.2
Low       = 1.0
Unlabeled = 0.0
```

Neutral is intentionally down-weighted rather than removed because Neutral periods may contain transition information useful to the longer Layer2 history.

## 3.3 W with no legal Entry

If a W contains no cleaned legal Entry, then U, C, and Q are not formally defined.

Current locked semantic rule:

```text
Do not invent C=0.
Do not invent Q=0.
Do not relabel it Neutral.
Keep the W on the chronological timeline.
Assign supervised weight = 0.
```

This `unlabeled → weight 0` rule is conceptually locked but **has not yet been fully implemented in the current Layer2 training/evaluation dataset code**. The latest formal rolling result therefore still evaluates only W with formal realized labels.

---

# 4. Rolling historical preparation

Historical path information should be prepared once and reused as much as possible.

At a rolling cutoff date D, there is one special rule:

```text
if path final Exit <= D:
    reuse the already prepared completed path and return

if path final Exit > D:
    preserve all Entry / Addon / partial-Exit actions that occurred through D
    force-close all remaining shares at D close
    recompute only the affected path return as of D
```

There are no approved extra rolling rules such as embargoes, overlap exclusion, cutoff-specific extrema reconstruction, additional Entry filtering, or assistant-added confirmation delays.

The prior 5 years are the model's rolling training-history range. They are not a new definition of C/Q.

Verified simplification commits:

```text
48f3214930955059bef9e978c14f3f5825f916dd
  Simplify rolling paths to exit-cutoff rule

e3238c82eb7ac3a1674439a1d1d90bc974115747
  Test rolling exit-cutoff reuse rule
```

---

# 5. Layer2 input and model

For target W beginning at session `t`, Layer2 sees only the preceding 90 sessions:

```text
X_t = sessions [t-90, ..., t-1]
Y_t = C/Q/state of W30 beginning at t
```

Thus input and target do not overlap.

Current input representation:

```text
channel 1 = log(close) - log(last close in the 90-session input)
channel 2 = within-input z-score of log(volume)
input shape = 2 × 90
```

Current network:

```text
Conv1d 2→16, kernel 7, same + GELU
Conv1d 16→24, kernel 5, same + GELU
AdaptiveAvgPool1d(1)
Linear 24→24 + GELU
C/Q regression head: 2 outputs
H/N/L classification head: 3 logits
```

Current loss:

```text
SmoothL1 for C
SmoothL1 for Q
cross entropy for H/N/L
sample-weighted by Layer1 weight
```

Q prediction is constrained nonnegative by the current decoding transform.

Optimizer:

```text
AdamW
learning rate = 0.003
weight decay = 1e-4
```

---

# 6. Epoch convergence diagnostic

Verified workflow:

```text
Strategy 1 Layer 2 Epoch Convergence
run: 33209467520
```

Five approximately evenly spaced final-year dates were tested. Each used the prior 5 years of training history, a fresh model, and up to 300 epochs. No internal validation split or early stopping was added.

Total training loss at epochs 50 / 100 / 200 / 300:

```text
2025-08-27: 1.250 / 0.959 / 0.540 / 0.429
2025-11-14: 1.313 / 0.911 / 0.549 / 0.458
2026-02-05: 1.328 / 0.994 / 0.553 / 0.451
2026-04-27: 1.337 / 0.968 / 0.586 / 0.489
2026-07-17: 1.357 / 1.160 / 0.699 / 0.552
```

Supported conclusion:

```text
50 epochs is clearly too early.
100 epochs is clearly too early.
200 epochs is still improving.
300 epochs is still not a strict training-loss plateau.
```

300 epochs was therefore retained for the first formal rolling experiment. This does not establish 300 as globally optimal and does not justify increasing epochs purely because training loss continues to fall.

---

# 7. Current formal rolling validation

Verified workflow:

```text
Strategy 1 Layer 2 Rolling 8Y
run: 33210088592
job: 98980914136
source commit: ab54f63bfb96bdb435c6cf0ea9ecda9a4670cbc5
```

Configuration:

```text
TSLA
8Y raw data
W30
L90
prior 5Y training history
final 1Y validation
fresh retrain every 15 trading sessions
300 epochs per retrain
High=1.0, Neutral=0.2, Low=1.0
base seed=20260827
```

Tests:

```text
8 passed
```

Support:

```text
raw daily rows = 2010
validation prediction days = 223
fresh retrains = 15
predictions emitted = 223
predictions with formal realized C/Q/state = 127
currently unlabeled evaluation days = 96
```

The 96 unlabeled W are approximately 43% of the 223-day validation timeline and therefore are not a negligible part of the chronology. They are currently absent from formal C/Q accuracy statistics because no formal realized C/Q target exists under the current definition.

---

# 8. Current Layer2 results

## 8.1 Overall C

Across the 127 formally labeled validation W:

```text
actual mean = -0.019885
pred mean   = -0.015988
bias        = +0.003897
MAE         = 0.056574
median AE   = 0.052826
Pearson     = 0.488500
Spearman    = 0.498201
```

Interpretation:

The model shows a meaningful association between historical 90-session price/volume structure and the realized C of the immediately following W30. The current evidence is stronger for **relative ordering** than for absolute calibration.

## 8.2 Overall Q

```text
actual mean = 0.010158
pred mean   = 0.013902
bias        = +0.003745
MAE         = 0.011292
median AE   = 0.008083
Pearson     = 0.238838
Spearman    = 0.238052
```

Interpretation:

Q is substantially less predictable than C under the current model. There is some coarse level information, but relative ordering is weak and unstable.

## 8.3 By actual H/N/L state

```text
High n=35
C actual mean = +4.7847%
C pred mean   = +0.6914%
C Pearson     = 0.413350
C Spearman    = 0.450980
Q actual mean = 0.2423%
Q pred mean   = 1.7208%
Q Pearson     = -0.333084

Neutral n=83
C actual mean = -3.8722%
C pred mean   = -2.2007%
C Pearson     = 0.481201
C Spearman    = 0.509257
Q actual mean = 1.2505%
Q pred mean   = 1.0968%
Q Pearson     = 0.470893
Q Spearman    = 0.555385

Low n=9
C actual mean = -10.9579%
C pred mean   = -4.9543%
C Pearson     = -0.540906
C Spearman    = -0.683333
Q actual mean = 1.8593%
Q pred mean   = 2.8106%
Q Pearson     = -0.657849
Q Spearman    = -0.753660
```

Low support is too small for a stable conclusion.

---

# 9. Time-split observations

## 9.1 2025 labeled validation subset

```text
n = 81
C Pearson  = 0.350587
C Spearman = 0.352258
Q Pearson  = 0.032620
Q Spearman = -0.101246
```

2025 High remained poorly calibrated in magnitude:

```text
High n=28
actual C mean = +4.1269%
pred C mean   = -0.9959%
```

## 9.2 2026 labeled validation subset

```text
n = 46
C Pearson  = 0.763290
C Spearman = 0.748504
Q Pearson  = 0.208561
Q Spearman = 0.187052
```

2026 Neutral also had strong C ordering:

```text
Neutral n=39
C Pearson  = 0.715464
C Spearman = 0.704251
```

2026 High:

```text
n = 7
actual C mean = +7.4163%
pred C mean   = +7.4406%
C MAE         = 0.8955%
C Pearson     = 0.887314
C Spearman    = 0.857143
```

However these seven High W are heavily overlapping stride-1 W30 observations and should not be treated as seven independent market episodes.

---

# 10. Main supported inferences

## 10.1 C contains learnable forward information

The strongest current result is:

```text
historical 90-session price/volume structure contains information associated with the C of the immediately following W30
```

Overall C Pearson/Spearman near 0.49/0.50 and stronger 2026 ordering support this interpretation.

This does **not** yet establish a deployable trading model, but it is evidence that the target is not purely unpredictable noise under the current data construction.

## 10.2 C ranking is better than C magnitude calibration

The model systematically compresses extremes toward zero.

Examples:

```text
High actual mean C = +4.78%, predicted +0.69%
Low  actual mean C = -10.96%, predicted -4.95%
```

Therefore the current CNN is better at relative opportunity ordering than at reproducing the full amplitude of realized C.

## 10.3 Q is not yet learned reliably

The Q signal is much weaker than C. In High regions, average Q level may sometimes be in the correct rough range while within-state ranking can be reversed.

Current interpretation:

```text
C: meaningful learnable signal is present
Q: coarse information may be present, but reliable ordering has not been established
```

## 10.4 H/N/L classification and C/Q regression are not fully aligned

There are periods where C regression is sensible while the H/N/L classification head assigns a different state than the realized Layer1 state.

This suggests the multi-task heads have not yet formed a fully consistent internal representation. It is an observation, not yet a reason to modify the architecture.

## 10.5 2026 improvement cannot be attributed to one cause

The strong 2026 C results cannot currently be interpreted simply as "the model learned more over time."

Potential contributors include:

```text
changing rolling training composition
market-regime differences
fresh-model initialization variance
```

Training sample counts did not monotonically increase, so sample count alone does not explain the improvement.

## 10.6 Fresh retraining can create large prediction discontinuities

A notable example occurred around the 2025-10-10 retrain. Immediately before retrain, several High-region C predictions were positive and directionally sensible; after the fresh retrain, the same continuing High regime received strongly negative predictions.

The current implementation uses a different effective seed at each retrain:

```text
seed = base seed + target_start
```

Therefore some retrain-to-retrain discontinuity may be initialization variance rather than new market information. This is an unresolved interpretation issue, not yet an approved model change.

## 10.7 Unlabeled W are a substantial part of the chronology

96 of 223 final-year prediction days had no formal C/Q label under the current definition.

These W should not be silently treated as if they did not exist, and they should not be assigned artificial C/Q values. The current direction is to preserve them chronologically with supervised weight zero.

---

# 11. What the current results do NOT prove

The present evidence does not prove any of the following:

```text
300 epochs is optimal.
15-session retraining is optimal.
90 sessions is the optimal model history.
W30 is the optimal trading interval.
The model is profitable in live trading.
2026 High performance generalizes to independent future High episodes.
Q is adequately learned.
The H/N/L classification head is necessary or optimally specified.
Fresh retraining is better than warm-start training.
The 2026 improvement is caused by more training data.
```

These must remain open questions unless separately tested.

---

# 12. Current implementation mismatch / pending bookkeeping change

The latest completed rolling run predates full implementation of the newly locked unlabeled rule.

Current desired semantics:

```text
formal High      → weight 1.0
formal Neutral   → weight 0.2
formal Low       → weight 1.0
no formal C/Q    → keep chronology, weight 0.0, no invented target
```

The exact dataset representation of a zero-weight unlabeled W has not yet been finalized. In particular, the project has not yet decided whether such W should exist as complete input samples with a target mask or only as preserved chronological bookkeeping entries.

No implementation change should be made until that representation is explicitly agreed.

---

# 13. Current open questions, in priority order

The project direction is being reconsidered. The next step should be chosen deliberately rather than automatically extending the current CNN experiment.

Open questions include:

1. How exactly should unlabeled, weight-zero W be represented in the Layer2 dataset while preserving chronology and avoiding fake targets?
2. How much of retrain-to-retrain prediction variation comes from fresh random initialization rather than changed training information?
3. Should C and Q remain joint targets, given that C is currently much more learnable than Q?
4. Is the H/N/L classification head helping representation learning, or merely adding an unstable auxiliary objective?
5. Should the model be evaluated primarily as a C-ranking model before attempting more precise C magnitude or Q estimation?
6. Should retraining remain fresh-from-scratch, or should warm-start/continual approaches eventually be tested?
7. How should heavily overlapping stride-1 W30 observations be summarized into more nearly independent market episodes for statistical interpretation?

These are open research questions only. None is an approved implementation step yet.

---

# 14. Current authoritative takeaway

The current research state can be summarized as follows:

> The fixed Strategy and C/Q definitions are now sufficiently stable to support causal Layer2 investigation. In the first formal 5Y-train / final-1Y / 15-session-retrain rolling experiment, a small CNN using only the previous 90 sessions of TSLA price and volume achieved meaningful out-of-sample association with future W30 C, especially in relative ordering. Q was substantially weaker, C magnitude was compressed toward zero, and retrain-to-retrain stability remains unresolved. Approximately 43% of the validation timeline had no formal C/Q label; these intervals are now conceptually retained with zero supervised weight rather than deleted or mislabeled. The next research direction should be selected from these findings rather than assumed from the existing pipeline.

This document should be updated whenever a definition or conclusion is explicitly changed.
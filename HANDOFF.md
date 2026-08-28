# FutureView Strategy 1 — Full Research Handoff

Last consolidated: 2026-08-28

Branch: `strategy-profitability-restart`

This document is the current authoritative research-state handoff. It distinguishes locked definitions, validated observations, invalidated historical experiments, and open questions. When older notes conflict with this handoff, use this document together with the current branch code.

---

# 0. Current objective

The Strategy itself is fixed. This project is not currently optimizing Entry, Addon, Exit, capital allocation, or the Strategy rules.

The current Layer2 question is deliberately narrow:

> Given only causal historical price/volume information available before a target interval, can a model predict the C and Q of the immediately following trader-defined W interval, and optionally its retrospective H/N/L state?

Current primary configuration:

```text
Ticker: TSLA
W_trade: 30 sessions
Layer2 history L_model: 90 sessions
Layer1 weights: High=1.0, Neutral=0.2, Low=1.0
Unlabeled W weight: 0.0
Layer2 model: current small 1D CNN
Training history at each retrain: prior 5 years
Validation: final 1 year
Fresh retrain: every 15 trading sessions
Epochs per retrain: 300
Seed base: 20260827
```

The research pipeline is now:

```text
raw daily price/volume
→ raw Strategy signals/events
→ raw legal Entry / Exit points
→ 3-session forward-anchor preprocessing
→ cleaned legal Entry / Exit points
→ deterministic Strategy path per cleaned Entry
→ realized path return R(e)
→ rolling trader-defined W
→ U / periodic B / C / Q
→ Layer1 H/N/L state + sample importance weight
→ causal 90-session price/volume input
→ immediately following W30 target
→ Layer2 C/Q regression + H/N/L classification
→ 5Y rolling training / 15-session fresh retrain
→ final-year out-of-sample predictions
```

All substantive changes to data rules, filtering, weighting, model architecture, loss, training, or evaluation require explicit discussion and confirmation before implementation.

---

# 1. Legal Entry rule — LOCKED

Raw legal Entry:

```text
close > MA5
close > MA10
close > MA20
MA5 > MA10
MA10 > MA20
```

Equivalent:

```text
close > MA5 > MA10 > MA20
```

Every satisfying trading session is first recorded in the raw legal Entry set. No merging occurs during the scan.

---

# 2. Legal Entry / Exit preprocessing — LOCKED

Preprocessing occurs after the complete raw scan and before Strategy paths/CQ/model construction.

For sorted same-type raw legal points:

```text
p0 < p1 < p2 < ...
```

Use the earliest unconsumed point `p0` as anchor and absorb same-type points satisfying:

```text
pi - p0 <= 3 trading sessions
```

Absorbed points are consumed and cannot extend the group transitively. The next unconsumed point becomes the next anchor.

Therefore this is:

```text
forward-only anchor merging
not ±3
not transitive clustering
not scan-and-merge simultaneously
```

Example:

```text
raw:     100, 103, 106, 107
cleaned: 100, 106
```

5-day and 10-day Exit events are cleaned independently using the same forward-anchor concept.

Implementation:

```text
src/futureview/strategy1_deterministic_paths.py
MERGE_GAP = 3
```

---

# 3. Fixed deterministic Strategy path — LOCKED

For each cleaned legal Entry there is exactly one deterministic path.

1. Initial Entry deploys 1/3 of original campaign capital.
2. Find most recent retrospective local minimum before Entry from union of 5-session and 10-session minima.
3. Define `D_b = Entry price - base-min price`, requiring `D_b > 0`.
4. Addon candidates are later retrospective local maxima from union of 5-session and 10-session maxima.
5. First chronological candidate satisfying `candidate_price - last_buy_price > D_b` becomes the next Addon.
6. Reuse the original `D_b` for every Addon.
7. Maximum deployment is Entry + Addon1 + Addon2.
8. Every deployment uses exactly 1/3 of the original denominator.
9. First cleaned legal 5-day Exit sells 40% of then-current shares.
10. 5-day partial Exit occurs at most once and does not disable later Addons.
11. Cleaned legal 10-day Exit liquidates all remainder and terminates the campaign.
12. Same-day priority: `10-day Exit > 5-day partial Exit > Addon`.
13. Maximum path horizon = 60 sessions.
14. Remaining shares at horizon close are liquidated.
15. No 3-day re-entry cooldown in the locked deterministic C/Q path.

Do not substitute the broader legacy behavior from `strategy1.py`.

---

# 4. Path outcome and W membership — LOCKED

For cleaned legal Entry `e`:

```text
R(e) = realized return of its unique deterministic Strategy path
```

For trader-defined interval W:

```text
I_W = {cleaned legal Entries whose initial Entry lies inside W}
U_W = max_{e in I_W} R(e)
```

Membership is determined only by the initial Entry. Addons and Exit may occur after W; the full deterministic path still defines `R(e)`.

Therefore:

```text
W is an Entry-cohort / opportunity-evaluation interval.
W is not a holding-period cutoff.
```

---

# 5. Periodic baseline B and C — LOCKED

Keep the formal periodic baseline:

```text
C_W = U_W - B_W
```

where `B_W` is the periodic baseline return in the same W region.

Interpretation:

```text
C > 0 : the W contains a legal fixed-Strategy opportunity outperforming B
C < 0 : even the best legal Entry in W underperformed B
```

C measures regional Strategy-opportunity quality. It is not current Entry return and not a trend-direction score.

The formal `B_W` is unrelated to previously rejected assistant-added model-evaluation baselines. Do not remove `B_W`.

---

# 6. Q — LOCKED

Per Entry:

```text
Q(e) = U_W - R(e)
```

with:

```text
Q >= 0
Q = 0 means the Entry attains U_W
smaller Q means timing/outcome closer to the best legal Entry in W
```

Q is Entry-quality / timing-distance, not direction or trend strength.

Current scalar W-level Q used by the existing Layer1/Layer2 pipeline is the mean of per-Entry Q values inside W.

Do not exclude valid `Q=0` observations.

---

# 7. W with no legal Entry / no formal C-Q label — LOCKED 2026-08-28

A W that contains no cleaned legal Entry has no formal `U_W`, C, or Q target under the current definitions.

Such a W must remain on the chronological time axis, but its supervised training importance is:

```text
weight = 0.0
```

Important semantic rule:

```text
Do NOT invent C=0.
Do NOT invent Q=0.
Do NOT relabel it Neutral.
```

It is an unlabeled temporal W with zero supervised weight.

Conceptually:

```text
legal labeled High W    → weight 1.0
legal labeled Neutral W → weight 0.2
legal labeled Low W     → weight 1.0
no-formal-label W       → weight 0.0
```

A weight-zero W may remain in chronological/sample bookkeeping and inference continuity, but it contributes zero gradient to C regression, Q regression, and H/N/L classification.

This rule has been conceptually locked but has not yet been implemented into the current training dataset code as of this consolidation. The current completed rolling run still reports only W with formal labels in its evaluation statistics.

---

# 8. Layer1 H/N/L reference structure — LOCKED

Reference W is currently W30 with stride 1.

Short trailing reference: 90 sessions:

```text
C90_40, C90_60
Q90_40, Q90_60
```

Short-high:

```text
C >= C90_60 and Q <= Q90_60
```

Short-low:

```text
C <= C90_40 and Q >= Q90_40
```

Long trailing reference: 756 sessions:

```text
C3Y_50, Q3Y_50
```

Long-high:

```text
C > C3Y_50 and Q < Q3Y_50
```

Long-low:

```text
C < C3Y_50 and Q > Q3Y_50
```

Final state:

```text
High    = ShortHigh AND LongHigh
Low     = ShortLow  AND LongLow
Neutral = otherwise, among formally labeled W
```

An unlabeled W is not Neutral.

Layer1 semantics:

```text
High    = retrospectively high Strategy opportunity + relatively good timing
Low     = retrospectively low Strategy opportunity + relatively poor timing
Neutral = intermediate / non-extreme labeled state
```

High does not mean future bullish; Low does not mean future bearish.

---

# 9. Layer1 training importance — LOCKED CURRENT VALUES

Current supervised weights are:

```text
High      = 1.0
Neutral   = 0.2
Low       = 1.0
Unlabeled = 0.0
```

Neutral is intentionally down-weighted rather than removed because Neutral regions can be part of a meaningful temporal transition trajectory. Neutral prediction error is therefore not the primary success/failure criterion.

The zero-weight unlabeled case is different: it has no formal C/Q/HNL target and must not contribute supervised loss.

---

# 10. Trader-defined W versus model history — LOCKED

Keep separate:

```text
W_trade = trader-defined opportunity interval
Layer1  = retrospective C/Q importance/state map
L_model = causal price/volume history supplied to Layer2
```

Current configuration:

```text
W_trade = 30 sessions
L_model = 90 sessions
```

For prediction date/target start `t`:

```text
X_t = price/volume sessions [t-90, ..., t-1]
Y_t = C/Q/state of immediately following W30 starting at t
```

There is no input-target overlap.

---

# 11. Layer2 input representation and model — CURRENT

Input uses only price and volume.

For each 90-session causal input:

```text
price channel  = log(close) - log(last close in input)
volume channel = within-input z-score of log(volume)
```

Input shape:

```text
2 × 90
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

Training objective uses sample-weighted:

```text
C regression SmoothL1
Q regression SmoothL1
H/N/L cross entropy
```

Current Q decoding enforces non-negativity using the squared raw-Q transform.

Current learning parameters:

```text
AdamW
LR = 0.003
weight_decay = 1e-4
epochs = 300 in formal rolling run
```

---

# 12. Rolling historical preparation — LOCKED SIMPLE RULE

Historical deterministic paths should be reusable. Do not rebuild historical definitions unnecessarily at every rolling cutoff.

At rolling cutoff D, the one special path rule is:

```text
if path Exit <= D:
    reuse completed full path/outcome

if path Exit > D:
    preserve all path actions already occurring through D
    force-close all remaining shares at D close
    recompute affected path return as of D
```

No additional special rolling rules are approved:

```text
no embargo
no overlap exclusion
no cutoff-specific extrema reconstruction
no new legal-point rescan rule
no assistant-added causal confirmation delay
```

The 5-year period is the model training-history window. It does not redefine the formal historical C/Q concept.

Implementation:

```text
src/futureview/strategy1_deterministic_paths_asof.py
```

Relevant verified simplification commits:

```text
48f3214930955059bef9e978c14f3f5825f916dd
  Simplify rolling paths to exit-cutoff rule

e3238c82eb7ac3a1674439a1d1d90bc974115747
  Test rolling exit-cutoff reuse rule
```

---

# 13. Epoch convergence diagnostic — VERIFIED

Workflow:

```text
Strategy 1 Layer 2 Epoch Convergence
run: 33209467520
source workflow commit: 64793ca64b3348d5a84dba5b64a3c175fa20b8d9
```

Design:

```text
final-year period
5 approximately evenly spaced dates
prior 5 years training history per date
fresh model
max 300 epochs
training loss only
no internal validation split
no early stopping
```

Total loss at epochs 50 / 100 / 200 / 300:

```text
2025-08-27: 1.250 / 0.959 / 0.540 / 0.429
2025-11-14: 1.313 / 0.911 / 0.549 / 0.458
2026-02-05: 1.328 / 0.994 / 0.553 / 0.451
2026-04-27: 1.337 / 0.968 / 0.586 / 0.489
2026-07-17: 1.357 / 1.160 / 0.699 / 0.552
```

Validated observation:

```text
50 epochs clearly insufficient
100 epochs clearly insufficient
200 epochs still improving
300 epochs still not a strict training-loss plateau
```

300 was therefore selected as the fixed epoch count for the first formal rolling run. This does not establish that 300 is globally optimal.

---

# 14. Formal rolling Layer2 validation — VERIFIED CURRENT RESULT

Workflow:

```text
Strategy 1 Layer 2 Rolling 8Y
run: 33210088592
job: 98980914136
source commit: ab54f63bfb96bdb435c6cf0ea9ecda9a4670cbc5
```

Configuration:

```text
TSLA
raw period downloaded: 8y
W30
L90
prior 5y training history
final 1y validation
fresh retrain every 15 trading sessions
300 epochs per retrain
High=1, Neutral=.2, Low=1
base seed 20260827
```

Unit tests:

```text
8 passed
```

Rolling support:

```text
raw rows = 2010
validation prediction days = 223
fresh retrains = 15
predictions emitted = 223
predictions with formal realized C/Q/state = 127
currently unlabeled in evaluation output = 96
```

The current code's reported statistics use only the 127 formally labeled W. The newly locked zero-weight unlabeled handling has not yet been implemented into training/evaluation bookkeeping.

Overall formal-label results:

```text
C:
actual mean   = -0.019885
pred mean     = -0.015988
bias          = +0.003897
MAE           = 0.056574
median AE     = 0.052826
Pearson       = 0.488500
Spearman      = 0.498201

Q:
actual mean   = 0.010158
pred mean     = 0.013902
bias          = +0.003745
MAE           = 0.011292
median AE     = 0.008083
Pearson       = 0.238838
Spearman      = 0.238052
```

By actual Layer1 state:

```text
High n=35
C actual +4.7847%, pred +0.6914%, Pearson 0.413350, Spearman 0.450980
Q actual 0.2423%, pred 1.7208%, Pearson -0.333084

Neutral n=83
C actual -3.8722%, pred -2.2007%, Pearson 0.481201, Spearman 0.509257
Q actual 1.2505%, pred 1.0968%, Pearson 0.470893, Spearman 0.555385

Low n=9
C actual -10.9579%, pred -4.9543%, Pearson -0.540906
Q actual 1.8593%, pred 2.8106%, Pearson -0.657849
```

The Low population is too small for a stable conclusion.

Year split:

```text
2025 labeled n=81
C Pearson 0.350587
C Spearman 0.352258
Q Pearson 0.032620

2026 labeled n=46
C Pearson 0.763290
C Spearman 0.748504
Q Pearson 0.208561
```

2026 High subset, n=7:

```text
C actual mean = +7.4163%
C pred mean   = +7.4406%
C MAE         = 0.8955 percentage points
C Pearson     = 0.887314
C Spearman    = 0.857143

Q actual mean = 0.5005%
Q pred mean   = 0.2917%
Q Pearson     = -0.958460
```

Because W30 uses stride 1, nearby labeled samples are strongly overlapping. Counts such as n=7 are not seven independent market experiments.

---

# 15. Current interpretation of the formal rolling result — VALIDATED OBSERVATION

The current evidence supports a cautious statement:

> Under the present causal W30/L90 setup, the Layer2 model shows evidence of learning information related to the immediately following W30 C among formally labeled windows. C relative ordering is substantially more promising than Q. Q prediction remains weak/unstable, especially within High regions.

Important nuances:

1. C shows moderate overall forward association (`Pearson≈0.49`, `Spearman≈0.50`).
2. 2026 C association is much stronger than 2025, but this does not by itself prove progressive learning.
3. High C level is still substantially underestimated overall.
4. Q level sometimes looks reasonable while within-state ordering is wrong.
5. Neutral is down-weighted by design, so Neutral error is not the main success/failure criterion.
6. Low has too few observations for stable inference.
7. Stride-1 W30 produces heavy temporal overlap, so raw sample counts overstate independent support.

---

# 16. Important retrain-instability observation — CURRENT OPEN ISSUE

Inspection of the full rolling CSV found that predictions can change sharply at a fresh retrain boundary even while the realized market regime remains similar.

Example around October 2025:

```text
before retrain:
2025-10-07 actual C +8.18%, pred +5.37%
2025-10-08 actual C +8.41%, pred +0.49%
2025-10-09 actual C +8.48%, pred +0.63%

after fresh retrain:
2025-10-10 actual C +8.47%, pred -5.32%
2025-10-13 actual C +8.91%, pred -10.51%
2025-10-14 actual C +4.72%, pred -7.68%
2025-10-15 actual C +4.94%, pred -11.80%
```

Current code seeds each fresh retrain using:

```text
SEED + target_start
```

Therefore the formal rolling sequence combines:

```text
changing 5Y training composition
changing market regime
changing model initialization seed
```

This is an identified issue for interpretation only. No seed-variance experiment has yet been approved or run.

---

# 17. Invalid / superseded rolling attempts — DO NOT USE AS EVIDENCE

Do not use these as current evidence:

```text
commit 33b606462422a3634a449e0aab65ec8e7d38f30f
run 33203785150
```

It included unapproved overlap exclusions and 50 epochs.

Also superseded:

```text
commit ea3f6ad19af9d72896757e695b2f394967dddc2f
```

It used an overcomplicated interpretation of the 5-year historical window.

---

# 18. Earlier 10Y / final-1Y single-holdout result — HISTORICAL COMPARISON ONLY

Workflow run:

```text
33201541569
```

This earlier one-time holdout showed weak generalization, especially for High:

```text
C overall Pearson ≈ 0.141
Q overall Pearson ≈ 0.109
High actual C ≈ +4.13%
High predicted C ≈ -3.81%
```

The later rolling validation is the current primary evaluation because it follows the approved 5Y rolling / final-1Y / retrain-15 design.

---

# 19. Current data-to-model bookkeeping — AUTHORITATIVE MAP

For a target W starting on trading session `t`:

```text
A. Market data
   raw OHLCV daily rows

B. Legal-event data
   raw Entry/Exit detections
   → forward-anchor cleaned Entry/Exit points

C. Strategy-path data
   each cleaned Entry e
   → deterministic actions
   → realized R(e)

D. W-level retrospective opportunity data
   W = [t, ..., t+29]
   I_W = cleaned Entries whose initial Entry lies in W

   if I_W is nonempty:
       U_W = max R(e)
       B_W = periodic baseline in W
       C_W = U_W - B_W
       Q_W = current scalar aggregation of U_W - R(e)
       Layer1 state = High / Neutral / Low
       sample weight = 1.0 / 0.2 / 1.0

   if I_W is empty:
       C/Q/state are formally unlabeled
       sample weight = 0.0
       do not fabricate C/Q/Neutral

E. Layer2 causal input
   preceding 90 sessions only:
   [t-90, ..., t-1]
   channels = normalized close + normalized volume

F. Layer2 target
   immediately following W30 at t:
   C_W, Q_W, H/N/L if formally labeled

G. Training
   at retrain cutoff D:
   historical training information from prior 5 years
   paths ending after D are force-closed at D close only
   fresh CNN
   300 epochs
   weighted loss

H. Inference
   trained model frozen for next 15 trading sessions
   every day receives its own latest 90-session input
   no weight update until next retrain

I. Final output per prediction day
   pred_C
   pred_Q
   P_H / P_N / P_L
   pred_state
   plus actual_C / actual_Q / actual_state when retrospective label later exists
```

---

# 20. What is established versus not established

Established:

```text
- formal cleaned Entry/Exit preprocessing definition
- deterministic Strategy path definition
- W membership rule
- periodic B and C definition
- Q definition
- Layer1 H/N/L reference definition
- weights H=1, N=.2, L=1
- unlabeled W weight=0, without fabricated target
- W30/L90 causal input-target alignment
- simple rolling Exit>D force-close rule
- final-1Y / prior-5Y / retrain-15 / 300-epoch first formal validation
- current formal-label C has measurable forward association
```

Not established:

```text
- that 300 epochs is globally optimal
- that Q is reliably predictable
- that Low behavior generalizes
- that 2026 High performance represents multiple independent successes
- that rolling improvement is caused by increasing training information rather than regime/init effects
- that current H/N/L classification head is optimally aligned with C/Q regression
- that changing seed behavior is the dominant source of retrain discontinuity
```

---

# 21. Next-step discipline

Proceed one question at a time. Do not bundle model changes with data changes.

Before any new experiment, explicitly state:

```text
1. exact question being asked
2. data universe
3. what is changed
4. what is held fixed
5. output/statistics to inspect
```

No substantive next experiment is implicitly approved by this handoff.

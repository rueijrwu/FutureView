# FutureView Layer1 / Layer2 Research Rules and Experiment Registry

Date: 2026-09-04
Branch: `layer2-price-distribution-v1`

This document is the current rule registry for the active Layer1/Layer2 research. It exists to prevent strategy semantics, Layer1 outcome construction, Layer2 inputs, training memory, and experimental variables from being mixed together.

**Rule discipline:** no strategy rule, Layer1 membership rule, Layer2 training boundary, target definition, purge/embargo rule, model input, loss, or evaluation rule may be silently added or changed. Any unapproved implementation is experimental only and must not replace this registry.

---

## 1. Legal Entry / Exit preprocessing

### Raw legal Entry

A daily session is a raw legal Entry when:

```text
close > MA5 > MA10 > MA20
```

All satisfying sessions are first recorded. They are not merged during the scan.

### Forward-anchor cleaning

For sorted same-type raw legal points `p0 < p1 < ...`, use the earliest unconsumed point as anchor and absorb same-type points satisfying:

```text
pi - p0 <= 3 trading sessions
```

Absorbed points do not extend the group transitively. The next unconsumed point becomes the next anchor.

The same forward-anchor concept is applied independently to legal Entry, 5D Exit, and 10D Exit events.

---

## 2. Fixed deterministic Strategy path

Each cleaned legal Entry has one deterministic Strategy path.

1. Initial Entry deploys `1/3` of original campaign capital.
2. Find the most recent retrospective local minimum before Entry from the union of the 5D and 10D local-minimum sets.
3. Define:

```text
D_b = Entry price - base-min price
```

and require `D_b > 0`.
4. Addon candidates are later retrospective local maxima from the union of the 5D and 10D local-maximum sets.
5. The first chronological candidate satisfying:

```text
candidate price - last actual buy price > D_b
```

becomes the next Addon.
6. The original Entry-time `D_b` is reused for every Addon.
7. Maximum deployment is Entry + Addon1 + Addon2; each deployment uses `1/3` of original campaign capital.
8. First cleaned legal 5D Exit sells 40% of then-current shares. It occurs at most once.
9. A 5D partial Exit does not disable later Addons.
10. Cleaned legal 10D Exit liquidates all remaining shares and terminates the campaign.
11. Same-session priority is:

```text
10D Exit > 5D partial Exit > Addon
```

12. Maximum path horizon is 60 trading sessions. Remaining shares at the horizon close are liquidated.

The realized return of the unique deterministic path for Entry `e` is denoted `R(e)`.

---

## 3. Retrospective extrema semantics

The 5D/10D local minima and maxima are retrospective historical outcome definitions used to construct the deterministic Strategy path.

They are **not** Layer2 input indicators.

The following are not approved additions:

```text
no assistant-added +10D availability delay
no cutoff-specific extrema reconstruction
no extrema confirmation embargo
```

Do not change the Strategy's retrospective extrema definition merely to make Layer1 causal. Causality for Layer2 is enforced by what information Layer2 receives, not by silently redefining the historical Strategy outcome.

---

## 4. Layer1 window-path membership — CURRENT APPROVED RULE

For a Layer1 window:

```text
W = [start, end]
```

a Strategy path is legal for the window only when its complete path lies inside the window:

```text
start <= entry_index <= final_exit_index <= end
```

Therefore:

1. A path whose Entry is inside W but whose final Exit is after W is excluded.
2. A path whose Exit is inside W but whose Entry is before W is excluded.
3. An unfinished path is excluded.
4. There is no `final_exit + 10D` shift.
5. Entry-side and exit-side calculations use the same complete-path population under this rule unless a future explicitly approved definition changes this.

This rule supersedes the older Entry-cohort rule in which Entry membership alone was sufficient even when the path exited after W.

---

## 5. Layer1 C / Q definitions

For the legal complete-path set in W, let:

```text
I_W = {e : start <= entry(e) <= final_exit(e) <= end}
```

and:

```text
U_W = max_{e in I_W} R(e)
```

Let `B_W` be the formal periodic baseline return for the same W region.

Define:

```text
C_W = U_W - B_W
```

Interpretation:

- `C > 0`: the best legal complete Strategy opportunity in W outperformed periodic B.
- `C < 0`: even the best legal complete Strategy opportunity in W underperformed periodic B.

Per Entry/path:

```text
Q(e) = U_W - R(e)
```

Thus:

```text
Q >= 0
Q = 0 -> Entry/path attains U_W
smaller Q -> closer to the best Entry/path in W
```

The existing scalar W-level Q is the mean of valid per-Entry Q values unless explicitly changed in a future approved experiment.

A W with no legal complete path has no formal U/C/Q label; do not invent `C=0`, `Q=0`, or Neutral solely because it is unlabeled.

---

## 6. Layer1 H / N / L state

The active research currently uses Layer1 H-only for Layer2 selection. L-region research has been abandoned for the current line of work.

The historical H/N/L reference logic remains a Layer1 state definition and must not be confused with Layer2 future-return direction.

High means a retrospectively strong Strategy-opportunity/timing region under the Layer1 C/Q reference structure. It does **not** itself mean that the future market is bullish.

Any change to the exact H/N/L thresholds or reference windows must be explicitly approved before implementation.

---

## 7. Layer2 input

Layer2 receives price and volume only.

For each Layer2 sample, the feature history is:

```text
MODEL_HISTORY = 90 trading sessions
```

Current representation:

```text
price channel  = log(close) - log(last close in the 90D input)
volume channel = within-input z-score of log(volume)
input shape    = 2 x 90
```

No retrospective extrema, future Exit, future path return, future C/Q, or other future-derived Strategy outcome is supplied as a Layer2 input feature.

---

## 8. Layer2 rolling training window — CURRENT APPROVED RULE

At an OOS/retraining date `t`, Layer2 training candidates come from the immediately preceding 30 trading sessions:

```text
t - 30 <= sample_cutoff < t
```

This is a **30-session time lookback**.

It is not:

```text
memory = 30 samples
memory = 150 samples
```

The number of eligible samples inside the 30-session window is allowed to vary.

The older `memory=150` implementation meant "retain the latest 150 eligible samples". That was a fixed sample-count memory whose effective time span could vary. It is historical/experimental terminology and is not the current approved training-memory definition.

---

## 9. Keep the time variables separate

The following variables have different meanings and must never be conflated:

```text
W              = Layer1 C/Q window length
MODEL_HISTORY  = Layer2 P/V feature-history length; currently 90D
L2_TRAIN_W     = Layer2 rolling training lookback; currently 30D
RETRAIN_DAYS   = interval between fresh model retraining
h              = future-return target horizon
path horizon   = deterministic Strategy maximum holding/path horizon; 60D
```

The previously tested retraining cadences include 15D and 10D. Their comparative performance is experimental evidence, not permission to redefine the other time variables.

---

## 10. Layer2 target / training-boundary status

The exact future-return target horizon `h` is an experiment variable. Values previously explored include:

```text
h = 5, 10, 15, 20, 25, 30, 45 trading sessions
```

**Important:** a target-maturity, purge, embargo, or related training-boundary rule is a separate research definition. It must not be silently inferred from the 30D training lookback or added to the pipeline without explicit approval.

The earlier automatically introduced rule such as:

```text
sample_cutoff + h < OOS_start
```

must not be treated as approved merely because it is conventionally causal. It requires explicit research approval before becoming part of the baseline.

---

## 11. Current research scope

Current active scope:

```text
Ticker: TSLA
Layer1: H-only
Layer2 input: 90D normalized price/volume
Layer2 training lookback: preceding 30 trading sessions
Layer2 target horizon h: experimental
Retraining cadence: experimental
```

The current goal is to determine whether Layer2 can extract predictive structure from causal price/volume within Layer1-selected H regions, and then study interactions across future horizons.

A proposed later Layer3 may consume Layer2 results across multiple horizons (for example 5D through 30D in 5D increments), but Layer3 is not part of the current baseline until separately approved.

---

## 12. Evaluation terminology

Evaluation is chronological OOS.

Metrics may include:

```text
Spearman rank correlation
Pearson correlation where useful
top-vs-bottom realized future-return separation
realized up-rate by score bucket
fold / retrain-period consistency
OOS sample count
```

`realized up-rate` means the fraction of actual future returns greater than zero in a selected bucket. It is **not** model classification accuracy unless an explicit classification target is separately defined.

Do not judge a configuration only by the single highest Spearman. Stability across neighboring parameter settings, chronological periods, and non-overlapping/de-overlapped observations should be reported when those analyses are explicitly run.

---

## 13. Experiment variables to record for every run

Every future result must record at least:

```text
ticker
source data span
W
Layer1 path-membership rule
Layer1 scope / H rule
MODEL_HISTORY
L2_TRAIN_W
h
RETRAIN_DAYS
model architecture
loss / objective
random seed(s)
OOS date span
OOS n
metric definitions
code commit
```

If any additional purge, embargo, sample-selection, weighting, calibration, or overlap-handling rule is used, it must also be explicitly recorded.

---

## 14. Historical observations — NOT CURRENT VALIDATION

Before the leakage/boundary review, the 45D target produced these observed Spearman values:

| W | h=45D Spearman |
|---:|---:|
| 20 | 0.491 |
| 30 | 0.430 |
| 45 | 0.570 |
| 60 | 0.631 |

Thus the strongest observed pre-review 45D setting was:

```text
W=60, h=45D, Spearman approximately 0.631
```

For W=45, h=45D was also the strongest observed horizon in that earlier sweep, at approximately 0.570.

These numbers are experiment history only. They are not evidence for the rebuilt pipeline until all currently approved rules in this registry are applied consistently and the experiment is rerun.

---

## 15. Implementation guardrail

Before the next training run:

1. Rebuild Layer1 membership using only complete paths contained inside each W.
2. Remove the unapproved `final_exit + 10D` availability rule.
3. Preserve the locked retrospective extrema Strategy semantics.
4. Replace legacy fixed-count `memory=150` training selection with the approved preceding-30-session Layer2 training window.
5. Do not add a target purge/maturity rule until it is explicitly discussed and approved.
6. Run a minimal test first and report sample counts/boundaries before any broad parameter sweep.

Any code that conflicts with these rules should be treated as stale or experimental until reconciled.
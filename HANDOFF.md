# FutureView Strategy 1 — Full Research Handoff

Last consolidated: 2026-08-28

Branch: `strategy-profitability-restart`

This document is the current research-state handoff. It intentionally distinguishes **current locked definitions**, **current validated observations**, **archived/invalidated experiments**, and **remaining open questions**. When older documents conflict with this handoff, use the current code and the latest verified audit runs described here.

---

# 0. Current objective

The Strategy itself is fixed. The research is not trying to optimize Entry rules, Addon rules, Exit rules, capital allocation, or invent a better trading strategy.

The narrow research question is:

> Given the fixed Strategy, does the historical price/volume state contain information about whether the Strategy is operating in a favorable or unfavorable C/Q opportunity region, and later can a causal model estimate the C/Q distribution of a current cleaned legal Entry?

Current work has been intentionally stepped back from Layer 2. The immediate task is to validate the **cleaned legal-point data and Layer 1 statistical structure first**.

Current high-level pipeline:

```text
raw daily market data
→ compute raw Strategy signals/events
→ scan ALL raw legal Entry / Exit points
→ 3-session forward-anchor legal-point preprocessing
→ cleaned legal Entry / Exit data
→ deterministic Strategy paths
→ R(e)
→ W30 U / B / C / Q
→ Layer 1 historical state statistics
→ only after Layer 1 is accepted: rebuild Layer 2
```

A key methodological decision is that the legal-point merge is a **data preprocessing step before all Strategy outcome/CQ/model construction**. Raw legal events are not the formal downstream dataset.

---

# 1. Legal Entry rule

The raw legal Entry condition is unchanged:

```text
close > MA5
close > MA10
close > MA20
MA5 > MA10
MA10 > MA20
```

Equivalently:

```text
close > MA5 > MA10 > MA20
```

Every session satisfying this condition is first recorded as a **raw legal Entry**. Do not perform merging while scanning; the complete raw set must exist first.

This point is important because the preprocessing must not change which raw points are legally detected.

---

# 2. Legal Entry / Exit preprocessing — LOCKED

This is a data-cleaning rule applied **after the complete raw scan** and **before deterministic paths/CQ/modeling**.

## 2.1 Forward-anchor rule

Let the sorted raw legal points be:

```text
p0 < p1 < p2 < ...
```

Take the earliest currently unconsumed point `p0` as the anchor.

Merge every same-type raw legal point occurring within the next 3 trading sessions:

```text
pi - p0 <= 3
```

into `p0`.

The anchor itself is retained as the cleaned point.

All absorbed members are permanently consumed and **cannot propagate the cluster farther forward**.

Then choose the next unconsumed raw point as the next anchor and repeat.

Therefore:

```text
NOT ±3
NOT transitive / connected-component clustering
NOT scan-and-merge simultaneously
```

It is specifically:

```text
complete raw scan
→ earliest unconsumed anchor
→ absorb only anchor+1 ... anchor+3 sessions
→ absorbed members cannot extend the group
→ next unconsumed anchor
```

## 2.2 Example

Raw Entry indices:

```text
100, 103, 106, 107
```

First anchor = 100.

```text
103 - 100 = 3
```

so 103 is merged into 100.

106 is NOT merged into the first cluster because:

```text
106 - 100 = 6
```

Even though:

```text
106 - 103 = 3
```

103 was already absorbed and therefore cannot extend the cluster.

Next anchor = 106, and 107 is absorbed:

```text
106,107 → 106
```

Final cleaned Entry set:

```text
{100,106}
```

## 2.3 Exit preprocessing

The same forward-anchor preprocessing is applied after scanning all raw Exit events.

Current implementation treats 5-day Exit events and 10-day Exit events as separate event types and cleans each type independently.

This preserves their different Strategy meanings.

## 2.4 Formal code

The current implementation is in:

```text
src/futureview/strategy1_deterministic_paths.py
```

with:

```text
MERGE_GAP = 3
merge_legal_points_after_scan(...)
preprocess_legal_points(...)
```

`build_deterministic_path_table()` calls `preprocess_legal_points()` before constructing Strategy paths.

Therefore the current deterministic-path pipeline now uses cleaned legal points by construction.

---

# 3. Raw points versus formal data — LOCKED distinction

Raw Entry/Exit points are detection results only.

They are not formal Strategy observations and are not model samples.

The correct order is:

```text
raw legal points
→ preprocessing
→ cleaned legal points
→ deterministic Strategy outcome
→ C/Q
→ Layer1 / Layer2
```

The following order is wrong:

```text
raw Entry
→ Strategy outcome or C/Q
→ merge later
```

This means all Layer 2 results produced from the previous raw-entry population are now historical/invalid for the current formal dataset and must eventually be rebuilt.

---

# 4. Fixed deterministic Strategy path — LOCKED

Legal-point preprocessing changed the data population; it did not change the fixed Strategy execution semantics.

For each cleaned legal Entry there is one deterministic Strategy path.

Current path semantics:

1. Initial Entry deploys `1/3` of total campaign capital.
2. Find the most recent retrospective local minimum before Entry from the union of 5-session and 10-session local minima.
3. Define:

```text
D_b = Entry price - base-minimum price
```

and require `D_b > 0`.
4. Addon candidates are later retrospective local maxima from the 5/10-session maxima union.
5. The first chronological qualifying candidate satisfying

```text
candidate_price - last_buy_price > D_b
```

becomes the next Addon.
6. Reuse the original `D_b` for every Addon.
7. Maximum deployment count is:

```text
Entry + Addon1 + Addon2
```

8. Each deployment uses exactly `1/3` of the original total-capital denominator.
9. First cleaned legal 5-day Exit after Entry sells `40%` of then-current shares.
10. The 5-day partial Exit happens at most once and does not disable later Addons.
11. Cleaned legal 10-day Exit liquidates all remaining shares and terminates the campaign.
12. Same-day priority is:

```text
10-day Exit > 5-day partial Exit > Addon
```

13. Maximum path horizon is 60 sessions.
14. Any remaining shares at the horizon are liquidated at the horizon close.
15. There is no 3-day re-entry cooldown in this locked deterministic C/Q path.

Do not substitute the broader legacy behavior in `strategy1.py` for these deterministic C/Q semantics.

---

# 5. Outcome notation — LOCKED

The current formal return notation is:

```text
R(e)
```

where `e` is a cleaned legal Entry and:

```text
R(e) = realized return of the unique deterministic Strategy path starting at e
```

Older documents/code comments may use `E(e)`. For current discussion and documentation, use `R(e)`.

For an evaluation region `W`, define the cleaned legal Entry set:

```text
I_W = { cleaned legal Entries whose initial Entry lies inside W }
```

The best Strategy return in that region is:

```text
U_W = max_{e in I_W} R(e)
```

`U` is not an optimized Strategy. It is simply the best realized return among all cleaned legal Entries of the already-fixed Strategy in that region.

---

# 6. Baseline and C — LOCKED

Let `B_W` be the periodic baseline return over the same evaluation region.

Current central definition:

```text
C_W = U_W - B_W
```

This supersedes old historical definitions such as `C=U-L`.

Interpretation:

- `R(e)` = realized return of one specific cleaned Entry.
- `U` = best fixed-Strategy Entry return available in the region.
- `B` = periodic baseline return over the same region.
- `C=U-B` = how much the region's best legal fixed-Strategy opportunity beats or trails the periodic baseline.

Therefore:

```text
C > 0  → region contains a legal Strategy opportunity outperforming periodic baseline
C < 0  → even the best legal Entry in the region underperformed periodic baseline
```

C is a **region opportunity-quality measure**, not the return of the current Entry and not a directional trend score.

A large historical C also does not mean that opportunity must remain after the evaluation region has completed.

---

# 7. Q — LOCKED

For a cleaned legal Entry `e` in the same evaluation region:

```text
Q(e) = U - R(e)
```

Properties:

```text
Q >= 0
Q = 0 → this Entry itself attains the region upper bound U
smaller Q → Entry is closer to the region's best legal Entry
larger Q → Entry is farther below the best legal Entry
```

Q is an Entry-quality / timing-distance measure.

Q is NOT:

```text
trend strength
market direction
normalized by C
(U-R)/C
volatility-normalized regret
```

Those alternatives are closed unless explicitly reopened.

Desired semantic combination:

```text
C large + Q small
```

meaning a favorable Strategy-opportunity region and an Entry near that region's best legal Entry.

---

# 8. W30 Layer 1 construction

Current Layer 1 works on rolling:

```text
W = 30 trading sessions
stride = 1 session
```

For each W30 state, C is computed from `U-B` using cleaned Entry outcomes.

A window-level Q statistic is constructed from cleaned legal Entries in the W30 and used by Layer 1. The current gate logic is based on the historical C/Q state of the completed W30.

Layer 1 is retrospective. It labels what the completed W30 looked like under the fixed Strategy; it is not itself a forward market-direction classifier.

---

# 9. Layer 1 reference structure — LOCKED

Layer 1 uses two reference scales.

## 9.1 Short reference

Rolling 90-session historical reference:

```text
C90_40
C90_60
Q90_40
Q90_60
```

Short-high condition:

```text
C >= C90_60
and Q <= Q90_60
```

Short-low condition:

```text
C <= C90_40
and Q >= Q90_40
```

## 9.2 Long reference

Trailing 756 sessions, approximately 3 years:

```text
C3Y_50
Q3Y_50
```

Long-high:

```text
C > C3Y_50
and Q < Q3Y_50
```

Long-low:

```text
C < C3Y_50
and Q > Q3Y_50
```

## 9.3 Final state

```text
High = ShortHigh AND LongHigh
Low  = ShortLow  AND LongLow
Neutral = otherwise
```

The short reference remains the original **40/60** definition.

A previous ~50% sensitivity experiment is closed. It did not produce enough conceptual improvement to replace the 40/60 baseline.

Do not tune the gate simply to obtain desired class proportions.

---

# 10. Layer 1 semantics — LOCKED

Current labels mean:

```text
High    = retrospectively high Strategy opportunity + relatively good Entry timing
Low     = retrospectively low Strategy opportunity + relatively poor Entry timing
Neutral = intermediate / non-extreme retrospective state
```

Important:

```text
High ≠ future bullish
Low  ≠ future bearish
```

The observed historical relationship is primarily mean-reverting, not continuation-like.

Layer 1's intended downstream role is a Neutral prefilter:

```text
High → PASS
Low → PASS
Neutral → FILTER / BLOCK
```

High and Low remain distinct states downstream.

Layer 1 is not a Good-vs-Bad classifier.

---

# 11. Original pre-cleaning Layer 1 finding — HISTORICAL CONTEXT

Before the new legal-point preprocessing, the 5-year W30 Layer 1 audit produced:

```text
High = 77
Neutral = 146
Low = 80
```

Past versus completely non-overlapping next-W30 correlations were:

```text
C Pearson  = -0.333
C Spearman = -0.374
Q Pearson  = -0.173
Q Spearman = -0.099
```

This was the first important evidence that past C/Q structure was associated with the following W30, but with a negative / mean-reverting direction rather than continuation.

Those numbers are now **historical baseline values only**, because the legal Entry/Exit dataset has changed.

Do not use them as the current Layer 1 population.

---

# 12. Previous-W Neutral-gate experiment — HISTORICAL BUT CONCEPTUALLY IMPORTANT

A separate experiment tested whether the exact previous W30 state could act as a Neutral filter for a later target population.

Using the old population and previous window:

```text
[t-30, t-1]
```

results included:

```text
exact previous-W matches = 73
PASS (previous High/Low) n = 39
BLOCK (previous Neutral) n = 34
```

Target non-Neutral rate:

```text
PASS  = 61.54%
BLOCK = 35.29%
```

Target Neutral rate:

```text
PASS  = 38.46%
BLOCK = 64.71%
```

This supported the conceptual use of Layer 1 as a **Neutral prefilter**, not Good/Bad prediction.

However this audit also predates the new legal-point preprocessing. Its exact numbers must be recomputed before formal reuse.

---

# 13. Current cleaned-data C/Q full audit — CURRENT

Verified workflow:

```text
Strategy 1 C Q Full Audit
run: 33177328828
source commit: 449aeeade02d77c57dd2e88a00f19edff0e06963
```

The Python job completed with:

```text
S1 CQ FULL COMPLETE
```

TSLA 5-year data, W30:

```text
rows = 1255
windows = 798
Entry-window pairs = 2275
entries/window mean = 2.851
entries/window median = 3.0
```

C distribution:

```text
mean   = -4.5863%
min    = -51.8393%
P01    = -41.2296%
P05    = -31.1970%
P10    = -23.5464%
P25    = -11.1253%
median = -3.0118%
P75    = +4.2117%
P90    = +11.0524%
P95    = +15.9037%
P99    = +23.5950%
max    = +26.5654%
```

Q distribution:

```text
mean   = 2.3183%
min    = 0
P01    = 0
P05    = 0
P10    = 0
P25    = 0
median = 1.0481%
P75    = 3.8188%
P90    = 6.1764%
P95    = 8.3563%
P99    = 15.3116%
max    = 17.3204%
Q=0 rate = 35.0769%
```

Interpretation:

The forward-anchor cleaning sharply reduced repeated nearby Entry observations while preserving a broad and non-trivial C/Q outcome distribution.

---

# 14. Current cleaned-data Layer 1 forward-W audit — CURRENT

Verified workflow:

```text
Strategy 1 Layer 1 Forward W Audit
run: 33177328925
job: 98869231054
source commit: 449aeeade02d77c57dd2e88a00f19edff0e06963
```

The Python job completed with:

```text
S1 L1FW COMPLETE
```

Current cleaned-data support:

```text
classified states = 297
complete future-W states = 297
valid future C/Q pairs = 212
```

Current Layer 1 population:

```text
High = 60
Neutral = 158
Low = 79
```

These supersede the old `77/146/80` pre-cleaning counts.

## 14.1 Overall past-W versus future-W relationship

```text
C Pearson  = -0.301316
C Spearman = -0.321645
Q Pearson  = -0.349466
Q Spearman = -0.318524
Entry-count Pearson  = -0.333279
Entry-count Spearman = -0.329285
```

The central qualitative result survived preprocessing:

> Past C/Q state remains associated with the immediately following non-overlapping W30, and the dominant relationship remains negative / mean reverting.

Q association is now materially more negative than in the pre-cleaning audit.

## 14.2 High state

```text
n = 60
valid C/Q future pairs = 48
past C mean   = +4.3149%
future C mean = -10.1022%
past Q mean   = 0.1030%
future Q mean = 1.7766%
past Entry count mean   = 1.633
future Entry count mean = 2.617
future Entry median     = 3
future zero-Entry rate  = 20.00%
```

Within-High correlations:

```text
C Pearson  = -0.119278
C Spearman = +0.005970
Q Pearson  = -0.389945
Q Spearman = -0.400625
Entry Pearson  = +0.297882
Entry Spearman = +0.331816
```

High remains retrospectively strong but is followed by weak mean future C on average.

## 14.3 Neutral state

```text
n = 158
valid C/Q future pairs = 105
past C mean   = -4.9793%
future C mean = -7.3691%
past Q mean   = 1.5805%
future Q mean = 2.3116%
past Entry count mean   = 2.892
future Entry count mean = 2.348
future Entry median     = 2
future zero-Entry rate  = 23.42%
```

Within-Neutral correlations:

```text
C Pearson  = -0.393451
C Spearman = -0.343127
Q Pearson  = -0.499359
Q Spearman = -0.506040
Entry Pearson  = -0.478362
Entry Spearman = -0.509541
```

## 14.4 Low state

```text
n = 79
valid C/Q future pairs = 59
past C mean   = -21.7962%
future C mean = -3.5628%
past Q mean   = 3.2475%
future Q mean = 1.8205%
past Entry count mean   = 4.241
future Entry count mean = 2.570
future Entry median     = 3
future zero-Entry rate  = 25.32%
```

Within-Low correlations:

```text
C Pearson  = -0.045347
C Spearman = +0.092987
Q Pearson  = -0.496601
Q Spearman = -0.460711
Entry Pearson  = -0.622465
Entry Spearman = -0.600802
```

Low still shows strong average recovery in C and improvement in Q in the following W30, while Entry density falls substantially.

---

# 15. What legal-point preprocessing changed

The most obvious mechanical effect is reduced nearby-Entry duplication.

Pre-cleaning mean Entry counts per state versus current cleaned data were approximately:

```text
High:    5.61 → 1.63
Neutral: 7.73 → 2.89
Low:    12.36 → 4.24
```

Therefore the cleaning is not cosmetic. It materially changes the downstream observation population.

At the same time, the main Layer 1 historical relationship remained:

```text
pre-cleaning C correlation ≈ -0.33 / -0.37
post-cleaning C correlation ≈ -0.30 / -0.32
```

This is useful because it suggests the earlier Layer 1 relationship was not solely an artifact of counting long runs of adjacent stacked-MA Entry days as separate formal Entries.

Current interpretation:

```text
3-session forward-anchor preprocessing
→ strongly reduces duplicate nearby legal points
→ preserves broad C/Q variation
→ preserves the main historical Layer1 mean-reverting association
```

---

# 16. Overlap and statistical interpretation

W30 states use stride 1, so adjacent states overlap heavily.

That does NOT mean adjacent legal Entries are unreal or invalid decisions. It means statistical evaluation must distinguish:

```text
valid operational samples
from
independent statistical observations
```

The forward-W audit pairs each completed W30 with the completely non-overlapping immediately following W30:

```text
Past_W   = [t-W+1, t]
Future_W = [t+1, t+W]
```

However adjacent Past_W states still overlap one another because stride=1.

Therefore the current correlations and state means are best described as:

```text
historical descriptive temporal association
```

not yet:

```text
independent predictive significance
```

For future model Train/Validation/Test evaluation, centered C/Q targets also overlap strongly for neighboring Entry dates. Chronological partitioning with purge/embargo is therefore required to prevent near-identical target regions from straddling train/test boundaries.

---

# 17. Layer 2 research question — ARCHIVED UNTIL REBUILD

The intended Layer 2 question remains conceptually useful:

> At a current cleaned legal Entry t, using only causal price-volume information available through t, can a model estimate the C/Q distribution of the Entry-centered local region?

For W=30, intended causal input is:

```text
X_t = [t-29, t]
```

including the Entry day.

Historical centered target region was:

```text
R_t = [t-29, t+30]
```

The future half is used only to construct historical labels after it has happened. It is not an input feature.

The desired conceptual mapping is nonlinear/probabilistic:

```text
X_t → p(C_t, Q_t | information available at cleaned legal Entry t)
```

Do not revert to linear-regression/R² framing as the primary research method; previous work already showed that a simple linear interpretation is not the intended problem.

---

# 18. Previous Layer 2 baseline — INVALIDATED BY DATA REDEFINITION

A previous formal baseline used a small multiscale 1D CNN and the old legal-Entry population.

Architecture included:

```text
8 causal price/volume channels
kernels 5 / 10 / 20
continuous C and Q outputs
SmoothL1 loss
chronological train/val/test split
30-session embargo
```

The old 10-year formal run had:

```text
Layer1 classified rows = 1382
exact gate matches = 440
PASS Entries = 197
train = 135
val = 11
test = 17
```

Old test metrics included:

```text
C MAE  ≈ 0.0776
Q MAE  ≈ 0.0399
C corr ≈ -0.050
Q corr ≈ -0.815
```

and a live old-population TSLA Entry at 2026-08-27 produced:

```text
C_hat = -0.150477
Q_hat =  0.095224
```

These results are now **not current model results** because the legal Entry/Exit preprocessing changed the formal dataset before Strategy paths are constructed.

The saved checkpoint and live prediction must not be used for current research conclusions.

When Layer 2 resumes, it must be retrained from the cleaned legal-point population from the beginning.

---

# 19. Important unresolved Layer 1 → Layer 2 handoff issue

Before preprocessing changed the dataset, two different Layer 1 handoff concepts existed:

1. Previous-W causal gate concept:

```text
Layer1 window = [t-30, t-1]
```

2. Current `Layer2.md` / old formal training code used exact same-session handoff:

```text
Layer1.end_index = t
```

These are not the same architecture.

Do not silently claim they are equivalent.

This issue is intentionally unresolved because Layer 2 is currently paused. Before rebuilding Layer 2, explicitly decide which gate timing is conceptually correct under the cleaned Entry dataset.

Separately, Layer 2 input itself is intended to include the current Entry day:

```text
[t-29, t]
```

Do not confuse the Layer 1 gate-timing question with the Layer 2 causal feature window.

---

# 20. Documentation staleness warning

Some repository documents still contain pre-cleaning values or notation.

In particular, current `Layer1.md` still contains historical values such as:

```text
High/Neutral/Low = 77/146/80
E(e)
old pre-cleaning forward-W statistics
```

These are now stale as the formal current state.

`Layer2.md` also describes the old pre-cleaning Layer 2 dataset and exact same-session handoff.

Until those documents are separately revised, this `HANDOFF.md`, the current deterministic-path code, and the latest verified post-cleaning audit runs are the authoritative state for the ongoing discussion.

---

# 21. Current conclusions — what is actually supported

## Supported

1. The correct formal Entry/Exit data should be produced only after the complete raw legal-point scan and the forward-anchor 3-session preprocessing.
2. The preprocessing materially reduces repeated nearby legal Entry observations.
3. The cleaned data still produces a broad C/Q distribution.
4. The Layer 1 High/Neutral/Low structure remains well populated after cleaning.
5. Historical past-W C remains negatively associated with next-W C.
6. Historical past-W Q also shows a negative next-W association after cleaning.
7. High is not a continuation label; on average it is followed by much weaker future C.
8. Low is not a bearish continuation label; on average future C improves substantially and Q becomes smaller.
9. Therefore the useful Layer 1 finding is historical temporal structure / mean reversion, not directional continuation.

## Not yet supported

1. Independent predictive significance.
2. A deployable trading signal from Layer 1 alone.
3. A validated Layer 2 C/Q predictor using the cleaned dataset.
4. The old Layer 2 checkpoint or old 2026-08-27 live prediction.
5. A final decision on previous-W versus same-session Layer 1 handoff for future Layer 2.
6. Any claim that low trade count is inherently bad; lower decision frequency may simply mean fewer informative/valid opportunities.

---

# 22. Closed / rejected directions

Do not reopen these casually:

```text
C = U-L                         → rejected; current C = U-B
Q = (U-R)/C                     → rejected
normalize Q by C or |C|         → rejected
50% Layer1 threshold replacement→ closed; keep 40/60
Layer1 as Good/Bad classifier   → rejected
Neutral as a useful PASS state  → current rule is Neutral FILTER
linear regression / R² as the primary Layer2 framing → rejected
AE as required first layer      → not current architecture
Strategy optimization during this research → out of scope
```

The fixed Strategy should not be modified merely to improve model statistics.

---

# 23. Immediate next step

Do NOT immediately retrain Layer 2.

The next small falsifiable question should remain inside Layer 1:

> After legal-point preprocessing, are the High / Neutral / Low C/Q separations and their forward-W behavior stable across time, rather than being dominated by one chronological regime?

Suggested next audit without changing any definitions:

```text
1. Keep W=30, 40/60 short thresholds, 3Y median, cleaned Entry/Exit data.
2. Split the available history into several chronological evaluation periods/folds.
3. For each fold report High/Neutral/Low support.
4. Report C and Q distribution by state: mean, median, quantiles.
5. Report non-overlapping next-W C/Q distribution by prior state.
6. Check whether the ordering / mean-reversion direction is consistent across folds.
7. Do not train a model in this step.
```

The purpose is not to maximize correlation. It is to determine whether the first-layer statistical structure is sufficiently stable to justify using it as a gate/context definition for a rebuilt Layer 2.

---

# 24. Key GitHub state

Current formal branch:

```text
strategy-profitability-restart
```

Key post-cleaning source/audit commit:

```text
449aeeade02d77c57dd2e88a00f19edff0e06963
```

Verified current audit runs:

```text
C/Q Full Audit:
  run 33177328828
  completion marker: S1 CQ FULL COMPLETE

Layer1 Forward-W Audit:
  run 33177328925
  job 98869231054
  completion marker: S1 L1FW COMPLETE
```

Previous handoff-only commit:

```text
6dde759c4c3909f8c14f78c25702b65120c7cf7a
```

This rewritten handoff supersedes that shorter summary.

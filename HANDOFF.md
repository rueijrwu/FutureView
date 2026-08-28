# FutureView Strategy 1 — Full Research Handoff

Last consolidated: 2026-08-28

Branch: `strategy-profitability-restart`

This document is the current research-state handoff. It distinguishes **locked definitions**, **validated observations**, **archived/invalidated experiments**, and **open questions**. When older documents conflict with this handoff, use the current code and the latest verified audit runs described here.

---

# 0. Current objective

The Strategy itself is fixed. This research is not trying to optimize Entry rules, Addon rules, Exit rules, capital allocation, or invent a better trading strategy.

The narrow research question is:

> Given the fixed Strategy, does historical price/volume structure contain information about whether a trader-defined trading interval is operating in a favorable or unfavorable C/Q opportunity region, and later can a causal model learn the corresponding price/volume structure from longer historical context?

Current work has intentionally stepped back from Layer 2. The immediate task is to understand the **cleaned legal-point data and Layer 1 statistical structure** before rebuilding any model.

Current high-level pipeline:

```text
raw daily market data
→ compute raw Strategy signals/events
→ scan ALL raw legal Entry / Exit points
→ 3-session forward-anchor legal-point preprocessing
→ cleaned legal Entry / Exit data
→ deterministic Strategy paths
→ R(e)
→ trader-defined W → U / B / C / Q
→ Layer 1 historical state / importance statistics
→ only after Layer 1 is accepted: rebuild Layer 2
```

A key methodological decision is that legal-point merging is a **data preprocessing step before all Strategy outcome/CQ/model construction**. Raw legal events are detection results only and are not formal downstream observations.

---

# 1. Legal Entry rule — LOCKED

The raw legal Entry condition is:

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

Every session satisfying this condition is first recorded as a **raw legal Entry**. Do not merge while scanning; the complete raw set must exist first.

---

# 2. Legal Entry / Exit preprocessing — LOCKED

This cleaning rule is applied **after the complete raw scan** and **before deterministic paths/CQ/modeling**.

## 2.1 Forward-anchor rule

Let sorted raw legal points be:

```text
p0 < p1 < p2 < ...
```

Take the earliest currently unconsumed point `p0` as anchor. Merge every same-type raw legal point occurring within the next 3 trading sessions:

```text
pi - p0 <= 3
```

The anchor is retained as the cleaned point. Absorbed members are permanently consumed and **cannot propagate or extend the cluster farther forward**. Then the next unconsumed point becomes the next anchor.

Therefore:

```text
NOT ±3
NOT transitive / connected-component clustering
NOT scan-and-merge simultaneously
```

Specifically:

```text
complete raw scan
→ earliest unconsumed anchor
→ absorb only anchor+1 ... anchor+3 sessions
→ absorbed members cannot extend the group
→ next unconsumed anchor
```

Example:

```text
raw Entry indices = 100, 103, 106, 107
100 absorbs 103
106 is NOT absorbed through 103
106 becomes next anchor and absorbs 107
cleaned set = {100, 106}
```

The same rule is applied to Exit events after the raw scan. Current implementation treats 5-day Exit and 10-day Exit as separate event types and cleans each independently.

Current implementation:

```text
src/futureview/strategy1_deterministic_paths.py
MERGE_GAP = 3
merge_legal_points_after_scan(...)
preprocess_legal_points(...)
```

`build_deterministic_path_table()` preprocesses legal points before constructing Strategy paths.

---

# 3. Raw points versus formal data — LOCKED

Raw Entry/Exit points are detection results only. They are not formal Strategy observations and are not model samples.

Correct order:

```text
raw legal points
→ preprocessing
→ cleaned legal points
→ deterministic Strategy outcome
→ C/Q
→ Layer1 / Layer2
```

Wrong order:

```text
raw Entry
→ Strategy outcome/CQ
→ merge later
```

All previous Layer 2 results produced from the raw-entry population are therefore historical/invalid for the current formal dataset.

---

# 4. Fixed deterministic Strategy path — LOCKED

For each cleaned legal Entry there is exactly one deterministic Strategy path.

1. Initial Entry deploys `1/3` of total campaign capital.
2. Find the most recent retrospective local minimum before Entry from the union of 5-session and 10-session local minima.
3. Define `D_b = Entry price - base-minimum price`, requiring `D_b > 0`.
4. Addon candidates are later retrospective local maxima from the union of 5-session and 10-session maxima.
5. The first chronological candidate satisfying `candidate_price - last_buy_price > D_b` becomes the next Addon.
6. Reuse the ORIGINAL `D_b` for every Addon.
7. Maximum deployment is `Entry + Addon1 + Addon2`.
8. Each deployment uses exactly `1/3` of the original total-capital denominator.
9. First cleaned legal 5-day Exit after Entry sells `40%` of then-current shares.
10. The 5-day partial Exit happens at most once and does not disable later Addons.
11. Cleaned legal 10-day Exit liquidates all remaining shares and terminates the campaign.
12. Same-day priority: `10-day Exit > 5-day partial Exit > Addon`.
13. Maximum path horizon = 60 sessions.
14. Remaining shares at horizon liquidate at horizon close.
15. No 3-day re-entry cooldown in this locked deterministic C/Q path.

Do not substitute broader legacy behavior in `strategy1.py`.

---

# 5. Outcome notation and W membership — LOCKED

Use:

```text
R(e)
```

where `e` is a cleaned legal Entry and `R(e)` is the realized return of the unique deterministic Strategy path starting at `e`.

For an evaluation region `W`:

```text
I_W = { cleaned legal Entries whose initial Entry lies inside W }
U_W = max_{e in I_W} R(e)
```

Window membership is determined only by the initial Entry date/index. If Addons or Exit occur after W, the Entry remains assigned to W and `R(e)` uses the complete deterministic path outcome.

Therefore:

```text
W is NOT a holding-period cutoff.
W is an Entry-cohort / statistical grouping interval.
Do NOT truncate a Strategy path at the W boundary.
```

Historical future path information is used only to determine retrospective outcome/label; it is not an Entry-time feature.

`U` is not an optimized Strategy. It is the best realized return among cleaned legal Entries of the already-fixed Strategy in that region.

---

# 6. Baseline and C — LOCKED

Let `B_W` be the periodic baseline return over the same evaluation region.

```text
C_W = U_W - B_W
```

This supersedes old definitions such as `C=U-L`.

Interpretation:

```text
C > 0 → region contains a legal fixed-Strategy opportunity outperforming periodic baseline
C < 0 → even the best legal Entry in the region underperformed periodic baseline
```

C is a **region opportunity-quality measure**, not the return of the current Entry and not a directional trend score.

---

# 7. Q — LOCKED

For a cleaned legal Entry `e` in the same region:

```text
Q(e) = U - R(e)
```

Properties:

```text
Q >= 0
Q = 0 → Entry itself attains regional U
smaller Q → Entry closer to region's best legal Entry
larger Q → Entry farther below region's best legal Entry
```

Q is Entry-quality / timing-distance. It is NOT trend strength, market direction, `(U-R)/C`, or volatility-normalized regret.

Desired semantic combination:

```text
C large + Q small
```

= favorable Strategy-opportunity region + Entry near the best legal Entry.

---

# 8. Layer 1 construction — CURRENT REFERENCE

The current reference implementation has primarily used rolling:

```text
W = 30 trading sessions
stride = 1 session
```

W15 and W60 have also been audited to study how the same Layer 1 construction behaves at different **trader-defined trading interval lengths**.

Crucial semantic clarification:

> W is not a model-selected optimum and is not the model input lookback. W represents the interval length the trader chooses to evaluate as a trading opportunity.

Therefore W15/W30/W60 comparisons describe the historical behavior of different trader-selected trading scales. They are not an instruction for the algorithm to choose whichever W has the largest correlation.

Layer 1 is retrospective. It labels what a completed W looked like under the fixed Strategy; it is not itself a forward market-direction classifier.

---

# 9. Layer 1 reference structure — LOCKED

Short reference: rolling 90-session history:

```text
C90_40, C90_60, Q90_40, Q90_60
```

Short-high:

```text
C >= C90_60 and Q <= Q90_60
```

Short-low:

```text
C <= C90_40 and Q >= Q90_40
```

Long reference: trailing 756 sessions (~3 years):

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
High = ShortHigh AND LongHigh
Low = ShortLow AND LongLow
Neutral = otherwise
```

The short reference remains the original 40/60 definition. The previous ~50% sensitivity experiment is closed. Do not tune the gate to obtain desired class proportions.

---

# 10. Layer 1 semantics and downstream role — LOCKED / UPDATED

State semantics:

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

Observed historical relationship is primarily mean-reverting, not continuation-like.

## 10.1 Layer 1 is a data filter / importance layer

The intended Layer 1 role is now clarified more precisely:

> Layer 1 does not decide the final trade direction, does not learn the reversal itself, and does not dictate Layer 2's effective historical receptive field. Its job is to identify how informative historical regions are for training and to provide a gate / importance weight.

Current qualitative weighting policy:

```text
High    → high training importance
Low     → high training importance
Neutral → lower training importance
```

High and Low remain distinct. Layer 1 is not a Good-vs-Bad classifier.

Neutral should generally be **down-weighted rather than deleted**, because a long Layer 2 input may contain transitions such as:

```text
High → Neutral → Low
Low → Neutral → High
```

and the Neutral portion can be part of the price/volume transition structure that Layer 2 must observe. Hard deletion could cut the transition trajectory and remove useful context.

No exact numerical weight formula is locked yet. The current principle is only:

```text
weight(Neutral) < weight(High/Low)
```

with the detailed weighting function to be decided only after the historical state/transition statistics are sufficiently understood.

---

# 11. Trader-defined W versus Layer 2 history length — LOCKED CONCEPTUAL DISTINCTION

Three concepts must remain separate:

```text
W_trade   = trader-defined interval whose Strategy opportunity is being evaluated
Layer1    = historical C/Q-based importance/filtering of that trading interval
L_model   = amount of historical price/volume context supplied to Layer 2
```

Therefore:

```text
W_trade ≠ L_model
```

Example:

```text
W_trade = 30 sessions
L_model = 90 sessions
```

is conceptually valid.

A 90-session Layer 2 input contains the shorter 15/30/60-session price/volume structures as subsets. Providing long history does **not** imply that the model must trade on a 90-session horizon.

Instead, long historical input provides a maximum available context from which Layer 2 may learn an effective shorter or longer receptive field depending on the price/volume structure.

The purpose of Layer 1 weighting is not to pre-specify that effective length. If the model architecture and objective permit it, Layer 2 should be able to learn whether a useful pattern depends mainly on recent short history or on a longer preceding structure.

Thus:

```text
W_trade = what interval the trader wants to evaluate
L_model = how much history the model is allowed to inspect to understand that opportunity
```

---

# 12. Long-context training and transition information — UPDATED DESIGN PRINCIPLE

Suppose Layer 2 is eventually trained with 90 sessions of causal price/volume history while the trader-defined opportunity scale is W30.

Layer 1 can generate a rolling W30 state/importance trajectory inside that long context. A 90-session sample may therefore contain:

```text
stable High
stable Low
High → Neutral
Neutral → Low
Low → Neutral
Neutral → High
High → Neutral → Low
Low → Neutral → High
```

A long region that is continuously in one W30 state is still valid data, but it may contain less transition information than a sample spanning a state change.

However Layer 1 should not directly encode a handcrafted reversal target or force Layer 2 to learn a specific reversal duration. Its role remains **data importance weighting/filtering**.

Because Neutral is down-weighted rather than removed, the Layer 2 model can still see the complete price/volume evolution through reversal regions. In principle, this allows Layer 2 to learn from the full long context which shorter/longer structures are relevant and what historical durations tend to correspond to tradeable opportunity.

This is the preferred conceptual separation:

```text
Layer 1: where training information is more/less important
Layer 2: what price/volume structure explains that information and what effective history length matters
```

---

# 13. Current cleaned-data C/Q full audit — CURRENT

Verified workflow:

```text
Strategy 1 C Q Full Audit
run: 33177328828
source commit: 449aeeade02d77c57dd2e88a00f19edff0e06963
```

TSLA 5-year, W30:

```text
rows = 1255
windows = 798
Entry-window pairs = 2275
entries/window mean = 2.851
entries/window median = 3.0
```

C distribution:

```text
mean -4.5863%
min -51.8393%
P01 -41.2296%
P05 -31.1970%
P10 -23.5464%
P25 -11.1253%
median -3.0118%
P75 +4.2117%
P90 +11.0524%
P95 +15.9037%
P99 +23.5950%
max +26.5654%
```

Q distribution:

```text
mean 2.3183%
min 0
P01 0
P05 0
P10 0
P25 0
median 1.0481%
P75 3.8188%
P90 6.1764%
P95 8.3563%
P99 15.3116%
max 17.3204%
Q=0 rate 35.0769%
```

Forward-anchor cleaning reduced repeated nearby Entry observations while preserving broad C/Q variation.

---

# 14. Current cleaned-data Layer 1 forward-W audit — W30 CURRENT

Verified workflow:

```text
Strategy 1 Layer 1 Forward W Audit
run: 33177328925
job: 98869231054
source commit: 449aeeade02d77c57dd2e88a00f19edff0e06963
```

Support:

```text
classified states = 297
complete future-W states = 297
valid future C/Q pairs = 212
High = 60
Neutral = 158
Low = 79
```

Overall current-W versus immediately following non-overlapping W30:

```text
C Pearson  = -0.301316
C Spearman = -0.321645
Q Pearson  = -0.349466
Q Spearman = -0.318524
Entry-count Pearson  = -0.333279
Entry-count Spearman = -0.329285
```

State means:

```text
High:
  current C = +4.3149%
  next-W C  = -10.1022%
  current Q = 0.1030%
  next-W Q  = 1.7766%
  current Entries = 1.633

Neutral:
  current C = -4.9793%
  next-W C  = -7.3691%
  current Q = 1.5805%
  next-W Q  = 2.3116%
  current Entries = 2.892

Low:
  current C = -21.7962%
  next-W C  = -3.5628%
  current Q = 3.2475%
  next-W Q  = 1.8205%
  current Entries = 4.241
```

Key result:

> Current C/Q state is historically associated with the immediately following non-overlapping W, and the dominant relationship is negative / mean-reverting rather than continuation-like.

More legal Entries does not imply better opportunity. W30 Low has the highest mean Entry count.

These are descriptive historical statistics. Adjacent rolling W rows overlap strongly and are not independent observations.

---

# 15. Row-level persistence / reversal definitions — CURRENT

Primary unit = every classified rolling W row. Do NOT compress consecutive High/Low runs into episodes for the primary statistic.

For a High/Low source row at start index `t`:

## 15.1 Leave / persistence

Search forward to the first row whose state differs from the current state.

```text
days_until_leave = first_different_state.start_index - source.start_index
future_same_days = max(days_until_leave - 1, 0)
```

If none exists, `leave_censored=True`.

## 15.2 True opposite-state first passage

```text
High opposite = Low
Low opposite  = High
```

Search forward to the first true opposite state. Neutral and same-side returns are allowed before reaching the opposite.

```text
days_to_opposite
neutral_days_before_opposite
same_state_days_before_opposite
```

If no opposite before the data ends, `opposite_censored=True`.

Example:

```text
H H H N N H N N L
```

From the first H, persistence ends at the first N, but the true H→L reversal occurs only at the final L. H→N→H does not terminate the eventual reversal search.

---

# 16. W30 row-level transition audit — CURRENT

Workflow:

```text
Strategy 1 Layer 1 Transition Audit
run: 33185034632
job: 98895710885
```

W30:

```text
classified = 297
extreme rows = 139
```

High:

```text
n = 60
leave median = 12 sessions
future_same_days median = 11
H→L valid = 52, censored = 8
H→L first-opposite median = 28.5
Neutral before H→L median = 21
same-High rows before H→L median = 8
```

Low:

```text
n = 79
leave median = 9 sessions
future_same_days median = 8
L→H valid = 79, censored = 0
L→H first-opposite median = 28
Neutral before L→H median = 17
same-Low rows before L→H median = 11
```

`days_until_leave` is the remaining lifetime conditional on observing the state at a particular rolling row; it is not an episode duration.

---

# 17. W15 / W30 / W60 transition-scale audit — CURRENT

The transition audit was parameterized by `FUTUREVIEW_W` and W15/W60 were run using the same definitions.

Current branch head after this audit workflow change:

```text
94871aaa8c1145c6388c9c49069f56fc2ff899ee
```

Workflow run:

```text
33185373484
```

## 17.1 Median first-opposite passage

```text
W15: H→L = 23.5, L→H = 14
W30: H→L = 28.5, L→H = 28
W60: H→L = 71,   L→H = 62
```

## 17.2 Median persistence / leave

```text
W15: High = 13.5, Low = 5
W30: High = 12,   Low = 9
W60: High = 36,   Low = 14
```

## 17.3 Median Neutral rows before true opposite

```text
W15: H→L = 9,  L→H = 6
W30: H→L = 21, L→H = 17
W60: H→L = 57, L→H = 34
```

Important censoring:

```text
W15 Low: 2/67 opposite censored
W30 High: 8/60 H→L censored
W60 High: 54/81 H→L censored; only 27 valid H→L first passages
```

The W60 H→L median therefore applies only to the 27 uncensored cases and must not be treated as an unconditional population median.

W60 H→L neutral-days are all 57 among those 27 valid rows, likely because heavily overlapping rolling rows share a small number of underlying transition structures. Do not interpret 57 as a universal constant.

---

# 18. Interpretation of W-scale tests — UPDATED

The W15/W30/W60 experiment shows that measured state-transition time scales materially with W.

Therefore:

> Persistence or reversal duration alone cannot be used to identify an "optimal W".

This is partly mechanical: Layer 1 state itself is constructed from rolling W C/Q, so larger W naturally changes more slowly.

Approximate first-opposite median divided by W:

```text
W15: H→L 1.57W, L→H 0.93W
W30: H→L 0.95W, L→H 0.93W
W60: H→L 1.18W, L→H 1.03W
```

The more useful interpretation is:

> Different trader-selected trading interval lengths naturally imply different opportunity-state dynamics and different practical decision/update frequencies.

This is valuable information for understanding the trading cadence associated with a chosen strategy interval, but it is **not** a reason for Layer 1 to choose W on behalf of the trader.

---

# 19. Historical current-W → next-W statistics — SCOPE CLARIFICATION

Correlation between the current historical W and the immediately following non-overlapping W is a desired Layer 1 statistic.

It should be interpreted as a retrospective historical state-transition relationship:

```text
P(S_{W+1} | S_W)
```

where state includes C/Q or High/Neutral/Low.

This is not yet causal/OOS model evaluation and should not be confused with future inference.

Current analysis mode is deliberately:

```text
NO chronological folds
NO fold-based model evaluation
aggregate descriptive historical statistics
```

If W15/W30/W60 are compared further, the immediate fair comparison is current-W → next non-overlapping same-length W correlation strength and state-conditioned future C/Q behavior for each W.

This would characterize how historical relationships differ across trader-selected time scales. It is not an optimization criterion that automatically selects W.

---

# 20. Overlap and statistical interpretation

Rolling states use stride 1, so adjacent states overlap heavily.

Distinguish:

```text
valid operational observations
from
independent statistical observations
```

Current correlations, transition counts, state means, and waiting-time summaries are best described as:

```text
historical descriptive temporal association
```

not:

```text
independent predictive significance
```

Dependence-aware inference can be considered later if significance becomes a research question. It is not the present goal.

---

# 21. Layer 2 status — PAUSED / MUST REBUILD FROM CLEANED DATA

Old Layer 2 CNN/OOS/checkpoints/live inference used the old raw-entry population and are invalidated by the legal-point preprocessing change.

Do not use the old checkpoint or old 2026-08-27 live prediction as current evidence.

Do not resume old AE/CNN assumptions automatically.

When Layer 2 eventually restarts, it must be built from the cleaned legal-point population and from the clarified Layer 1 role in Sections 10–12.

Current conceptual direction is:

```text
long causal price/volume history
→ model learns relevant multiscale structure
→ Layer 1 supplies training importance / filtering based on trader-defined W opportunity
```

The model input history should not automatically be set equal to W.

A candidate such as:

```text
W_trade = 30
L_model = 90
```

is conceptually reasonable, but the actual Layer 2 lookback is not yet locked.

---

# 22. Stale / invalidated directions

Do not reopen casually:

```text
C = U-L                           → rejected; current C = U-B
Q = (U-R)/C                       → rejected
normalize Q by C or |C|           → rejected
50% Layer1 threshold replacement  → closed; keep 40/60
Layer1 as Good/Bad classifier     → rejected
Neutral as equal-importance PASS  → rejected; Neutral is lower importance
hard-delete Neutral by default    → not current design; prefer down-weighting
linear regression / R² as primary Layer2 framing → rejected
AE as required first layer        → rejected
old raw-entry Layer2 dataset      → invalid
old CNN checkpoint/live inference → invalid
Strategy optimization during this research → out of scope
chronological folds as current Layer1 analysis → rejected for present work
```

`Layer1.md` and `Layer2.md` contain older assumptions/results and are stale where they conflict with this handoff.

---

# 23. Current supported conclusions

1. Formal Entry/Exit data is produced only after complete raw legal scan + forward-anchor 3-session preprocessing.
2. Preprocessing materially reduces repeated nearby Entry observations.
3. Cleaned data still produces broad C/Q distributions.
4. Layer 1 High/Neutral/Low remains populated after cleaning.
5. W is an Entry-cohort/statistical grouping interval and represents a trader-selected trading opportunity scale; it is not a holding-period cutoff.
6. Complete Strategy outcomes may intentionally extend outside W.
7. Current-W → next non-overlapping W correlation is a desired retrospective statistic, not model/OOS prediction evaluation.
8. W30 current-to-next historical C/Q relationships are mean-reverting.
9. More legal Entries does not imply better opportunity; W30 Low has the most Entries on average.
10. Main persistence/reversal analysis is row-level, not episode-compressed.
11. Time until leaving a state and time until first true opposite state are distinct statistics.
12. W15/W30/W60 show transition time scales materially with W; reversal duration cannot by itself select an optimal W.
13. The selected W defines the trading interval the trader wants to evaluate. The model does not choose W merely from correlation strength.
14. Layer 1's downstream role is data filtering / importance weighting, not final trade prediction.
15. High and Low should receive higher training importance than Neutral; Neutral should generally be down-weighted rather than removed.
16. Preserving Neutral in long contexts allows Layer 2 to observe complete High↔Low transition trajectories.
17. Layer 2 input history length `L_model` is separate from trader-defined `W_trade` and may be substantially longer.
18. A long model input contains shorter structures, allowing the model in principle to learn which effective history length is relevant, provided the architecture/training objective supports it.
19. Current Layer 1 work uses aggregate descriptive statistics with no folds.
20. Rolling rows are dependent; inferential significance requires dependence-aware treatment only if later needed.

---

# 24. Immediate next questions — CURRENT

Do NOT retrain Layer 2 yet.

Do NOT return to chronological folds for current Layer 1 analysis.

The next small statistical questions should remain descriptive and falsifiable. The most direct remaining question is:

> For trader-selected W15/W30/W60, how strong is the historical relationship between current-W C/Q and the immediately following non-overlapping same-length W, and how does state-conditioned next-W behavior differ by W?

Recommended statistics:

```text
1. C current-W → next same-length W Pearson/Spearman
2. Q current-W → next same-length W Pearson/Spearman
3. future C/Q means and distributions conditioned on current High/Neutral/Low
4. state/sample support and valid-pair counts
5. no folds
```

This comparison is for understanding the historical information content and trading cadence of different trader-defined intervals. It should not automatically be interpreted as selecting the "best" W.

A later Layer 2 design question, after Layer 1 is accepted, is how long `L_model` must be to let a model learn the relevant price/volume structure while Layer 1 supplies importance weighting.

---

# 25. Key GitHub state

Authoritative handoff branch:

```text
strategy-profitability-restart
```

Key cleaned-data audit commit:

```text
449aeeade02d77c57dd2e88a00f19edff0e06963
```

Transition-audit implementation/workflow branch head before this documentation update:

```text
94871aaa8c1145c6388c9c49069f56fc2ff899ee
```

Verified runs:

```text
C/Q Full Audit:
  run 33177328828

Layer1 Forward-W Audit W30:
  run 33177328925
  job 98869231054

Layer1 Transition Audit W30:
  run 33185034632
  job 98895710885

Layer1 Transition Audit W15/W60:
  run 33185373484
  W15 job 98896891387
  W60 job 98896891618
```

This handoff supersedes older Layer1/Layer2 documents and earlier fold-oriented next-step language where they conflict with the definitions above.

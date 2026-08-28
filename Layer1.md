# Strategy 1 — Deterministic Gate

## Purpose

Layer 1 is **not a learned classifier**. It is a deterministic retrospective state filter used to select informative High/Low historical contexts for Layer 2.

The fixed Strategy is never changed or optimized.

The current separation is

\[
\boxed{\text{historical C/Q statistics}\rightarrow\text{deterministic High/Neutral/Low gate}}
\]

followed by

\[
\boxed{\text{High/Low price-volume context}\rightarrow\text{Layer 2 centered-2W C/Q prediction}}.
\]

Layer 1 is retrospective. Its High/Neutral/Low labels describe what the evaluated W-session region has already realized under the fixed Strategy. They must not be interpreted directly as bullish/bearish forecasts for the next W sessions.

## C and Q

For any retrospective evaluation region R,

\[
U_R=\max_{e\in I_R}E(e),
\]

\[
\boxed{C_R=U_R-B_{p,R}}.
\]

For a legal Entry e in the same region,

\[
\boxed{Q_e=U_R-E(e)}.
\]

C is larger-is-better. Q is smaller-is-better and Q is non-negative by construction.

The current interpretation is:

- **C** measures how much exploitable fixed-Strategy opportunity the evaluated region has contained relative to the periodic baseline. A high C does not mean that more opportunity must remain in the future.
- **Q** measures how far a legal Entry is from the best legal Entry available in the same retrospective region. Small Q means the Entry is close to the region upper bound; large Q means poorer timing relative to that upper bound.

Therefore C is a region-opportunity measure and Q is an Entry-quality / timing-distance measure. Neither quantity is itself a directional market forecast.

## Current gate reference structure

The gate uses two time scales.

### Short reference: rolling 90 sessions

For each evaluable historical state, use a rolling 90-trading-session reference and compute

\[
C^{90}_{40},\ C^{90}_{60},\ Q^{90}_{40},\ Q^{90}_{60}.
\]

The short-relative conditions are

\[
ShortHigh:\quad C\ge C^{90}_{60}\land Q\le Q^{90}_{60},
\]

\[
ShortLow:\quad C\le C^{90}_{40}\land Q\ge Q^{90}_{40}.
\]

The 90-session reference rolls continuously; it is not split into fixed non-overlapping blocks.

### Long reference: rolling 3 years

Use a trailing 3-year reference, operationalized as 756 trading sessions. The long reference uses the 50th percentile (median):

\[
C^{3Y}_{50},\ Q^{3Y}_{50}.
\]

Long-term confirmation is

\[
LongHigh:\quad C>C^{3Y}_{50}\land Q<Q^{3Y}_{50},
\]

\[
LongLow:\quad C<C^{3Y}_{50}\land Q>Q^{3Y}_{50}.
\]

This removes a locally relative High that is still poor on a longer historical scale, and removes a locally relative Low that is still strong on that longer scale.

## Locked classification

\[
\boxed{High=ShortHigh\land LongHigh}
\]

\[
\boxed{Low=ShortLow\land LongLow}
\]

Everything else is Neutral.

The **40/60 short-reference thresholds are retained**. A temporary sensitivity check that narrowed the Neutral region toward 50% produced nearly the same forward-W High result, but it did not improve the core interpretation enough to justify changing the baseline. The working Layer 1 therefore remains the original 40/60 definition.

For the 5-year TSLA audit the classified W30 population is:

\[
\boxed{High=77,\quad Neutral=146,\quad Low=80}
\]

across 303 evaluable rolling W30 states.

## Semantic interpretation of High and Low

The current evidence changes the interpretation of the labels, but not their formulas.

### High

High means that the evaluated W30 region has shown:

\[
\boxed{\text{high Strategy opportunity + relatively good Entry timing}}
\]

because C is high and Q is low relative to both the short and long references.

It must **not** be interpreted as "the next W sessions should also be good." The historical forward-W audit instead shows that High is associated with lower next-W C on average.

### Low

Low means that the evaluated W30 region has shown:

\[
\boxed{\text{low Strategy opportunity + relatively poor Entry timing}}
\]

because C is low and Q is high relative to both references.

Low must not be interpreted as "the next W sessions should remain bad." In the historical audit, Low was followed on average by higher C and lower Q than the just-completed Low region.

The audit also shows that Low regions can contain many legal Entries. This means Low does not imply "no Entry." It can instead mean that many legal Entries occurred but those Entries were inefficient relative to the best Entry in the region and the Strategy did not outperform the periodic baseline strongly.

## Past-W versus next-W audit

To test whether the retrospective Layer 1 state contains information about the immediately following equal-length region, each classified W30 state ending at t was paired with the completely non-overlapping next W30:

\[
Past_W=[t-W+1,t]
\]

\[
Future_W=[t+1,t+W].
\]

No Entry alignment and no Layer 2 model were used in this audit.

All 303 classified states had a complete next W30 for Entry-count analysis. Future C/Q was defined for 218 pairs because C/Q requires at least one legal Entry in the future W30.

### Overall relationship

Across the valid C/Q pairs:

\[
Corr_P(C_{past},C_{future})=-0.333
\]

\[
Corr_S(C_{past},C_{future})=-0.374
\]

and

\[
Corr_P(Q_{past},Q_{future})=-0.173,
\qquad
Corr_S(Q_{past},Q_{future})=-0.099.
\]

Across all 303 states, Entry-count correlation was also negative:

\[
Corr_P(N_{past},N_{future})=-0.329,
\qquad
Corr_S(N_{past},N_{future})=-0.330.
\]

The important conclusion is not that High means future High or Low means future Low. The important conclusion is that the historical C/Q state is **associated with the following W30**, and the dominant observed direction is negative rather than persistent.

In compact form:

\[
\boxed{\text{Past C/Q structure contains information about next-W opportunity, with historical mean-reverting association.}}
\]

This association is useful even though its direction differs from the original continuation intuition.

### High state forward behavior

For High states:

- count: 77;
- C/Q forward pairs: 51;
- past C mean: +4.20%;
- next-W C mean: -9.57%;
- past Q mean: 0.65%;
- next-W Q mean: 1.73%;
- past Entry count mean: 5.61;
- next-W Entry count mean: 5.43;
- next-W Entry count median: 7;
- next-W zero-Entry rate: 33.8%.

Thus High is historically associated with a materially lower-opportunity next W30. This is evidence of a relationship between the previous C/Q structure and the following region; it is not evidence that High should be treated as a bullish continuation label.

### Neutral state forward behavior

For Neutral states:

- count: 146;
- C/Q forward pairs: 112;
- past C mean: -5.61%;
- next-W C mean: -6.52%;
- past Q mean: 2.01%;
- next-W Q mean: 2.48%;
- past Entry count mean: 7.73;
- next-W Entry count mean: 7.43;
- next-W zero-Entry rate: 18.5%.

Neutral showed the least dramatic state transition on average.

### Low state forward behavior

For Low states:

- count: 80;
- C/Q forward pairs: 55;
- past C mean: -21.12%;
- next-W C mean: -3.70%;
- past Q mean: 3.55%;
- next-W Q mean: 2.39%;
- past Entry count mean: 12.36;
- next-W Entry count mean: 7.91;
- next-W Entry count median: 7;
- next-W zero-Entry rate: 17.5%.

Low therefore showed substantial average recovery in C and improvement in Q during the following W30, together with a reduction in Entry frequency.

Within Low states, the reversal was particularly strong for Q and Entry count:

\[
Corr_P(Q_{past},Q_{future})=-0.720
\]

and

\[
Corr_P(N_{past},N_{future})=-0.593.
\]

This supports interpreting Low as a retrospectively inefficient / crowded Entry region that can be followed by normalization or recovery, rather than as a forward bearish label.

## 50% sensitivity check

A temporary sensitivity test changed only the short-reference cut from 40/60 to approximately 44.1/55.9 while preserving the same W30, 3Y median confirmation, next-W construction, C/Q calculation, and data period.

The key High result was almost unchanged:

\[
C^{future}_{High}:\ -9.57\%\rightarrow -9.48\%.
\]

The state counts changed from

\[
77/146/80
\]

to

\[
78/137/88
\]

for High/Neutral/Low respectively. Low next-W C changed more materially, from -3.70% to -5.94%.

Therefore the sensitivity check did **not** overturn the main conclusion that High is followed by weak next-W C. Because the original 40/60 definition already exhibits the association and is the locked baseline, the experiment is closed and Layer 1 remains at 40/60.

## Implication for Layer 1 meaning

The forward-W audit supports the following distinction:

\[
\boxed{High/Neutral/Low = retrospective Strategy state}
\]

not

\[
\boxed{High/Neutral/Low = forward market direction}
\]

In particular:

\[
\boxed{High\neq future\ bullish}
\]

\[
\boxed{Low\neq future\ bearish}
\]

The useful result is the existence of a historical relationship between past C/Q structure and the following W30, even though the relationship is primarily mean-reverting rather than continuation-like.

## Gate pass rule

\[
\boxed{High\rightarrow PASS}
\]

\[
\boxed{Low\rightarrow PASS}
\]

\[
\boxed{Neutral\rightarrow FILTER}
\]

High and Low must remain distinct downstream states.

## Relationship to Layer 2

For a current decision point t with W=30, Layer 2 uses causal price-volume information available at the Entry and learns the Entry-centered C/Q target after the centered region is completed historically.

Layer 1 selects the non-Neutral historical contexts. Layer 2 performs the actual price-volume prediction problem. Layer 1 itself has no neural network.

The forward-W audit should not be treated as proof of independent predictive significance because the 303 Layer 1 states are stride-1 rolling windows and therefore overlap heavily across adjacent t. The result is descriptive historical evidence of association and temporal structure, not yet an independent OOS predictive claim.

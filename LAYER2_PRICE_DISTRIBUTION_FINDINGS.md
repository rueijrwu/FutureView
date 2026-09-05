# Layer2 Price Distribution — Current Findings

Date: 2026-09-04
Branch: `layer2-price-distribution-v1`

This note records the current interpretation of the Layer2 price-distribution experiments. It is intentionally neutral and must be read together with `LAYER2_EXPERIMENT_VARIABLES.md`.

## 0. Canonical experiment conditions

`LAYER2_EXPERIMENT_VARIABLES.md` is now the single source of truth for experiment variables and information-boundary requirements.

The following names must not be used interchangeably:

- `W`: Layer1 C/Q window length.
- `h`: Layer2 future-return target horizon.
- `MODEL_HISTORY`: normalized P/V input length.
- `RETRAIN_DAYS` / `ROLL_DAYS`: chronological retraining cadence.
- `retain` / `memory`: number of most recent eligible training samples retained at each retrain.

Any reported experiment must state all five where applicable.

The previous working setup often used:

```text
MODEL_HISTORY = 90 sessions
retain/memory = 150 eligible samples
RETRAIN_DAYS   = 10 or 15 sessions
Layer1 scope   = H only
```

However, `retain=150` was never established by a dedicated retain-length sweep and must not be described as optimal.

## 1. Current research scope

Layer1 and Layer2 have different roles.

Layer1 uses the fixed Strategy and Strategy-path statistics to identify regions where Strategy-relative structure is sufficiently non-neutral to justify further analysis. U/C/Q are Strategy-relative quantities.

The current research scope is intentionally narrow:

> Study only the H-selected region and ask whether normalized recent price/volume structure contains a learnable nonlinear signal associated with the distribution of future price changes.

Other Layer1 regions are out of scope. Layer2 is not asked to predict the Layer1 label itself.

Current Layer2 inputs remain normalized historical price/volume only. Handcrafted indicators are not part of the approved baseline.

## 2. Entry-relative and exit-relative C/Q

A single C/Q characterization was found to be insufficient. Two views are retained:

- entry-relative C/Q: characterizes opportunity relative to entry/path construction;
- exit-relative C/Q: characterizes opportunity relative to exit/path construction.

Q keeps its historical Strategy-relative meaning where applicable:

```text
Q = (U - P) / |C|
```

The entry and exit views are combined only to determine whether a window belongs to the H-focused study population. Conflicting or neutral combinations are excluded.

## 3. Historical Layer2 observations before the leakage audit

Several chronological Layer2 experiments produced positive ranking separation inside H. In the previous 8-year, 90D-input, 150-memory setup, changing retraining cadence from 15D to 10D improved the observed H-only Spearman from about 0.262 to about 0.292 while OOS n remained 131.

Later horizon sweeps also produced strong apparent relationships. For example, before the leakage audit:

```text
W=30, h=30D   Spearman ≈ 0.635
W=45, h=45D   Spearman ≈ 0.570
W=60, h=45D   Spearman ≈ 0.631
```

For the 45D target specifically, the strongest observed pre-leakage configuration was:

```text
W=60, h=45D, Spearman ≈ 0.631
```

These are now historical observations only. They are not validated OOS performance claims.

## 4. Leakage audit and current validity status

The strict audit found that the previous pipeline violated causal information boundaries in multiple places.

### 4.1 Exact duplicates

No exact duplicate cutoff rows or duplicate windows were observed in the audited W=30 eligible set.

### 4.2 Sliding-window overlap

Adjacent W=30 windows often differed by only one session, giving 29/30 = 96.67% overlap for step-1 neighbors. This is not itself direct lookahead leakage, but it means nominal sample count is much larger than effective independent sample count. De-overlapped OOS checks are required.

### 4.3 Layer2 target maturity

The previous rolling trainer selected rows using `cutoff < OOS block start`. For horizon `h`, the stricter causal condition is:

```text
cutoff + h < OOS block start
```

Under W=30 and the previous 150-memory setup, contaminated training-row fractions increased with horizon and reached about 8.11% for h=30D and 11.85% for h=45D.

Therefore all previous horizon-performance values must be rerun after target purge.

### 4.4 Layer1 entry-side path lookahead

The audit showed that entry-relative C/Q could use campaign outcomes whose final exits occurred after the current window end. In the audited W=30 construction, about 42.43% of entry-C/Q windows contained at least one such future-completing path; about 33.12% of entry-side path members were future-completing, with maximum exit lookahead of 48 sessions.

Exit-relative C/Q showed zero future-path lookahead under the same audit.

### 4.5 Retrospective extrema

The current local-extrema construction is retrospective and can require up to 10 future sessions to confirm an extremum. It must therefore either be made causal or assigned to its confirmation time before the full pipeline can be considered real-time valid.

## 5. Current interpretation

Because the leakage exists upstream as well as inside Layer2 training, previous high Spearman and top/bottom separation cannot be used as evidence of genuine deployable OOS predictive strength.

The correct status is:

```text
Historical evidence suggests potentially learnable H-conditioned structure,
but the magnitude of that structure is unknown until the causal pipeline is rerun.
```

It is not correct to conclude either that the model works or that it fails from the current contaminated results.

## 6. Retain / memory status

The previous working baseline used:

```text
retain = 150 eligible samples
```

but this was inherited as a working setting rather than proven optimal. The earlier observation that longer overall history weakened performance and more frequent retraining helped motivated a regime-local hypothesis, but that hypothesis itself must also be rechecked after causal fixes.

After the causal boundary is repaired, the planned dedicated retain sweep is:

```text
retain ∈ {30, 50, 75, 100, 150}
```

During that sweep, other conditions should remain fixed so retain length is the only changed variable.

## 7. Evaluation definitions

The Layer2 score is primarily a ranking variable unless probability calibration is separately established.

- `Spearman`: rank correlation between model score and realized future return.
- `realized up-rate`: fraction of actual future returns greater than zero inside a score bucket. This is not prediction accuracy.
- `top-bottom return gap`: difference in realized mean return between high-score and low-score buckets.
- `fold consistency`: whether the ordering persists across chronological OOS segments.
- `de-overlapped result`: robustness check after reducing highly overlapping neighboring samples.

A good result should therefore satisfy all of the following rather than merely produce one high Spearman value:

```text
causal / no leakage
+ positive OOS rank separation
+ top/bottom realized-distribution separation
+ chronological fold consistency
+ robustness to de-overlapping
+ robustness to nearby parameter values
```

## 8. Required sequence before new performance claims

The next sequence is fixed:

```text
1. Make extrema causal or shift them to confirmation time.
2. Rebuild deterministic paths under that information boundary.
3. Rebuild entry-relative and exit-relative C/Q without future campaign outcomes.
4. Reconstruct H from the causal dual-C/Q definitions.
5. Enforce Layer2 target maturity: cutoff + h < OOS block start.
6. Rerun the W × h sweep.
7. Rerun de-overlapped OOS robustness checks.
8. Only then sweep retain ∈ {30,50,75,100,150} and nearby retraining cadences.
```

Until these steps are complete, the pre-leakage W×h results remain experiment history, not validated conclusions.

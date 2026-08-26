# FutureView — Implementation Reference

Last consolidated: 2026-08-25

This is the canonical implementation document. Research definitions, interpretation, evidence, and current scientific direction belong in `RESEARCH.md`.

## 1. Separation of concerns

```text
RESEARCH.md  -> what is being asked, what labels mean, what evidence supports
                current conclusions, and what is not yet decided

IMPLEMENT.md -> how the repository constructs data/labels, models, validation,
                workflows, commands, and reproducible experiments
```

Implementation must follow the research definitions; code convenience must not silently redefine the research object.

## 2. Data and causality

Primary data are OHLCV-derived causal features. A model sample may use only information observable at the prediction/Entry timestamp.

Forbidden model inputs include future return, future L/U/μ/Q labels, future exits, future extrema, future target statistics, and test-distribution information.

Formal evaluation uses chronological/purged splits. Random train/test splitting is forbidden.

For the current three-month live holdout experiment, historical reference samples must satisfy:

```text
entry_target_end < holdout_start
```

so the complete 60-session label path matures before the holdout begins.

## 3. Strategy 1 executable semantics

The current formal entry-level research engine uses daily data and three equal capital tranches.

Entry candidate:

```text
Close > MA5
Close > MA10
Close > MA20
MA5 > MA10
MA10 > MA20
```

All qualifying sessions are formal Entry candidates. Legacy event fields may remain for compatibility but must not override the current research definition.

Legal add-on references are generated from confirmed local maxima:

```text
Close[i] > Close[i-1]
Close[i] >= Close[i+1]
```

Reference configurations include no add-on, one local-max reference, or two local-max references with index gap > 5.

For the second add-on:

```text
first_gap  = Addon1Price - EntryPrice
second_gap = Addon2Price - Addon1Price
first_gap > 0
second_gap > 0
abs(second_gap / first_gap - 1) <= 0.20
```

Execution priority:

```text
eligible MA10 full exit
> eligible MA5 half exit
> addon action
```

Three-session cooldown and horizon-end liquidation remain enforced.

## 4. Label construction

For an Entry `e` and 60-session horizon, enumerate all unique legal realized Strategy 1 paths `P(e,60)`.

Construct:

```text
EntryLower / L
  = min(Return(path))

EntryUpper / U
  = max(Return(path))

EntryNetExpectedReturn / μ
  = mean(Return(path))

EntryPathProfitabilityRate / Q
  = mean(Return(path) > 0)

LegalRealizedPathCount
  = count(unique legal paths)
```

Legacy code/output names such as `target_success_probability` may remain for compatibility, but documentation and new analysis should use the preferred research terminology.

At the window level:

```text
LowerBound(W) = worst legal Strategy 1 path
UpperBound(W) = best legal Strategy 1 path
```

Do not substitute DCA/random entry for either bound.

## 5. Historical reference distribution workflow

Canonical commands currently include:

```bash
futureview-strategy1-reference-distribution
futureview-strategy1-reference-distribution-fast
futureview-strategy1-fixed-entry-compare
```

Reference-distribution output should report symbol-specific sample counts and descriptive statistics for `L`, `U`, and `μ`, including at least:

```text
mean
P10
P25
P50
P75
P90
```

The current reference comparison includes SPY, QQQ, and SMH.

No percentile is automatically a trading threshold. Threshold logic must not be introduced into the implementation until it has been explicitly approved at the research layer.

## 6. DCA comparator

Current fixed comparator:

```text
Day 0 / Day 20 / Day 40
three equal entries
hold to Day 59
```

This comparator is external to the Strategy 1 legal path set and is used only to measure strategy-relative headroom.

## 7. Model baseline

The historically tested joint CNN is retained as an implementation baseline.

Representative architecture:

```text
multi-scale 1D CNN
causal O/H/L/C/V-derived channels
kernel scales approximately 5 / 10 / 20 sessions
```

Earlier experiments used a 50-session input context and Sliding-260 training policy. These are experimental settings, not immutable research definitions.

A fixed low-dimensional Summary Ridge baseline uses 20 causal features across 5/10/20/50-session lookbacks:

```text
close_sum
close_std
range_mean
abs_close_mean
volume_z_mean
```

Training-fold-only standardization is required.

## 8. Validation and model evaluation

Historical workflows include:

```bash
futureview-strategy1-success-model
futureview-strategy1-success-model-oos-diagnostics
```

Formal comparisons must use identical OOS dates where models are compared, multiple fixed seeds where stochastic training is involved, and purged chronological folds.

Metrics are not automatically accepted because they are standard ML metrics. The implementation may calculate diagnostics, but research interpretation must follow `RESEARCH.md`.

In particular, historical evidence showed that MAE can improve while ranking quality deteriorates. MAE should therefore remain a diagnostic unless explicitly promoted by a later research decision.

## 9. Historical experimental implementations

### Daily vs higher-frequency

The frequency experiment compared approximately the same 50-session context using daily bars and two regular-session intraday observations per session. A parameter-matched dilation control was also tested.

Historical commands:

```bash
futureview-strategy1-frequency-compare
futureview-strategy1-frequency-compare-massive
```

Alpaca cache location:

```text
.cache/futureview/alpaca/
```

Required Alpaca credentials are supplied through environment variables and must never be committed.

Current research status: higher-frequency advantage not established; daily remains the primary baseline.

### CNN + Summary20 fusion

Historical command:

```bash
futureview-strategy1-summary-fusion
```

The fusion architecture concatenated the CNN representation with the 20 fixed causal summary features. It remains a failed/hold research variant and should not replace the baseline architecture without a new predeclared experiment.

### OOS portfolio/gate experiments

Historical portfolio work compared always-on Strategy 1, Summary-Ridge-filtered Strategy 1, CNN-filtered Strategy 1, and hindsight references.

Tested CNN gates included absolute training-distribution P80, expanding causal rank P80, and recent-OOS rank60 P80. These are historical experiments only. They must not become default policy or be further tuned on the same OOS sample and presented as fresh validation.

Planning/gate logic is currently downstream of the reduced L/μ/U research problem.

### SMH daily Ridge L/μ/U audit — 2026-08-25

Implementation:

```text
symbol = SMH
frequency = daily
input = existing causal 50-session x 5 feature tensor, flattened
model = deterministic Ridge regression
alpha = 10
three separate targets = L, μ, U
no Q target
no composite score
standardization = training-fold only
history eligibility = complete 60-session label must end before 3-month live holdout
validation = purged chronological folds
purge = 60 raw sessions
folds = 4
fold test size = 30 entries
```

Evaluation is deliberately target-local. For each of `L`, `μ`, and `U`, the audit reports only:

```text
OOS Spearman(predicted target, realized target)
realized target mean for predicted Top 20%
realized target mean for predicted Bottom 20%
Top20 - Bottom20 realized-target separation
```

Workflow:

```text
.github/workflows/strategy1-smh-ridge-lmu.yml
```

Module:

```text
python -m futureview.strategy1_smh_ridge_lmu
```

Run 1 (`32914790066`) completed successfully on commit `720fd7eb1fd3e85ae7a48718ead6d8f894f4b31c`.

Observed four-fold summary:

```text
L:
  mean Spearman = -0.164850
  positive Spearman folds = 1/4
  mean Top20 - Bottom20 = -0.016108
  positive-separation folds = 1/4

μ:
  mean Spearman = -0.185762
  positive Spearman folds = 1/4
  mean Top20 - Bottom20 = -0.010018
  positive-separation folds = 1/4

U:
  mean Spearman = -0.174416
  positive Spearman folds = 0/4
  mean Top20 - Bottom20 = -0.005436
  positive-separation folds = 2/4
```

This implementation result means only that this first fixed Ridge configuration does not provide positive OOS ranking/separation evidence for the three targets. It must not be generalized into a claim that causal OHLCV contains no predictive information for L/μ/U.

## 10. Current implementation priorities

The code should support the research sequence without prematurely adding planning complexity:

```text
1. reproducibly construct symbol-specific historical L/μ/U distributions
2. preserve strict three-month holdout + 60-session maturity isolation
3. quantify Strategy 1 headroom versus simple baselines for SPY/QQQ/SMH
4. build causal supervised targets for L/μ/U
5. evaluate OOS ranking/estimation one target at a time
6. retain Q for later robustness/sensitivity experiments
```

Do not introduce or optimize these without a separate research decision:

```text
composite L/μ/U score
fixed percentile entry gate
Q55/adaptive gate
trade-frequency target
portfolio overlap policy
position sizing
symbol allocation
entry-delay planner
```

## 11. Reproducibility rules

- Use fixed data ranges for formal experiments when possible; provider-relative `period=` windows are acceptable for smoke/debug only.
- Record symbol, horizon, lookback, holdout boundary, purge, train policy, OOS dates, seeds, and model version.
- Never fit normalization on OOS/test data.
- Never use future OOS predictions to define a causal threshold.
- Never use the live three-month holdout to choose historical percentiles/thresholds.
- Repeated tuning on an OOS block converts it into development data.
- Preserve old experiment outputs as historical evidence, but do not let legacy field names redefine current research semantics.

## 12. Documentation rule

New research conclusions go to `RESEARCH.md`.

New code architecture, commands, workflows, provider setup, reproducibility details, or implementation caveats go to `IMPLEMENT.md`.

Do not create new root-level explanatory Markdown files for individual experiments unless there is a compelling reason. Prefer adding a dated subsection to one of these two canonical documents so the project does not fragment again.

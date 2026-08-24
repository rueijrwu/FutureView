# FutureView CNN Trend Research Plan

Last updated: 2026-08-24

## 1. Reset Scope

This branch is a clean research restart.

The previous momentum ranking, sector-selection, portfolio-construction, pyramiding, options, frontend, and production workflow logic are intentionally excluded from the initial research scope.

Phase 1 has one question only:

> Using only recent SPY price and volume history, can a small CNN identify future 3-week to 3-month bullish trends with a materially higher out-of-sample successful rate than the unconditional SPY baseline?

If SPY itself cannot produce a useful and stable out-of-sample trend signal, do not expand to QQQ, sector ETFs, individual stocks, portfolio construction, or options.

## 2. Technical Baseline

Primary language:

```text
Python
```

Primary ML framework:

```text
PyTorch
```

Local research environment:

```text
CPU first
GPU only when repeated experiments justify it
Tesla P100 available
CUDA ecosystem available up to CUDA 12.9
cuDNN 9.x
```

The initial SPY dataset and CNNs are small enough that CPU execution is the default. GPU acceleration is optional and should be enabled only if walk-forward, repeated seeds, or hyperparameter experiments become materially slow.

Use standard PyTorch modules first. Do not write custom CUDA kernels during Phase 1.

## 3. Core Research Rules

1. SPY only in Phase 1.
2. Price and volume only.
3. Pure technical-analysis research: no fundamentals, news, macro, sentiment, options, breadth, analyst data, or alternative data.
4. PyTorch CNN is the primary predictive model.
5. The primary target is future trend quality, not next-day direction.
6. The intended trading horizon is 3 weeks to 3 months, approximately 15-60 trading sessions.
7. Evaluate multiple forward horizons: 15, 30, 45, and 60 sessions.
8. Use strict chronological, purged walk-forward validation. Never randomly shuffle overlapping time-series samples.
9. Do not assume older market data is equally useful. Test recent-history length empirically.
10. Optimize for out-of-sample trend discrimination and successful rate, not training accuracy.
11. Keep the first models deliberately small.
12. QQQ, sectors, and stocks are deferred until SPY succeeds.

## 4. Data Scope

Initial instrument:

```text
SPY only
```

Allowed raw model information:

```text
Open
High
Low
Close
Volume
```

Derived transformations are allowed only when they are produced entirely from historical price and volume available at or before the prediction date.

Examples:

```text
returns
relative OHLC geometry
moving averages
volume averages
range measures
price/volume normalization
```

Future-path quantities may be used only to construct labels and evaluation metrics.

### Data sources

Preferred history:

```text
Yahoo Finance or another reliable source: up to ~5 recent years of SPY daily OHLCV
Massive: recent ~2 years for cross-checking and/or current updates
```

Before reconciling sources, verify:

```text
trading dates
OHLC values
volume
adjustment conventions
missing sessions
corporate-action treatment
```

Produce one canonical SPY daily series before training.

## 5. Recency Research

Older market regimes may not represent the current market well, so training-history length is itself a research variable.

Primary comparison:

```text
1-year rolling history
2-year rolling history
3-year rolling history
5-year rolling history
5-year history with recency-weighted loss
```

All variants must use identical test dates, preprocessing, target definitions, architecture, optimizer, and evaluation logic. Only training-history treatment should differ.

## 6. Input Representation

Initial lookback:

```text
50 trading sessions
```

Baseline tensor:

```text
50 x 5
```

Do not feed absolute SPY price levels directly without normalization.

Candidate causal price channels:

```text
Open / previous Close - 1
High / previous Close - 1
Low / previous Close - 1
Close / previous Close - 1
```

or equivalent log-return representations.

Candidate volume normalization:

```text
log(volume)
relative volume using trailing history
causal z-score using trailing history
```

No normalization may use future information.

## 7. Phase-1 Models

Two CNN models must be implemented together and evaluated under identical conditions.

### Model A — Joint OHLCV CNN

Purpose: establish the cleanest CNN baseline.

```text
Input: past 50 sessions OHLCV

            -> Conv1D kernel 5  -\
            -> Conv1D kernel 10 -- concat -> fusion -> pooling -> dense -> trend outputs
            -> Conv1D kernel 20 -/
```

Price and volume are treated as channels in one shared representation.

### Model B — Separate Price / Volume CNN

Purpose: test whether modeling price structure and volume structure separately improves future-trend detection.

```text
Price branch: OHLC
    -> multi-scale Conv1D 5/10/20

Volume branch: Volume
    -> multi-scale Conv1D 5/10/20

Price features + Volume features
    -> fusion
    -> pooling
    -> dense
    -> trend outputs
```

The key Phase-1 comparison is:

```text
Model A: joint OHLCV representation
vs
Model B: separate price and volume representations
```

Do not add extra architecture complexity unless this comparison has been completed.

## 8. Prediction Horizons

Because the intended trading strategy holds approximately 3 weeks to 3 months, the CNN should not optimize only for a 20-day future.

The model should produce horizon-specific future trend estimates:

```text
Trend15
Trend30
Trend45
Trend60
```

Conceptually:

```text
Past 50D OHLCV
      -> CNN
      -> Trend15
      -> Trend30
      -> Trend45
      -> Trend60
```

Do not immediately collapse these four outputs into one weighted score. First evaluate each horizon independently.

This allows the model to distinguish, for example:

```text
short-lived acceleration
medium-duration swing trend
persistent multi-month trend
```

## 9. Trend Ground Truth

Defining realized trend quality is the most important modeling decision.

A successful bullish trend should not mean only that the final price is higher.

A high-quality trend should generally combine:

```text
positive forward return
persistent directional movement
limited adverse excursion
reasonable path efficiency
```

For each horizon h in {15, 30, 45, 60}, calculate at least:

```text
ForwardReturn_h
MAE_h
MFE_h
TrendEfficiency_h
```

A useful path-efficiency definition is:

```text
TrendEfficiency_h =
    (Close[t+h] - Close[t])
    /
    sum(abs(Close[i] - Close[i-1])) over the forward h-session path
```

A smooth directional rise should score better than a highly erratic path ending at the same final return.

### Continuous trend target

The CNN should primarily predict a continuous realized trend-quality target rather than a next-day binary direction.

Conceptually:

```text
FutureTrendQuality_h
= reward(forward return)
+ reward(path efficiency)
- penalty(adverse excursion)
```

The exact formula and coefficients are research hypotheses and must be documented and tested for robustness.

## 10. Successful Trend Definition

Successful rate is an evaluation metric, not the only training target.

For each horizon h, define:

```text
SuccessfulTrend_h = 1
```

when the realized future path satisfies a predeclared combination of:

```text
minimum forward return
maximum acceptable MAE
minimum trend efficiency
```

Otherwise:

```text
SuccessfulTrend_h = 0
```

Do not tune these thresholds solely to maximize the headline successful rate.

Use at least two predeclared evaluation definitions, for example a looser and a stricter definition, to test whether model quality is robust to the exact success threshold.

## 11. Successful Rate

For a selected group of predictions:

```text
Successful Rate
= number of SuccessfulTrend signals
  / number of evaluated signals
```

The most important comparison is not the raw successful rate by itself, but the improvement over the unconditional SPY baseline for the same horizon and dates.

Define:

```text
BaselineSuccessRate_h
= successful future trends across all eligible SPY dates
```

Then evaluate model-selected subsets such as:

```text
top 50% TrendScore
top 30%
top 20%
top 10%
```

The key evidence is:

```text
SuccessRate(high TrendScore)
>> BaselineSuccessRate
```

and this improvement must repeat across walk-forward folds.

A model that produces a tiny number of signals with a superficially high success rate is not automatically useful.

## 12. Primary Phase-1 Goal

The highest-priority empirical property is:

```text
higher predicted TrendScore
-> higher realized Successful Rate
```

Ideally, TrendScore buckets should also show:

```text
higher realized trend quality
higher forward return
better MFE
controlled MAE
higher path efficiency
```

But successful-rate discrimination is the primary Phase-1 gate.

If high TrendScore does not materially and consistently improve successful rate over baseline SPY behavior, the model is not good enough to expand.

## 13. Validation Rules

Random train/test splitting is forbidden because adjacent 50-day windows overlap heavily.

Required method:

```text
Train on past data only
Validate on the next chronological block
Purge future-label overlap at boundaries
Test on a later untouched block
Roll forward
Repeat
```

All results must be reported out-of-sample.

The final conclusion must not depend on one favorable market period.

## 14. Model-A vs Model-B Evaluation

A and B must use:

```text
same SPY data
same 50-day lookback
same 15/30/45/60 horizons
same targets
same walk-forward folds
same optimizer
same learning rate policy
same epoch limit
same early stopping
same random seeds
same history-window experiment
```

Only the representation architecture differs.

Required comparison for each horizon:

```text
baseline successful rate
Model A top-score successful rate
Model B top-score successful rate
success-rate lift over baseline
sample count / coverage
fold stability
```

Prefer the simpler model unless Model B shows reproducible incremental value.

## 15. Initial Training Defaults

First implementation should favor stable defaults over tuning.

Suggested starting point:

```text
Optimizer: AdamW
Loss: Huber / SmoothL1 for continuous trend targets
Batch size: ~32
Epoch limit: ~100
Early stopping: validation patience ~10
Activation: ReLU or GELU
Dropout: small, approximately 0.1-0.2
Device: CPU
```

These are starting defaults, not permanent strategy parameters.

## 16. CPU-First Policy

Initial execution should use:

```text
device = cpu
```

Reasons:

```text
SPY daily dataset is small
models are intentionally small
debugging chronology and labels matters more than speed
CPU improves implementation simplicity during Phase 1
```

GPU becomes useful when experiment volume grows, for example:

```text
many walk-forward folds
x multiple training-history windows
x Model A/B
x repeated random seeds
x multiple label variants
```

At that point enable the Tesla P100 through PyTorch CUDA without changing the research logic.

## 17. Primary Evaluation Output

Every experiment should report, separately for 15/30/45/60 sessions:

```text
BaselineSuccessRate
TrendScore distribution
TrendScore quantiles / deciles
signal count
coverage
successful rate by score bucket
successful-rate lift over baseline
mean forward return
median forward return
MAE
MFE
TrendEfficiency
walk-forward fold results
```

The most important table should resemble:

```text
Horizon | Score bucket | Signals | Success rate | Baseline | Lift
15D     | top 20%      | ...     | ...          | ...      | ...
30D     | top 20%      | ...     | ...          | ...      | ...
45D     | top 20%      | ...     | ...          | ...      | ...
60D     | top 20%      | ...     | ...          | ...      | ...
```

## 18. Baseline Models

The CNN must also outperform simple price/volume baselines.

At minimum compare against:

```text
unconditional SPY baseline
simple recent-return trend score
simple MA-based price trend score
small linear model using the same allowed price/volume data
```

This prevents attributing value to CNN complexity when a simpler price trend rule performs equally well.

## 19. Initial Experiment Matrix

### CNN architecture

```text
Model A: joint OHLCV CNN
Model B: separate price / volume CNN
```

### Training-history window

```text
1Y
2Y
3Y
5Y
5Y recency-weighted
```

### Prediction horizons

```text
15D
30D
45D
60D
```

### Device

```text
CPU first
GPU only if experiment throughput requires it
```

Do not broaden the matrix until these experiments are understood.

## 20. Local Python / PyTorch Structure

Suggested initial repository structure:

```text
PLAN.md
pyproject.toml
README.md
src/
  futureview/
    data.py
    features.py
    labels.py
    datasets.py
    models.py
    train.py
    walkforward.py
    evaluate.py
    device.py
configs/
  baseline.yaml
scripts/
  download_spy.py
  train_spy.py
  evaluate_spy.py
tests/
```

Responsibilities:

```text
data.py        -> canonical SPY OHLCV loading and source reconciliation
features.py    -> causal price/volume normalization\labels.py      -> 15/30/45/60 trend-quality, success, MAE, MFE, efficiency labels
datasets.py    -> PyTorch Dataset and 50-session sequence construction
models.py      -> Model A and Model B
train.py       -> PyTorch training loop, seeds, checkpoints
walkforward.py -> purged chronological fold generation
evaluate.py    -> successful-rate and trend-quality audits
device.py      -> CPU default and optional CUDA selection
```

## 21. Reproducibility

Record for every experiment:

```text
Python version
PyTorch version
execution device
CUDA/cuDNN versions if GPU is used
GPU model if GPU is used
random seed
training date range
validation date range
test date range
training-history length
model configuration
target configuration
success-definition configuration
```

Save configuration, metrics, and predictions with each run.

## 22. Expansion Gate

Do not add QQQ, IWM, sector ETFs, individual stocks, sector weights, or per-stock context weights during Phase 1.

Expansion is allowed only if the SPY CNN demonstrates reproducible out-of-sample value.

The minimum qualitative gate is:

```text
high TrendScore groups consistently produce materially higher successful rates than unconditional SPY baseline
```

across multiple walk-forward folds and preferably across multiple 15-60 day horizons.

If SPY fails this test:

```text
do not add more instruments
revise target definition
revise input representation
revise model architecture
revise training-history assumptions
```

Adding QQQ or stocks must not be used to hide a weak SPY trend detector.

## 23. Explicitly Deferred

Until the SPY expansion gate is passed, do not implement:

```text
QQQ weighting
sector ETF weighting
stock-specific context weights
individual-stock CNNs
stock ranking
portfolio construction
pyramiding
options acceleration
broker execution
frontend dashboard
production workflows
```

These are future phases only.

## 24. First Implementation Milestones

1. Build the canonical recent SPY daily OHLCV dataset, preferably up to 5 years.
2. Cross-check Yahoo Finance and Massive overlap where practical.
3. Implement causal 50-session price/volume preprocessing.
4. Implement 15/30/45/60 future trend-quality labels.
5. Implement 15/30/45/60 successful-trend evaluation labels.
6. Calculate unconditional SPY baseline successful rates for every horizon.
7. Implement simple non-CNN price/volume baselines.
8. Implement Model A.
9. Implement Model B.
10. Implement strict purged walk-forward evaluation.
11. Run CPU-based A/B baseline experiments.
12. Run 1Y/2Y/3Y/5Y training-history comparisons.
13. Run 5Y recency-weighted comparison.
14. Produce TrendScore bucket vs Successful Rate reports for 15/30/45/60 days.
15. Decide whether SPY passes the expansion gate.
16. Use GPU only if experiment throughput becomes a practical bottleneck.

## 25. Phase-1 Success Criterion

The first milestone is not portfolio return.

The central question is:

> Can the CNN reliably identify SPY states whose future 3-week to 3-month trend success probability is materially higher than normal?

A strong result should show:

```text
TrendScore increases
-> Successful Rate increases
-> successful-rate lift over baseline is material
-> improvement persists across walk-forward folds
-> result is not caused by a tiny number of signals
```

Additional supporting evidence:

```text
better forward return
better MFE
controlled MAE
higher trend efficiency
```

If these conditions are not met, Phase 1 is not complete and the project should not expand beyond SPY.

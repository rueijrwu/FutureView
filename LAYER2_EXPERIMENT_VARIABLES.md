# Layer2 Experiment Variables Registry

Date: 2026-09-04
Branch: `layer2-price-distribution-v1`

This file exists to keep experiment variables unambiguous and to separate observed results from validated conclusions.

## Core variables

- `W`: Layer1 C/Q window length in trading sessions. Examples tested: 20, 30, 45, 60.
- `h`: Layer2 future-return prediction horizon in trading sessions. Examples tested: 5, 10, 15, 20, 25, 30, 45.
- `MODEL_HISTORY`: raw normalized price/volume input length for Layer2. Current working value: 90 sessions.
- `L2_TRAIN_W`: Layer2 rolling training lookback in trading sessions. **Approved current definition: 30 sessions immediately preceding the current/OOS date.** Training membership is therefore time-window based, not a fixed count of the most recent N eligible samples.
- `RETRAIN_DAYS` / `ROLL_DAYS`: cadence between chronological retraining points. Tested values include 15D and 10D; these are update cadences and are distinct from the 30-session Layer2 training lookback.
- `retain` / `memory`: legacy terminology from intermediate experiments that treated training history as a fixed number of eligible samples (for example 150). This is **not the approved current Layer2 training definition** and must not be used as the baseline unless explicitly reintroduced as a separate experiment.
- `Layer1 scope`: current research is H-only. Other Layer1 regions are out of scope.
- `Layer2 output`: ranking / distribution outputs such as q10, q50, q90 and P(up); P(up) should not be interpreted as calibrated probability unless calibration is separately validated.
- `evaluation`: chronological OOS only. Realized up-rate means the fraction of actual future returns above zero inside a score bucket; it is not classification accuracy.

## Approved Layer1 window-path definition

For a Layer1 window `[start, end]`, a Strategy path is legal for C/Q only when the entire path lies inside the window:

```text
start <= entry_index <= final_exit_index <= end
```

Consequences:

1. An unfinished path with `final_exit_index > end` is excluded.
2. For an exit-side view, a path whose entry occurred before `start` is excluded even if its exit lies inside the window.
3. No additional `final_exit + 10D` availability shift is part of the approved definition.
4. The retrospective 5D/10D extrema semantics of the Strategy are not changed by this rule.

Under this definition, entry-side and exit-side C/Q are evaluated from the same legal complete-path set. Their separate names are retained for continuity, but they should not be assumed to provide different path populations unless a future definition explicitly changes that.

## Approved Layer2 rolling-training definition

At an OOS/retraining date `t`, Layer2 training candidates come only from the immediately preceding 30 trading sessions:

```text
t - 30 <= sample_cutoff < t
```

This is a **30-session time lookback**, not `memory=30 samples` and not `memory=150 samples`.

The 90-session normalized P/V input for each sample remains a separate variable:

```text
MODEL_HISTORY = 90 sessions
```

Thus:

```text
90D = input feature history for each sample
30D = rolling time window from which Layer2 training samples are drawn
10D / 15D = how often the model is retrained
h = future-return target horizon
```

Any target-maturity / purge rule is a separate research boundary and must not be silently bundled into this 30D training-window definition.

## Pre-leakage W × h observation — NOT VALIDATED

Before the leakage audit, the 45D future horizon showed the following Spearman values across Layer1 W:

| W | h=45D Spearman |
|---:|---:|
| 20 | 0.491 |
| 30 | 0.430 |
| 45 | 0.570 |
| 60 | 0.631 |

Thus the strongest *observed pre-leakage* setting for the 45D target was:

```text
W=60, h=45D, Spearman≈0.631
```

For W=45 specifically, the strongest horizon observed in the earlier sweep was also 45D, with Spearman≈0.570.

These values are retained only as experiment history. They must not be used as evidence of genuine OOS predictive strength until the revised Layer1 window-path rule and the exact Layer2 training boundary are rerun consistently.
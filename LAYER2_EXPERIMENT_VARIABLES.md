# Layer2 Experiment Variables Registry

Date: 2026-09-04
Branch: `layer2-price-distribution-v1`

This file exists to keep experiment variables unambiguous and to separate observed results from validated conclusions.

## Core variables

- `W`: Layer1 C/Q window length in trading sessions. Examples tested: 20, 30, 45, 60.
- `h`: Layer2 future-return prediction horizon in trading sessions. Examples tested: 5, 10, 15, 20, 25, 30, 45.
- `MODEL_HISTORY`: raw normalized price/volume input length for Layer2. Current working value: 90 sessions.
- `RETRAIN_DAYS` / `ROLL_DAYS`: cadence between chronological retraining points. Tested values include 15D and 10D; 10D was the stronger observed cadence in the earlier 150-memory experiment, but this was before the later leakage audit invalidated performance claims.
- `retain` / `memory`: number of most recent eligible training samples retained at each retrain. The working baseline had been 150, but 150 was not established by a dedicated retain-length sweep and should not be treated as optimal. Candidate future sweep: 30, 50, 75, 100, 150.
- `Layer1 scope`: current research is H-only. Other Layer1 regions are out of scope.
- `Layer2 output`: ranking / distribution outputs such as q10, q50, q90 and P(up); P(up) should not be interpreted as calibrated probability unless calibration is separately validated.
- `evaluation`: chronological OOS only. Realized up-rate means the fraction of actual future returns above zero inside a score bucket; it is not classification accuracy.

## Leakage constraints that must be satisfied before future performance comparisons

1. Layer2 label maturity: a training row for horizon `h` may only be used when `cutoff + h < train_asof` / OOS block start.
2. Layer1 entry-side C/Q must not use campaign returns whose final exit occurs after the window end.
3. Retrospective local extrema currently require up to 10 future sessions for confirmation and therefore must be made causal or shifted to their confirmation time.
4. Sliding windows are highly overlapping; exact duplicates were not observed, but de-overlapped OOS checks are required for robustness.

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

These values are retained only as experiment history. They must not be used as evidence of genuine OOS predictive strength until the causal Layer1 construction and Layer2 target-purge rules are fixed and the sweep is rerun.
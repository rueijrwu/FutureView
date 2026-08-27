# FutureView Profitability Learning Implementation Framework

## 1. Scope

This document defines the implementation framework for the restarted Strategy profitability research branch.

The current implementation goal is deliberately narrow:

1. generate reproducible historical Strategy outcomes and baseline families;
2. analyze Candidate Representation A directly;
3. only after A is understood, test Candidate Representation B with an unsupervised Autoencoder.

No CNN or raw price-volume predictive model is part of the current experiment.

## 2. Technology baseline

Continue using the existing research stack:

- Python
- NumPy
- pandas
- Numba where useful
- PyTorch for Autoencoder experiments
- GitHub Actions for reproducible cloud tests

Existing Strategy-1 path-generation code and previously used SMH historical-data workflow may be reused where compatible with the definitions in `Theory.md`.

## 3. Historical path evaluation

For each historical evaluation window, the pipeline should produce auditable legal Strategy outcomes and a reproducible baseline family.

Conceptually:

```python
evaluate_historical_window(
    market,
    window,
    strategy_config,
    baseline_configs,
) -> HistoricalWindowResult
```

The result should retain at least:

```text
window identity / dates
legal Strategy outcome profits E_i
L
U
Q_i values
baseline results B_i
reproducibility metadata
```

Derived quantities such as `C = U - L` and `U - B_i` may be computed for reporting, but they should not automatically be duplicated as independent representation inputs.

## 4. Candidate Representation A

Representation A is the direct statistical representation:

```text
A = [L, U, B_1, ..., B_k]
```

A does **not** use an Autoencoder.

The first implementation task is to build a table with one row per historical window and columns for:

```text
window start / end
L
U
each selected B_i
optional derived columns for reporting only: C, U-B_i
```

### 4.1 A statistical analysis

At minimum, analyze:

```text
univariate distributions
correlation / dependence matrix
pairwise plots or equivalent summaries
baseline-to-baseline redundancy
L/U versus baseline relationships
chronological stability across subperiods
```

The purpose is to determine how much structure is already visible without any learned representation.

## 5. Candidate Representation B

Representation B extends A with fixed-length summaries of the Q distribution.

Initial candidate:

```text
B = [
    L,
    U,
    B_1, ..., B_k,
    Q10,
    Q25,
    Q50,
    Q75,
    Q90,
]
```

The exact quantiles are configurable and are not yet frozen as theory.

For each window, compute Q from all legal Strategy outcomes:

```text
Q_i = (U - E_i) / (U - L)
```

with explicit handling of degenerate windows where `U == L`.

## 6. Algebraic-redundancy rule

Do not treat deterministic transformations as independent evidence of low dimensionality.

If A or B already contains:

```text
L
U
B_i
```

then the default Autoencoder input should exclude:

```text
C = U - L
U - B_i
```

These quantities may still be saved and reported for interpretation.

The experiment should distinguish:

```text
derived redundancy
empirical redundancy
```

Only empirical redundancy is relevant evidence for a lower-dimensional historical state.

## 7. Autoencoder experiment for B

Only Representation B is the current Autoencoder candidate.

Conceptual model:

```python
z = encoder(y_B)
y_hat = decoder(z)
```

The Autoencoder objective is reconstruction only.

It must not use win rate, mean profit, median profit, or other withheld profitability statistics as supervised targets during formation of Z.

Test a small latent-dimension sweep, for example:

```text
d = 1, 2, 3, ...
```

and compare reconstruction quality on chronological held-out windows.

The purpose is to identify whether reconstruction error meaningfully saturates at a small latent dimension.

## 8. Post-hoc profitability analysis

After Z has been formed, profitability statistics that were not used to train the Autoencoder may be joined back to each historical window.

Examples include:

```text
mean realized profit
median realized profit
win rate
other explicitly withheld outcome statistics
```

These are analyzed only after the unsupervised representation is learned.

No relationship is assumed in advance.

## 9. Chronological validation

Both A statistics and B Autoencoder experiments must preserve chronology.

At minimum:

```text
historical subperiod comparison for A
chronological train/validation/test separation for B
no random-only split as the sole validation
```

The goal is to distinguish persistent historical structure from a representation that only fits one period.

## 10. Reuse of previous SMH framework

The previous branches already contain:

- SMH daily-data loading;
- Strategy-1 legal path generation;
- historical-window construction;
- GitHub Actions research workflows.

These components may be reused to avoid rebuilding infrastructure.

However, previous Autoencoder assumptions or input definitions are not automatically inherited. The current A/B definitions in `Theory.md` are authoritative for the restarted experiment.

## 11. Immediate execution order

The implementation order is now:

1. verify historical SMH outcome generation on the restart branch;
2. implement the selected baseline family for the same windows;
3. generate Representation A table;
4. inspect and report A statistics before any AE interpretation;
5. generate Representation B by adding Q quantiles;
6. run the smallest chronological Autoencoder latent-dimension experiment on B;
7. only afterward perform post-hoc profit analysis.

Do not proceed to CNN development before these results are understood.

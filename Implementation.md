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

Existing SMH historical-data infrastructure may be reused where compatible with the definitions in `Theory.md`. The legacy addon-reference enumeration is not authoritative for the current deterministic Strategy definition.

## 3. Deterministic historical path construction

All current Strategy calculations use daily close prices only.

Over the complete five-year sample, construct once:

```text
legal Entry set
legal 5-day Exit-event set
legal 10-day Exit-event set
5-day local-minimum set
10-day local-minimum set
5-day local-maximum set
10-day local-maximum set
```

For the retrospective outcome-space experiment, a `k`-day local extremum is evaluated against the preceding `k` and following `k` trading sessions. This retrospective extremum set is used only for historical-outcome construction; confirmation delay belongs to a later predictive/tradable experiment.

For each legal Entry `e`:

```text
entry_price = close[e]
base_min = most recent member of (local_min_5 union local_min_10) before e
D_b = entry_price - close[base_min]
```

The Entry is eligible for path construction only when `base_min` exists and `D_b > 0`.

Capital deployment is:

```text
Entry   = 1/3 total campaign capital
Addon1  = 1/3 total campaign capital
Addon2  = 1/3 total campaign capital
```

Unused capital remains cash.

After Entry, candidate Addons are only chronological members of:

```text
local_max_5 union local_max_10
```

Let `last_buy_price` be the actual price of the Entry or most recent Addon. The first later local-maximum candidate satisfying

```text
candidate_close - last_buy_price > D_b
```

becomes the next Addon. The same fixed `D_b` from the initial Entry is reused for Addon1 and Addon2. At most two Addons are allowed. No alternative addon-reference configurations are enumerated, so one legal Entry produces at most one deterministic path.

Exit handling is:

```text
first legal 5-day exit event  -> sell 40% of the then-current shares
later legal Addon             -> still allowed after the 5-day partial exit
legal 10-day exit event       -> sell all remaining shares and terminate campaign
fixed horizon                 -> liquidate any still-open shares
```

The 5-day partial exit is used at most once. It does not reset `D_b`, does not reset `last_buy_price`, and does not reset the maximum of three total capital deployments. Cash released by the 5-day partial exit may remain cash or later fund a still-legal Addon. The current fixed campaign horizon remains 60 trading sessions. Campaign profit is measured against the original total-capital denominator.

## 4. Historical evaluation interval

The current audit uses a single interval definition first:

```text
window length = 60 trading sessions
stride = 1 trading session
```

For window `[start, end]`, include every deterministic Strategy path whose **initial Entry index** lies in that interval. The path itself may continue beyond `end` until its exit or 60-session campaign horizon.

Thus:

```text
one legal Entry -> at most one deterministic outcome E(e)
L = min E(e) over Entries in the interval
U = max E(e) over Entries in the interval
```

A window with no eligible deterministic Entry is omitted from the descriptive table.

## 5. Baselines for the current audit

### 5.1 Periodic baseline

`B_periodic` is the primary comparison for the immediate audit.

It uses the same maximum of three capital deployments:

```text
1/3 at the interval start
1/3 at approximately one-third of the interval
1/3 at approximately two-thirds of the interval
all positions valued at the common interval end
```

The immediate question is simply:

```text
How often and by how much is U - B_periodic positive or negative?
```

A negative value is retained; it can indicate that the Strategy is unsuitable in that historical interval.

### 5.2 Random indicator

`B_random` remains a coarse descriptive indicator only. It is not the focus of the current audit and no Monte Carlo convergence study is required.

## 6. Candidate Representation A

Representation A is the direct statistical representation:

```text
A = [L, U, B_periodic, B_random]
```

A does **not** use an Autoencoder.

The output table should retain:

```text
window start / end
eligible Entry count
L
U
B_periodic
B_random
optional derived reporting columns: C, U-B_periodic, U-B_random
```

### 6.1 A statistical analysis

At minimum, analyze:

```text
univariate distributions
correlation / dependence matrix
chronological stability
fraction of windows with U > B_periodic
magnitude distribution of U - B_periodic
```

The purpose is to determine how much structure is already visible without any learned representation.

## 7. Candidate Representation B

Representation B extends A with fixed-length summaries of the Q distribution.

Initial candidate:

```text
B = [
    L,
    U,
    B_periodic,
    B_random,
    Q10,
    Q25,
    Q50,
    Q75,
    Q90,
]
```

The exact quantiles are configurable and are not yet frozen as theory.

For each window, compute Q from all legal deterministic Strategy outcomes:

```text
Q_i = (U - E_i) / (U - L)
```

with explicit handling of degenerate windows where `U == L`.

## 8. Algebraic-redundancy rule

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

## 9. Autoencoder experiment for B

Only Representation B is the current Autoencoder candidate.

Conceptual model:

```python
z = encoder(y_B)
y_hat = decoder(z)
```

The Autoencoder objective is reconstruction only. It must not use win rate, mean profit, median profit, or other withheld profitability statistics as supervised targets during formation of Z.

Test a small latent-dimension sweep and compare reconstruction quality on chronological held-out windows. This step remains blocked until the deterministic path audit and Representation A statistics are accepted.

## 10. Chronological validation

Both A statistics and later B experiments must preserve chronology.

At minimum:

```text
historical subperiod comparison for A
chronological train/validation/test separation for B
no random-only split as the sole validation
```

## 11. Immediate execution order

The implementation order is now:

1. build the deterministic five-year Entry / Exit / local-extrema sets;
2. generate one deterministic 60-session Strategy path per eligible Entry;
3. construct daily-stride 60-session evaluation intervals;
4. compare `U` directly with `B_periodic` and report the signed-difference distribution;
5. only after this audit is accepted, regenerate the full Representation A table;
6. only afterward return to Representation B / Q quantiles;
7. Autoencoder work remains later.

Do not proceed to CNN development before these results are understood.

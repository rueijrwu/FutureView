# FutureView Profitability Learning Implementation Framework

## 1. Scope

This document defines the implementation and program/API framework for the restarted Strategy profitability research branch.

The implementation should remain deliberately small. It should reuse the repository's existing GitHub/cloud-computation foundation where useful, but it does not require the existing web application, frontend visualization, production brokerage execution, or dashboard layers.

The immediate implementation goal is to provide a reproducible research pipeline in which representation experiments can be added without repeatedly redesigning data loading, Strategy outcome generation, baseline generation, training, evaluation, and artifact handling.

## 2. Technology Baseline

Continue using the current scientific/GPU Python ecosystem:

- Python
- NumPy
- Numba
- CUDA where appropriate
- PyTorch

Additional dependencies should be introduced only when they provide a clear research or infrastructure benefit.

The implementation should remain runnable in the existing GitHub cloud-development/computation environment.

## 3. Design Principles

The restarted framework should follow these rules:

1. Keep the fixed Strategy definition separate from learned models.
2. Keep historical outcome construction separate from predictive model input construction.
3. Compute Strategy outcomes and baseline families from the same historical path-generation pass where practical.
4. Prevent future-data leakage by API design rather than convention alone where practical.
5. Keep raw/intermediate datasets reproducible from explicit configuration.
6. Keep model training independent of frontend or web services.
7. Keep GPU acceleration optional at the API boundary: research logic should identify the compute device explicitly.
8. Save enough metadata to reproduce every experiment.
9. Do not freeze the learned representation format until the representation question is resolved.

## 4. Proposed Research Package

A minimal Python package can evolve around the following responsibilities:

```text
src/futureview/
    data/
        market.py
        windows.py
    strategy/
        strategy1.py
        outcomes.py
        baseline.py
    representation/
        base.py
    models/
        profitability.py
    training/
        dataset.py
        trainer.py
    evaluation/
        metrics.py
        audit.py
    experiment/
        config.py
        runner.py
```

This is a responsibility map, not a requirement to create every module immediately.

## 5. Core Data APIs

### 5.1 Market data

The market-data layer should expose canonical chronological price-volume observations without model-specific feature engineering.

Conceptual API:

```python
load_market_data(symbol, start, end) -> MarketSeries
```

`MarketSeries` should preserve timestamps and the primitive market fields needed by later representation experiments.

### 5.2 Historical input window

```python
build_input_window(market, entry_time, lookback, config) -> InputWindow
```

The API must guarantee that returned observations do not extend beyond `entry_time`.

The tensor/channel representation remains configurable and is intentionally not frozen yet.

## 6. Fixed Strategy APIs

Strategy code should deterministically identify legal Strategy events and outcomes from historical data.

Conceptual interfaces:

```python
find_legal_entries(market, strategy_config) -> list[Entry]
```

```python
realize_entry_outcome(market, entry, strategy_config) -> EntryOutcome
```

An `EntryOutcome` should eventually contain at minimum:

```text
entry identifier
timestamp
realized profit
legal Strategy evolution needed for audit
```

The exact treatment of nested Entry/Add1/Add2 paths must follow the final theoretical sample-space definition and should not be silently decided by the implementation.

## 7. Historical Path Evaluation Bundle

Strategy outcomes and baselines should be generated together from the same historical evaluation window where practical.

Conceptual API:

```python
evaluate_historical_window(
    market,
    window,
    strategy_config,
    baseline_configs,
) -> HistoricalWindowResult
```

A `HistoricalWindowResult` should contain at least:

```text
legal Strategy entries
realized Strategy outcomes
L
U
C
Q values
baseline family
U - baseline opportunity values
reproducibility metadata
```

This keeps all historical comparisons synchronized to the same source data and evaluation window.

## 8. Window-Level Profitability Statistics

For a historical evaluation window, provide deterministic statistics:

```python
compute_profitability_bounds(outcomes) -> ProfitabilityBounds
```

with conceptually:

```text
L = minimum realized Entry profit
U = maximum realized Entry profit
C = U - L
```

and

```python
compute_q(profit, bounds) -> float
```

implementing

```text
Q = (U - E_i) / C
```

with explicit handling of the degenerate case `C == 0`.

## 9. Baseline Family APIs

Baselines should be configuration-controlled, reproducible, and computed from the same historical data used for Strategy path evaluation.

A common conceptual interface is:

```python
compute_baseline(
    market,
    window,
    strategy_config,
    baseline_config,
    rng,
) -> BaselineResult
```

Potential baseline types include:

```text
market / buy-and-hold
periodic-investment
random-entry
strategy-null random-entry with downstream Strategy rules retained
matched-random entry
```

For stochastic baselines, the random seed and sampling procedure must be explicit and persisted.

Because a single random draw is noisy, stochastic baseline configurations should support repeated Monte Carlo sampling and return a distribution summary rather than only one realization.

Conceptually:

```python
compute_baseline_distribution(
    market,
    window,
    strategy_config,
    baseline_config,
    n_samples,
    seed,
) -> BaselineDistribution
```

A baseline distribution may retain:

```text
mean
median
quantiles
standard deviation
individual sampled returns when audit requires them
```

For any baseline result `B`, compute opportunity relative to the observed upper Strategy outcome:

```python
compute_upper_opportunity(U, B) -> float
```

implementing

```text
A = U - B
```

For a stochastic baseline, both opportunity relative to the expected baseline and opportunity relative to baseline quantiles may be retained.

## 10. Training Sample Construction

Training-data construction should join two objects that remain separately auditable:

```text
past-only market input X_i
historically realized Strategy target E_i
```

Conceptual API:

```python
build_samples(
    market,
    entries,
    outcomes,
    input_config,
    target_config,
) -> DatasetManifest
```

Each sample should retain stable identifiers allowing reconstruction of:

- symbol;
- Entry timestamp;
- input-window boundaries;
- outcome identity;
- historical evaluation window used for L/U/Q when applicable;
- associated baseline-family statistics for that window;
- configuration/version information.

## 11. Representation API

Do not freeze the CNN representation yet.

Provide only a small interface boundary that future experiments can satisfy:

```python
class RepresentationModel:
    def encode(self, x):
        """Map a batch of past price-volume inputs to representation Z."""
```

A later implementation may use a PyTorch CNN, but the API should not assume a specific number of layers, dimensions, receptive fields, or latent semantics.

The representation output should conceptually have shape

```text
[batch, representation_dim]
```

unless later research demonstrates that a structured representation is preferable.

## 12. Profitability Model API

The downstream estimator should consume a representation and expose profitability predictions without requiring knowledge of how the representation was generated.

Conceptual interface:

```python
class ProfitabilityModel:
    def forward(self, z):
        ...
```

Potential outputs include:

```text
win probability
expected profit
expected/estimated Q
probability of next Strategy decision state
```

These outputs are not all required for the first experiment. Target selection will follow the representation discussion.

## 13. End-to-End Composition

The framework should permit both separated and joint training:

```python
z = representation_model(x)
prediction = profitability_model(z)
```

or a composed PyTorch module:

```python
class StrategyProfitabilityModel(torch.nn.Module):
    def forward(self, x):
        z = self.representation(x)
        return self.head(z)
```

This allows representation experiments without changing Strategy/outcome generation or evaluation infrastructure.

## 14. GPU and Numerical Execution

PyTorch should be the primary learned-model execution layer.

Typical device selection:

```python
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
```

NumPy and Numba/CUDA may be used for deterministic preprocessing, Strategy replay, large-scale historical calculations, Monte Carlo baseline evaluation, or other operations where they are more appropriate than PyTorch.

CPU fallbacks should remain available for validation and small tests.

## 15. Experiment Configuration

Every experiment should be driven by an explicit serializable configuration containing at least:

```text
data range
symbols/universe
lookback definition
Strategy version/configuration
baseline family definitions
baseline Monte Carlo sample count and random seed where applicable
sample-space/outcome-definition version
representation model version
profitability-head version
training parameters
random seed
compute device
```

Conceptual entry point:

```bash
python -m futureview.experiment.runner --config configs/<experiment>.yaml
```

The exact configuration format may reuse existing repository conventions; no format change is required merely for this restart.

## 16. Experiment Artifacts

A run should produce a self-contained result directory, for example:

```text
artifacts/<run-id>/
    config.*
    manifest.*
    metrics.*
    model.*
    audit.*
```

The artifacts should make it possible to answer:

- exactly which samples were used;
- exactly which historical periods were train/validation/test;
- which Strategy and outcome definitions generated the targets;
- which baseline definitions and stochastic seeds generated reference results;
- which representation/model version was trained;
- which code revision produced the run.

## 17. Validation Framework

At minimum, validation should include:

```text
unit tests
past-only input-window leakage tests
Strategy outcome reproducibility tests
L/U/C/Q calculation tests
baseline reproducibility tests
random-baseline seed reproducibility tests
chronological train/validation/test separation
CPU/GPU numerical sanity checks where relevant
```

Model evaluation should remain chronological rather than relying only on random sample splitting.

## 18. Cloud/GitHub Workflow

Reuse the existing GitHub-based development and cloud-computation workflow. The restarted branch should remain research-oriented:

```text
GitHub repository
    -> cloud development/computation environment
    -> deterministic Strategy/baseline outcome generation
    -> GPU/CPU training
    -> versioned experiment artifacts
```

No frontend, dashboard, web API, scheduled production workflow, or deployment layer is required for the present research phase.

## 19. Immediate Implementation Boundary

Do not implement a new CNN architecture yet.

The next step is to define the learned representation theoretically. After that decision, implementation can add the smallest representation module and experiment necessary to test the hypothesis.

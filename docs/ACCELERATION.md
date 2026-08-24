# FutureView Acceleration Architecture

FutureView currently remains a **JavaScript / Node-only** system for production logic, ranking, replay, and backtesting.

The architecture must nevertheless preserve a clean interface for future native numerical acceleration so that C++/WebAssembly can be introduced later without rewriting or forking strategy logic.

## Current policy

Current default:

```text
JavaScript / Node = canonical implementation
```

Do not introduce C++, WebAssembly, Python, or Fortran merely because a workload looks computationally large.

Optimization order is:

```text
1. eliminate repeated computation
2. precompute immutable historical features
3. append only new sessions incrementally
4. cache reusable artifacts
5. improve batching / data layout / I/O
6. profile
7. only then consider C++/WASM for proven numeric bottlenecks
```

## Required pluggable interface

JavaScript code should call numerical feature operations through a stable provider interface rather than coupling strategy code to one implementation.

Conceptual contract:

```js
export interface NumericFeatureProvider {
  sma(values, window)
  rollingMin(values, window)
  rollingMax(values, window)
  atr(high, low, close, window)
  volatility(values, window)
  rollingSum(values, window)
}
```

The exact API may evolve, but the architectural boundary must remain:

```text
Strategy / ranking / backtest JS
            |
            v
Numeric feature interface
       /           \
      v             v
JS reference     future WASM provider
(current)        (optional later)
```

The current provider remains JavaScript. A future C++ implementation should normally be compiled to WebAssembly and exposed behind the same interface.

## What may be accelerated

Future C++/WASM support may implement strategy-neutral deterministic numerical kernels such as:

- rolling SMA / EMA-like primitives where needed
- rolling sum / min / max
- ATR and true-range batches
- volatility / standard-deviation batches
- large typed-array transforms
- other reusable point-in-time feature calculations

These operations should accept compact numeric inputs and return deterministic outputs without owning portfolio or strategy state.

## What must remain canonical JavaScript

Native/WASM code must not become a second trading strategy implementation.

The following remain JavaScript responsibilities:

- SetupScore and ranking semantics
- stock eligibility decisions
- Top 50 selection
- sector ranking / Top 3 sector selection
- final stock selection
- entry signals
- Add #1 / Add #2 decisions
- option-acceleration rules
- exit conditions
- portfolio state and capital allocation
- backtest execution semantics
- audit definitions and result interpretation

In short:

> C++/WASM may accelerate arithmetic, but JavaScript owns trading decisions.

## Precomputation-first design

Historical features whose point-in-time values are immutable after a session closes should be calculated once and reused.

Examples:

```text
SMA5 / SMA10 / SMA20 / SMA50 / SMA200
ATR14
rolling 20D / 50D highs and lows
average dollar volume
relative-volume baseline
volatility inputs
other strategy-neutral rolling statistics
```

Backtests should consume these stored historical features rather than recomputing the same windows on every run.

New data should normally cause only incremental computation:

```text
existing feature watermark = T
new session                = T+1

compute T+1 only
append artifact
advance watermark
```

## Storage boundary

Large historical feature artifacts belong primarily in R2-compatible object storage layouts.

D1-compatible relational storage should primarily hold queryable metadata/index records such as:

- feature schema version
- producer / provider version
- date coverage
- R2 prefix / object keys
- symbol count
- validation/parity status
- creation timestamps

Historical artifacts should be versioned so cached backtests can identify exactly which feature set they consumed.

## Provider identity and reproducibility

Every generated feature artifact should be able to identify its numerical producer, for example:

```text
numeric_provider = js-reference-v1
```

and, if native acceleration is introduced later:

```text
numeric_provider = wasm-cpp-v1
```

Provider changes must not silently overwrite semantics.

## Parity requirement before enabling C++/WASM

A future native provider must be validated against the JavaScript reference implementation before use.

At minimum:

```text
same historical input
        ↓
JS reference output
WASM output
        ↓
compare all sampled fields
        ↓
within documented numerical tolerance
```

Parity testing must cover boundary conditions, missing data handling, window warm-up behavior, and point-in-time indexing.

If parity is not demonstrated, the JavaScript provider remains authoritative.

## Performance trigger

Do not add C++/WASM based on intuition alone.

Native acceleration should be considered only after profiling shows that:

1. repeated historical computation has already been removed;
2. historical feature reuse/caching is in place;
3. I/O and JSON/object-allocation overhead have been evaluated;
4. a specific deterministic numerical kernel is still a material CPU bottleneck.

The goal is to avoid unnecessary architectural complexity while keeping the system ready for acceleration when scale justifies it.

## Design rule

The long-term contract is:

> **JS strategy semantics stay stable while numerical execution providers may change behind a compatible interface.**

This allows FutureView to remain simple today while preserving a migration path to C++/WASM later without changing trading behavior or duplicating strategy logic.

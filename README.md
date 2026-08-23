# FutureView

FutureView is a point-in-time market research platform for systematic screening, ranking, portfolio research, and backtesting.

## Design goals

1. Maintain a reproducible historical market database.
2. Generate a daily cross-sectional ranking and Top-50 market view.
3. Track ranking trajectories, persistence, breakouts, trend, relative strength, and extension.
4. Use exactly the same feature/ranking logic in live screening and historical backtests.
5. Model the portfolio as Emergency Reserve + Core/Reserve + Tactical Momentum.
6. Keep order execution manual; FutureView is a research and decision-support system.

## Portfolio policy

- Tactical Momentum is opportunity-driven and capped at roughly two-thirds of investable capital.
- Unused tactical capital returns to the Core/Reserve reservoir.
- Profit-taking triggers portfolio re-evaluation rather than automatic reinvestment.
- Emergency Reserve targets 10–30% of total assets and must not fall below 10%.
- Emergency Reserve deployment during extreme fear is restricted to broad ETFs and large-cap/core assets.
- The reservoir adjusts cash exposure and reallocates capital as total assets and market conditions change.

## Initial screener

The baseline universe filter favors liquid, established right-side trends. The ranking model combines 20-day and 60-day relative strength, trend quality, breakout strength, and volume confirmation, with an extension constraint based on ATR.

Daily Top 50 is intended for both candidate discovery and human market familiarization. Historical ranking snapshots are first-class data so ranking trajectory and forward returns can be studied without look-ahead.

## Architecture

- `config/` — strategy and portfolio policy
- `src/futureview/features/` — point-in-time feature calculations
- `src/futureview/screener/` — filtering and cross-sectional ranking
- `src/futureview/storage/` — DuckDB schemas and persistence
- `src/futureview/backtest/` — event-driven portfolio simulation
- future modules: market-data providers, analytics, options overlay, API, dashboard

## Data stack

Python 3.12+, Polars, DuckDB, Parquet, PyArrow.

Raw market data, derived features, ranking snapshots, portfolio state, and trade/position events are kept separate so research can be reproduced and strategy parameters can be changed without corrupting source data.

## Development sequence

Phase 1: data provider + historical database + feature engine.

Phase 2: Top-50 screener + ranking history + forward-return analytics.

Phase 3: underlying-only event-driven backtest including new-high profit taking and 5/10-day moving-average exits.

Phase 4: Core/Reserve/Tactical dynamic allocation and market-regime logic.

Phase 5: historical option-chain layer and Top-1-to-3 leader call overlay.

Automated order execution is intentionally out of scope.

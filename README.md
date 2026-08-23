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

The baseline scanner ranks **active U.S. common stocks only**. Massive ticker-reference metadata is used to restrict the ranking universe to `type=CS`, so ETFs are excluded before cross-sectional scoring and Top-50 selection.

ETF OHLCV is intentionally retained in the historical R2 database. It is not currently part of the stock screener, but will be reused later for market-regime and capital-allocation research.

The baseline universe filter favors liquid, established right-side trends. The ranking model combines 20-day and 60-day relative strength, trend quality, breakout strength, and volume confirmation, with an extension constraint based on ATR.

Daily Top 50 is intended for both candidate discovery and human market familiarization. Historical ranking snapshots are first-class data so ranking trajectory and forward returns can be studied without look-ahead.

## Architecture

- `config/` — strategy and portfolio policy
- `src/futureview/features/` — point-in-time feature calculations
- `src/futureview/screener/` — filtering and cross-sectional ranking
- `src/futureview/storage/` — DuckDB schemas and persistence
- `src/futureview/backtest/` — event-driven portfolio simulation
- `src/futureview/dashboard/` — presentation-only static snapshot export
- `site/` — Cloudflare Pages static dashboard
- future modules: analytics, ETF regime analysis, options overlay, API

## Data stack

Python 3.12+, Polars, DuckDB, Parquet, PyArrow.

Raw market data, derived features, ranking snapshots, portfolio state, and trade/position events are kept separate so research can be reproduced and strategy parameters can be changed without corrupting source data.

## Cloudflare Pages

FutureView uses a framework-free static dashboard so deployment remains independent from the Python research engine.

Recommended Cloudflare Pages Git settings:

- Production branch: `master`
- Framework preset: `None`
- Build command: `exit 0`
- Build output directory: `site`
- Root directory: repository root

Pull-request branches receive Cloudflare preview deployments through the Git integration. The dashboard reads `site/data/latest.json`; the research pipeline writes this presentation snapshot after a successful daily ranking run.

Historical OHLCV, full feature tables, and full ranking history should live in persistent object storage such as Cloudflare R2 rather than in the Git repository. Only compact presentation snapshots need to be published with the static dashboard.

## Development sequence

Phase 1: data provider + historical database + feature engine.

Phase 2: Top-50 common-stock screener + ranking history + forward-return analytics.

Phase 3: underlying-only event-driven backtest including new-high profit taking and 5/10-day moving-average exits.

Phase 4: ETF-based market-regime analysis and Core/Reserve/Tactical dynamic allocation. The retained ETF history will be used to study broad-market trend, risk appetite, sector leadership, defensive rotation, credit conditions, and other signals that can determine the allowed tactical-capital ceiling and reservoir cash posture. ETF signals will control risk capacity rather than enter the stock Top-50 ranking.

Phase 5: historical option-chain layer and Top-1-to-3 leader call overlay.

Automated order execution is intentionally out of scope.

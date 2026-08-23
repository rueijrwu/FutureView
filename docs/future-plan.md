# Future Plan

## ETF market-regime analysis

ETF market data remains part of the retained raw OHLCV history, but ETFs are excluded from the current stock screener and Top-50 ranking.

A later market-regime module will use a selected ETF set to estimate risk capacity and guide the portfolio reservoir rather than generate stock candidates. Candidate inputs include:

- broad-market trend and breadth proxies such as SPY, QQQ, IWM, and DIA;
- cyclical-versus-defensive sector leadership;
- risk-appetite ratios such as IWM/SPY and XLY/XLP;
- credit-risk proxies such as HYG/LQD;
- duration and defensive assets such as TLT and GLD;
- volatility, extension, and trend-state measures derived from ETF OHLCV.

The regime output should determine an **allowed tactical-capital ceiling**, not a required invested percentage. Actual tactical allocation remains the minimum of market risk capacity, available high-quality setups, and portfolio risk limits.

The intended architecture is:

```text
retained ETF OHLCV
        ↓
ETF features / relative ratios / regime signals
        ↓
Market Regime Score
        ↓
allowed tactical-capital ceiling + reservoir cash posture
```

This ETF regime layer is intentionally separate from the common-stock ranking model.

## Dynamic web application

FutureView will evolve from a static daily snapshot into an interactive research application while keeping the Python research engine as the single source of truth for features, scores, rankings, backtests, and portfolio logic.

Target architecture:

```text
GitHub Actions / Python research engine
                ↓
               R2
      prices / rankings / regime
                ↓
       Cloudflare Worker API
                ↓
      interactive web frontend
```

The web layer should not recompute trading signals. It should query precomputed research outputs and present them interactively. Planned capabilities include:

- latest and historical Top-50 rankings without redeploying the site for every data update;
- ticker search and symbol detail views;
- sortable and filterable ranking tables;
- 5/10/20-day rank trajectories and persistence;
- breakout, sector, and leader-state filters;
- historical date selection;
- ETF market-regime and capital-level views;
- later portfolio and backtest parameter interfaces.

Migration will be incremental so the current Cloudflare Pages dashboard remains functional until the dynamic path is validated.

### Dynamic-web migration sequence

1. Add a minimal Cloudflare Worker API skeleton with `/api/health` while leaving Pages unchanged.
2. Add an R2 binding and expose read-only ranking endpoints such as `/api/rankings/latest`.
3. Change the frontend to fetch ranking data from the API instead of committed `site/data/latest.json`.
4. Stop committing daily dashboard data once API delivery is stable.
5. Optionally migrate the static frontend from Pages to Workers Static Assets so one Worker serves both `/api/*` and the frontend.
6. Expand the API to historical rankings, symbol views, ETF regime data, portfolio research, and backtest results.

The first step is intentionally infrastructure-only: the Worker health endpoint establishes the deployment and routing contract without changing current production behavior.

# Future Plan

## Formal system architecture

FutureView adopts a database-first dynamic-web architecture. The daily research pipeline and the web application are deliberately decoupled.

The operating principle is:

```text
Daily scheduled research pipeline
Massive
  ↓
Python feature / ranking engine
  ↓
R2 database and derived research outputs

Interactive application
Browser
  ↓
Cloudflare Worker API
  ↓
R2
  ↓
render current research state dynamically
```

R2 is the persistent source of truth for market data and published research outputs. Git is the source of truth for code, configuration, documentation, and frontend assets only. Daily market-data or ranking changes must not create Git commits and must not require a frontend redeployment.

### Deployment boundary

A Cloudflare deployment is required only when application code changes, for example:

- HTML, CSS, or JavaScript UI changes;
- Worker API code or routing changes;
- application-level static assets.

A deployment is **not** required when research data changes, including:

- a new trading session;
- a new Top-50 ranking;
- strategy weight changes followed by a scanner rerun;
- extension, persistence, or ranking-formula changes followed by recomputation;
- future ETF regime values;
- future portfolio or backtest outputs.

Those changes flow only through the research pipeline into R2 and become visible through the API.

### Data responsibilities

The Python research engine remains the only layer that computes trading research logic. The Worker must not recompute SMA, ATR, relative strength, ranking scores, persistence, market regime, or portfolio signals.

Suggested R2 layout:

```text
prices/
  daily/date=YYYY-MM-DD/bars.parquet

rankings/
  date=YYYY-MM-DD/ranking.parquet
  date=YYYY-MM-DD/top50.parquet

dashboard/
  latest.json

metadata/
  latest-market-data.json
  latest-ranking.json

reference/
  tickers/...

regime/
  date=YYYY-MM-DD/regime.json
```

Large Parquet datasets support Python research and backtests. Compact JSON objects support low-latency web/API delivery.

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

The web application is a read-oriented interactive research interface over precomputed R2 outputs.

Planned capabilities include:

- latest and historical Top-50 rankings without redeploying the site;
- ticker search and symbol detail views;
- sortable and filterable ranking tables;
- 5/10/20-day rank trajectories and persistence;
- breakout, sector, and leader-state filters;
- historical date selection;
- ETF market-regime and capital-level views;
- later portfolio and backtest research interfaces.

### Dynamic-web migration sequence

1. Add a minimal Worker API skeleton with `/api/health`. **Completed.**
2. Add the R2 binding and `/api/rankings/latest`. **Completed in code.**
3. Make the frontend prefer the API over committed static ranking data. **Completed in code.**
4. Stop committing daily dashboard snapshots to `master`. **Completed in the current migration.**
5. Validate Worker production delivery, then remove the legacy static JSON fallback so the dashboard is fully database-driven.
6. Expand the API to historical rankings, symbol views, ETF regime data, portfolio research, and backtest results.
7. Optionally consolidate static frontend delivery into Workers Static Assets after the API path is stable.

The target steady state is simple: the scheduled daily workflow writes research outputs to R2; the browser dynamically reads them through the Worker API. Routine daily data updates never touch Git and never redeploy the frontend.

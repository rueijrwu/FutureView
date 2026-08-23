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

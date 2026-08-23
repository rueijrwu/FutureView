# Screener Universe

The current FutureView screener ranks **active U.S. common stocks only**.

Universe classification comes from Massive ticker-reference metadata. Securities must be classified as `type=CS` before they enter hard filtering, cross-sectional scoring, and Top-50 selection. ETFs remain in the raw R2 price history but do not participate in stock ranking.

This separation is deliberate:

```text
Raw market OHLCV
├─ Common stocks (`type=CS`) → stock screener / ranking / Top 50
└─ ETFs and other instruments → retained for future research
```

The benchmark (currently SPY) is still available to the feature engine for relative-strength calculations even though it is not eligible to enter the stock ranking universe.

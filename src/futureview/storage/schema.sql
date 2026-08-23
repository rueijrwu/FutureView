CREATE TABLE IF NOT EXISTS daily_prices (
    symbol VARCHAR NOT NULL,
    date DATE NOT NULL,
    open DOUBLE NOT NULL,
    high DOUBLE NOT NULL,
    low DOUBLE NOT NULL,
    close DOUBLE NOT NULL,
    adjusted_close DOUBLE,
    volume BIGINT NOT NULL,
    PRIMARY KEY(symbol, date)
);

CREATE TABLE IF NOT EXISTS daily_rankings (
    date DATE NOT NULL,
    symbol VARCHAR NOT NULL,
    stock_score DOUBLE NOT NULL,
    rank INTEGER NOT NULL,
    rs20 DOUBLE,
    rs60 DOUBLE,
    rs20_rank DOUBLE,
    rs60_rank DOUBLE,
    trend_score DOUBLE,
    breakout_score DOUBLE,
    volume_rank DOUBLE,
    extension_atr DOUBLE,
    breakout20 BOOLEAN,
    breakout50 BOOLEAN,
    distance_from_high20 DOUBLE,
    sma5 DOUBLE,
    sma10 DOUBLE,
    sma20 DOUBLE,
    sma50 DOUBLE,
    sma200 DOUBLE,
    volume_ratio20 DOUBLE,
    rank_5d INTEGER,
    rank_10d INTEGER,
    rank_20d INTEGER,
    top50_days_20d INTEGER,
    PRIMARY KEY(date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_daily_rankings_rank
    ON daily_rankings(date, rank);

CREATE TABLE IF NOT EXISTS portfolio_daily (
    date DATE PRIMARY KEY,
    total_equity DOUBLE NOT NULL,
    cash DOUBLE NOT NULL,
    core_reserve DOUBLE NOT NULL,
    tactical_capital DOUBLE NOT NULL,
    emergency_reserve DOUBLE NOT NULL,
    delta_adjusted_exposure DOUBLE,
    drawdown DOUBLE
);

CREATE TABLE IF NOT EXISTS position_events (
    event_id VARCHAR PRIMARY KEY,
    date DATE NOT NULL,
    symbol VARCHAR NOT NULL,
    event_type VARCHAR NOT NULL,
    quantity DOUBLE,
    price DOUBLE,
    reason VARCHAR
);

CREATE TABLE IF NOT EXISTS daily_prices (
    symbol VARCHAR NOT NULL,
    date DATE NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    adjusted_close DOUBLE,
    volume BIGINT,
    PRIMARY KEY(symbol, date)
);

CREATE TABLE IF NOT EXISTS daily_rankings (
    date DATE NOT NULL,
    symbol VARCHAR NOT NULL,
    stock_score DOUBLE,
    rank INTEGER,
    rs20 DOUBLE,
    rs60 DOUBLE,
    extension_atr DOUBLE,
    breakout20 BOOLEAN,
    rank_5d INTEGER,
    rank_10d INTEGER,
    rank_20d INTEGER,
    top50_days_20d INTEGER,
    PRIMARY KEY(date, symbol)
);

CREATE TABLE IF NOT EXISTS portfolio_daily (
    date DATE PRIMARY KEY,
    total_equity DOUBLE,
    cash DOUBLE,
    core_reserve DOUBLE,
    tactical_capital DOUBLE,
    emergency_reserve DOUBLE,
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

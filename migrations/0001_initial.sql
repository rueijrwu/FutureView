PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS instruments (
  symbol TEXT PRIMARY KEY,
  name TEXT,
  type TEXT NOT NULL,
  market TEXT NOT NULL,
  locale TEXT,
  primary_exchange TEXT,
  currency_name TEXT,
  cik TEXT,
  composite_figi TEXT,
  share_class_figi TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  source_updated_at TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS universe_snapshots (
  as_of TEXT PRIMARY KEY,
  instrument_count INTEGER NOT NULL,
  r2_key TEXT NOT NULL,
  producer TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS universe_membership (
  as_of TEXT NOT NULL,
  symbol TEXT NOT NULL,
  PRIMARY KEY (as_of, symbol),
  FOREIGN KEY (symbol) REFERENCES instruments(symbol)
);
CREATE INDEX IF NOT EXISTS idx_universe_membership_symbol
  ON universe_membership(symbol, as_of DESC);

CREATE TABLE IF NOT EXISTS ranking_runs (
  trading_date TEXT PRIMARY KEY,
  candidate_count INTEGER NOT NULL,
  top50_count INTEGER NOT NULL,
  universe_as_of TEXT,
  ranking_r2_key TEXT NOT NULL,
  top50_r2_key TEXT NOT NULL,
  ranking_state_r2_key TEXT NOT NULL,
  workflow_instance TEXT,
  producer TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ranking_entries (
  trading_date TEXT NOT NULL,
  symbol TEXT NOT NULL,
  rank INTEGER NOT NULL,
  base_rank INTEGER,
  stock_score REAL NOT NULL,
  base_score REAL,
  rs20 REAL,
  rs60 REAL,
  extension_atr REAL,
  breakout20 INTEGER,
  rank_change_5d INTEGER,
  rank_change_20d INTEGER,
  PRIMARY KEY (trading_date, symbol),
  FOREIGN KEY (trading_date) REFERENCES ranking_runs(trading_date)
);
CREATE INDEX IF NOT EXISTS idx_ranking_entries_date_rank
  ON ranking_entries(trading_date DESC, rank ASC);
CREATE INDEX IF NOT EXISTS idx_ranking_entries_symbol_date
  ON ranking_entries(symbol, trading_date DESC);

CREATE TABLE IF NOT EXISTS workflow_runs (
  workflow_instance TEXT PRIMARY KEY,
  workflow_type TEXT NOT NULL,
  trading_date TEXT,
  status TEXT NOT NULL,
  details_json TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_versions (
  version TEXT PRIMARY KEY,
  config_json TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_runs (
  id TEXT PRIMARY KEY,
  strategy_version TEXT,
  start_date TEXT,
  end_date TEXT,
  status TEXT NOT NULL,
  result_r2_key TEXT,
  summary_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

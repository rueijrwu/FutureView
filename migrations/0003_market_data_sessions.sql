CREATE TABLE IF NOT EXISTS market_data_sessions (
  trading_date TEXT PRIMARY KEY,
  r2_key TEXT NOT NULL,
  row_count INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  source TEXT NOT NULL,
  producer TEXT NOT NULL,
  storage_format TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_market_data_sessions_updated
  ON market_data_sessions(updated_at DESC);

CREATE TABLE IF NOT EXISTS simulation_accounts (
  replay_session_id TEXT PRIMARY KEY,
  user_id INTEGER,
  product TEXT NOT NULL,
  contract TEXT NOT NULL,
  position_qty INTEGER NOT NULL DEFAULT 0,
  avg_price REAL NOT NULL DEFAULT 0,
  realized_pnl REAL NOT NULL DEFAULT 0,
  commission REAL NOT NULL DEFAULT 0,
  slippage REAL NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_fills (
  id TEXT PRIMARY KEY,
  replay_session_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  side TEXT NOT NULL CHECK(side IN ('buy','sell')),
  quantity INTEGER NOT NULL,
  requested_at_ts INTEGER NOT NULL,
  filled_at_ts INTEGER NOT NULL,
  fill_price REAL NOT NULL,
  realized_delta REAL NOT NULL DEFAULT 0,
  commission REAL NOT NULL DEFAULT 0,
  slippage REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_fills_session_sequence
  ON trade_fills(replay_session_id, sequence);
CREATE INDEX IF NOT EXISTS idx_trade_fills_session
  ON trade_fills(replay_session_id);

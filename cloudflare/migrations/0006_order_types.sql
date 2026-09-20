-- Working orders (limit, stop, stop-limit) rest across bars, so they need a home
-- outside the Durable Object blob to be visible in any history view.
CREATE TABLE IF NOT EXISTS trade_orders (
  id TEXT PRIMARY KEY,
  replay_session_id TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  order_type TEXT NOT NULL CHECK(order_type IN ('market','limit','stop','stop_limit')),
  side TEXT NOT NULL CHECK(side IN ('buy','sell')),
  quantity INTEGER NOT NULL,
  limit_price REAL,
  stop_price REAL,
  status TEXT NOT NULL CHECK(status IN ('working','triggered','filled','cancelled')),
  requested_at_ts INTEGER NOT NULL,
  triggered_at_ts INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trade_orders_session
  ON trade_orders(replay_session_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_orders_session_sequence
  ON trade_orders(replay_session_id, sequence);

-- A fill used to record only side, quantity and price, so after the fact there
-- was no way to tell a market fill from a stop fill.
ALTER TABLE trade_fills ADD COLUMN order_id TEXT;
ALTER TABLE trade_fills ADD COLUMN order_type TEXT;
ALTER TABLE trade_fills ADD COLUMN limit_price REAL;
ALTER TABLE trade_fills ADD COLUMN stop_price REAL;

CREATE INDEX IF NOT EXISTS idx_trade_fills_order
  ON trade_fills(order_id);

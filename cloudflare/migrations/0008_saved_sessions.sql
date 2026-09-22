-- One resumable save per user: replay cursor + full trading record (position,
-- pending orders, fills). A save overwrites any prior one for that user, since
-- only a single saved slot is supported.
CREATE TABLE IF NOT EXISTS saved_sessions (
  user_id INTEGER PRIMARY KEY,
  product TEXT NOT NULL,
  contract TEXT NOT NULL,
  contract_selection TEXT,
  start_ts INTEGER NOT NULL,
  cursor_ts INTEGER NOT NULL,
  warmup INTEGER NOT NULL DEFAULT 300,
  trading TEXT NOT NULL,
  saved_at TEXT NOT NULL
);

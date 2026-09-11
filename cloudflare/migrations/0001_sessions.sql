CREATE TABLE IF NOT EXISTS replay_sessions (
  id TEXT PRIMARY KEY,
  contract TEXT NOT NULL,
  start_ts INTEGER NOT NULL,
  cursor_ts INTEGER NOT NULL,
  state TEXT NOT NULL,
  speed TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_replay_sessions_updated_at
  ON replay_sessions(updated_at DESC);

ALTER TABLE ranking_runs ADD COLUMN strategy_version TEXT;
CREATE INDEX IF NOT EXISTS idx_ranking_runs_strategy_date
  ON ranking_runs(strategy_version, trading_date DESC);

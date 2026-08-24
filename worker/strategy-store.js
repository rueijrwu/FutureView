import {
  BACKTEST_CONFIG_V1,
  RANKING_CONFIG_V2,
  STRATEGY_VERSION,
} from "./strategy-config.js";

export async function ensureStrategyVersion(db) {
  if (!db) return;
  const now = new Date().toISOString();
  const config = JSON.stringify({
    ranking: RANKING_CONFIG_V2,
    backtest: BACKTEST_CONFIG_V1,
  });

  await db.batch([
    db.prepare("UPDATE strategy_versions SET active = 0 WHERE active != 0"),
    db.prepare(`
      INSERT INTO strategy_versions (version, config_json, active, created_at)
      VALUES (?, ?, 1, ?)
      ON CONFLICT(version) DO UPDATE SET
        config_json=excluded.config_json,
        active=1
    `).bind(STRATEGY_VERSION, config, now),
  ]);
}

export async function tagRankingRunStrategy(db, tradingDate) {
  if (!db) return;
  await db.prepare(`
    UPDATE ranking_runs
    SET strategy_version = ?
    WHERE trading_date = ?
  `).bind(STRATEGY_VERSION, tradingDate).run();
}

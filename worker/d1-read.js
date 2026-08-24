function normalizeRankingRows(rows) {
  return rows.map((row) => ({
    ...row,
    breakout20: Boolean(row.breakout20),
  }));
}

export async function rankingByDateFromD1(db, tradingDate) {
  if (!db) return null;
  const run = tradingDate
    ? await db.prepare(`
        SELECT trading_date, candidate_count, top50_count, universe_as_of,
               ranking_r2_key, top50_r2_key, ranking_state_r2_key, created_at
        FROM ranking_runs
        WHERE trading_date = ?
        LIMIT 1
      `).bind(tradingDate).first()
    : await db.prepare(`
        SELECT trading_date, candidate_count, top50_count, universe_as_of,
               ranking_r2_key, top50_r2_key, ranking_state_r2_key, created_at
        FROM ranking_runs
        ORDER BY trading_date DESC
        LIMIT 1
      `).first();
  if (!run) return null;

  const { results = [] } = await db.prepare(`
    SELECT symbol, rank, base_rank, stock_score, base_score,
           rs20, rs60, extension_atr, breakout20,
           rank_change_5d, rank_change_20d
    FROM ranking_entries
    WHERE trading_date = ? AND rank <= 50
    ORDER BY rank ASC
  `).bind(run.trading_date).all();

  const universe = run.universe_as_of
    ? await db.prepare(`
        SELECT instrument_count
        FROM universe_snapshots
        WHERE as_of = ?
        LIMIT 1
      `).bind(run.universe_as_of).first()
    : null;

  return {
    as_of: run.trading_date,
    universe_count: universe?.instrument_count ?? null,
    candidate_count: run.candidate_count,
    market_regime: "Research",
    cash_posture: "Rule-based",
    rankings: normalizeRankingRows(results),
    source: "d1",
    updated_at: run.created_at,
  };
}

export async function rankingDatesFromD1(db, limit = 100) {
  if (!db) return [];
  const safeLimit = Math.max(1, Math.min(Number(limit) || 100, 500));
  const { results = [] } = await db.prepare(`
    SELECT trading_date, candidate_count, top50_count, universe_as_of, created_at
    FROM ranking_runs
    ORDER BY trading_date DESC
    LIMIT ?
  `).bind(safeLimit).all();
  return results;
}

export async function symbolRankingHistoryFromD1(db, symbol, limit = 100) {
  if (!db) return [];
  const safeLimit = Math.max(1, Math.min(Number(limit) || 100, 500));
  const { results = [] } = await db.prepare(`
    SELECT trading_date, rank, base_rank, stock_score, base_score,
           rs20, rs60, extension_atr, breakout20,
           rank_change_5d, rank_change_20d
    FROM ranking_entries
    WHERE symbol = ?
    ORDER BY trading_date DESC
    LIMIT ?
  `).bind(String(symbol).toUpperCase(), safeLimit).all();
  return normalizeRankingRows(results);
}

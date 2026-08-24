const BATCH_SIZE = 500;

function chunks(items, size = BATCH_SIZE) {
  const out = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

export async function persistUniverseToD1(db, { asOf, r2Key, instruments, createdAt }) {
  if (!db) return;

  const upsertInstrument = db.prepare(`
    INSERT INTO instruments (
      symbol, name, type, market, locale, primary_exchange, currency_name,
      cik, composite_figi, share_class_figi, active, source_updated_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(symbol) DO UPDATE SET
      name=excluded.name,
      type=excluded.type,
      market=excluded.market,
      locale=excluded.locale,
      primary_exchange=excluded.primary_exchange,
      currency_name=excluded.currency_name,
      cik=excluded.cik,
      composite_figi=excluded.composite_figi,
      share_class_figi=excluded.share_class_figi,
      active=excluded.active,
      source_updated_at=excluded.source_updated_at,
      updated_at=excluded.updated_at
  `);

  for (const group of chunks(instruments)) {
    await db.batch(group.map((item) => upsertInstrument.bind(
      String(item.ticker),
      item.name ?? null,
      item.type ?? "CS",
      item.market ?? "stocks",
      item.locale ?? "us",
      item.primary_exchange ?? null,
      item.currency_name ?? null,
      item.cik ?? null,
      item.composite_figi ?? null,
      item.share_class_figi ?? null,
      item.active === false ? 0 : 1,
      item.last_updated_utc ?? null,
      createdAt,
    )));
  }

  await db.prepare(
    "DELETE FROM universe_membership WHERE as_of = ?",
  ).bind(asOf).run();

  const insertMembership = db.prepare(
    "INSERT INTO universe_membership (as_of, symbol) VALUES (?, ?)",
  );
  for (const group of chunks(instruments)) {
    await db.batch(group.map((item) => insertMembership.bind(asOf, String(item.ticker))));
  }

  await db.prepare(`
    INSERT INTO universe_snapshots (as_of, instrument_count, r2_key, producer, created_at)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(as_of) DO UPDATE SET
      instrument_count=excluded.instrument_count,
      r2_key=excluded.r2_key,
      producer=excluded.producer,
      created_at=excluded.created_at
  `).bind(asOf, instruments.length, r2Key, "cloudflare-js", createdAt).run();
}

export async function persistMarketDataSession(db, record) {
  if (!db) return;
  const now = record.updatedAt ?? new Date().toISOString();
  await db.prepare(`
    INSERT INTO market_data_sessions (
      trading_date, r2_key, row_count, sha256, source,
      producer, storage_format, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(trading_date) DO UPDATE SET
      r2_key=excluded.r2_key,
      row_count=excluded.row_count,
      sha256=excluded.sha256,
      source=excluded.source,
      producer=excluded.producer,
      storage_format=excluded.storage_format,
      updated_at=excluded.updated_at
  `).bind(
    record.tradingDate,
    record.r2Key,
    record.rowCount,
    record.sha256,
    record.source ?? "massive",
    record.producer ?? "cloudflare-js",
    record.storageFormat ?? "json",
    record.createdAt ?? now,
    now,
  ).run();
}

export async function persistRankingToD1(db, { rankingMetadata, rankings }) {
  if (!db) return;
  const date = rankingMetadata.date;

  await db.prepare(`
    INSERT INTO ranking_runs (
      trading_date, candidate_count, top50_count, universe_as_of,
      ranking_r2_key, top50_r2_key, ranking_state_r2_key,
      workflow_instance, producer, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(trading_date) DO UPDATE SET
      candidate_count=excluded.candidate_count,
      top50_count=excluded.top50_count,
      universe_as_of=excluded.universe_as_of,
      ranking_r2_key=excluded.ranking_r2_key,
      top50_r2_key=excluded.top50_r2_key,
      ranking_state_r2_key=excluded.ranking_state_r2_key,
      workflow_instance=excluded.workflow_instance,
      producer=excluded.producer,
      created_at=excluded.created_at
  `).bind(
    date,
    rankingMetadata.candidate_count,
    rankingMetadata.top50_count,
    rankingMetadata.universe_as_of ?? null,
    rankingMetadata.ranking_key,
    rankingMetadata.top50_key,
    rankingMetadata.ranking_state_metadata_key,
    rankingMetadata.workflow_instance ?? null,
    rankingMetadata.producer,
    rankingMetadata.updated_at,
  ).run();

  await db.prepare("DELETE FROM ranking_entries WHERE trading_date = ?").bind(date).run();
  const insert = db.prepare(`
    INSERT INTO ranking_entries (
      trading_date, symbol, rank, base_rank, stock_score, base_score,
      rs20, rs60, extension_atr, breakout20, rank_change_5d, rank_change_20d
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `);
  for (const group of chunks(rankings)) {
    await db.batch(group.map((row) => insert.bind(
      date,
      String(row.symbol),
      Number(row.rank),
      row.base_rank == null ? null : Number(row.base_rank),
      Number(row.stock_score),
      row.base_score == null ? null : Number(row.base_score),
      row.rs20 == null ? null : Number(row.rs20),
      row.rs60 == null ? null : Number(row.rs60),
      row.extension_atr == null ? null : Number(row.extension_atr),
      row.breakout20 ? 1 : 0,
      row.rank_change_5d == null ? null : Number(row.rank_change_5d),
      row.rank_change_20d == null ? null : Number(row.rank_change_20d),
    )));
  }
}

export async function latestRankingFromD1(db) {
  if (!db) return null;
  const run = await db.prepare(`
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

  return {
    as_of: run.trading_date,
    universe_count: null,
    market_regime: "Research",
    cash_posture: "Rule-based",
    rankings: results.map((row) => ({ ...row, breakout20: Boolean(row.breakout20) })),
    source: "d1",
    updated_at: run.created_at,
  };
}

export async function recordWorkflowRun(db, record) {
  if (!db) return;
  await db.prepare(`
    INSERT INTO workflow_runs (
      workflow_instance, workflow_type, trading_date, status, details_json, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(workflow_instance) DO UPDATE SET
      trading_date=excluded.trading_date,
      status=excluded.status,
      details_json=excluded.details_json,
      updated_at=excluded.updated_at
  `).bind(
    record.workflowInstance,
    record.workflowType,
    record.tradingDate ?? null,
    record.status,
    JSON.stringify(record.details ?? {}),
    record.updatedAt ?? new Date().toISOString(),
  ).run();
}

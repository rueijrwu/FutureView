import { rankCrossSection } from "./ranking-core.js";

const RANKING_STATE_SHARDS = 32;
const RANKING_STATE_VERSION = 1;
const NUMERIC_FIELDS = [
  "rs20",
  "rs60",
  "rs20_rank",
  "rs60_rank",
  "volume_rank",
  "trend_score",
  "breakout_score",
  "base_score",
  "persistence_score",
  "extension_penalty",
  "stock_score",
];

async function readJson(bucket, key) {
  const object = await bucket.get(key);
  if (object === null) throw new Error(`R2 object not found: ${key}`);
  return object.json();
}

async function writeJson(bucket, key, payload) {
  await bucket.put(key, JSON.stringify(payload), {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
  });
}

async function loadFeatures(bucket, tradingDate) {
  const metadata = await readJson(
    bucket,
    `features/daily/date=${tradingDate}/metadata.json`,
  );
  const features = [];
  for (const key of metadata.keys ?? []) {
    const payload = await readJson(bucket, key);
    features.push(...(payload.features ?? []));
  }
  return features;
}

async function loadUniverse(bucket, db, tradingDate) {
  const row = await db.prepare(`
    SELECT as_of, r2_key
    FROM universe_snapshots
    WHERE as_of <= ?
    ORDER BY as_of DESC
    LIMIT 1
  `).bind(tradingDate).first();
  if (!row?.r2_key) throw new Error(`no universe snapshot available for ${tradingDate}`);
  const payload = await readJson(bucket, row.r2_key);
  return {
    symbols: new Set((payload.symbols ?? []).map(String)),
    asOf: row.as_of,
  };
}

async function loadPriorRankingState(bucket, db, tradingDate) {
  const row = await db.prepare(`
    SELECT trading_date, ranking_state_r2_key
    FROM ranking_runs
    WHERE trading_date < ?
    ORDER BY trading_date DESC
    LIMIT 1
  `).bind(tradingDate).first();

  if (!row?.ranking_state_r2_key) {
    return { states: new Map(), priorSessionCount: 0, asOf: null };
  }

  const metadata = await readJson(bucket, row.ranking_state_r2_key);
  if (
    Number(metadata.version) !== RANKING_STATE_VERSION
    || Number(metadata.shard_count) !== RANKING_STATE_SHARDS
  ) {
    throw new Error("unsupported ranking state contract during replay");
  }

  const states = new Map();
  for (const key of metadata.keys ?? []) {
    const payload = await readJson(bucket, key);
    for (const state of payload.states ?? []) {
      if (state?.symbol) states.set(String(state.symbol), state);
    }
  }
  return {
    states,
    priorSessionCount: Number(metadata.prior_session_count ?? 20),
    asOf: metadata.as_of ?? row.trading_date,
  };
}

function compareRows(expectedRows, actualRows, tolerance = 1e-10) {
  const expected = new Map(expectedRows.map((row) => [String(row.symbol), row]));
  const actual = new Map(actualRows.map((row) => [String(row.symbol), row]));
  const missing = [...expected.keys()].filter((symbol) => !actual.has(symbol)).sort();
  const unexpected = [...actual.keys()].filter((symbol) => !expected.has(symbol)).sort();
  const mismatches = [];
  let maxAbsError = 0;

  for (const [symbol, left] of expected.entries()) {
    const right = actual.get(symbol);
    if (!right) continue;
    for (const field of NUMERIC_FIELDS) {
      const a = left[field];
      const b = right[field];
      if (a == null && b == null) continue;
      if (a == null || b == null) {
        mismatches.push({ symbol, field, expected: a, actual: b });
        continue;
      }
      const error = Math.abs(Number(a) - Number(b));
      maxAbsError = Math.max(maxAbsError, error);
      if (error > tolerance) {
        mismatches.push({ symbol, field, expected: a, actual: b, abs_error: error });
      }
    }
  }

  const expectedTop50 = [...expectedRows]
    .sort((a, b) => Number(a.rank) - Number(b.rank))
    .filter((row) => Number(row.rank) <= 50)
    .map((row) => String(row.symbol));
  const actualTop50 = [...actualRows]
    .sort((a, b) => Number(a.rank) - Number(b.rank))
    .filter((row) => Number(row.rank) <= 50)
    .map((row) => String(row.symbol));
  const top50Ok = JSON.stringify(expectedTop50) === JSON.stringify(actualTop50);

  return {
    missing,
    unexpected,
    mismatches,
    maxAbsError,
    expectedTop50,
    actualTop50,
    top50Ok,
  };
}

export async function runRankingReplay({ bucket, db, tradingDate }) {
  if (!db) throw new Error("D1 binding is required for JS ranking replay");

  const [features, universe, prior, productionPayload] = await Promise.all([
    loadFeatures(bucket, tradingDate),
    loadUniverse(bucket, db, tradingDate),
    loadPriorRankingState(bucket, db, tradingDate),
    readJson(bucket, `rankings/date=${tradingDate}/ranking.json`),
  ]);

  const result = rankCrossSection({
    features,
    tradingDate,
    eligibleSymbols: universe.symbols,
    priorStates: prior.states,
    priorSessionCount: prior.priorSessionCount,
  });

  const comparison = compareRows(
    productionPayload.rankings ?? [],
    result.rankings,
  );
  const coverageOk = comparison.missing.length === 0 && comparison.unexpected.length === 0;
  const numericOk = comparison.mismatches.length === 0;
  const status = coverageOk && numericOk && comparison.top50Ok ? "pass" : "fail";
  const root = `validation/js-replay/date=${tradingDate}`;
  const replayRankingKey = `${root}/ranking.json`;
  const resultKey = `${root}/result.json`;
  const now = new Date().toISOString();

  await writeJson(bucket, replayRankingKey, {
    version: RANKING_STATE_VERSION,
    date: tradingDate,
    count: result.rankings.length,
    rankings: result.rankings,
    producer: "cloudflare-js-replay",
    updated_at: now,
  });

  const validation = {
    date: tradingDate,
    status,
    candidate_count: result.candidateCount,
    production_candidate_count: productionPayload.rankings?.length ?? 0,
    prior_state_as_of: prior.asOf,
    universe_as_of: universe.asOf,
    missing_symbol_count: comparison.missing.length,
    unexpected_symbol_count: comparison.unexpected.length,
    numeric_mismatch_count: comparison.mismatches.length,
    max_abs_error: comparison.maxAbsError,
    coverage_status: coverageOk ? "pass" : "fail",
    numeric_status: numericOk ? "pass" : "fail",
    top50_status: comparison.top50Ok ? "pass" : "fail",
    sample_missing_symbols: comparison.missing.slice(0, 20),
    sample_unexpected_symbols: comparison.unexpected.slice(0, 20),
    sample_mismatches: comparison.mismatches.slice(0, 20),
    production_top50: comparison.expectedTop50,
    replay_top50: comparison.actualTop50,
    replay_ranking_key: replayRankingKey,
    updated_at: now,
  };
  await writeJson(bucket, resultKey, validation);
  await writeJson(bucket, "metadata/latest-js-replay.json", {
    date: tradingDate,
    status,
    data_key: resultKey,
    producer: "cloudflare-js-replay",
    updated_at: now,
  });

  if (status !== "pass") {
    throw new Error(`JS ranking replay failed for ${tradingDate}: ${JSON.stringify(validation)}`);
  }
  return validation;
}

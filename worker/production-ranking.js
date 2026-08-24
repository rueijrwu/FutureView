import { rankCrossSection } from "./ranking-core.js";

const RANKING_STATE_VERSION = 1;
const RANKING_STATE_SHARDS = 32;
const LATEST_RANKING_STATE_KEY = "metadata/latest-ranking-state.json";
const LATEST_UNIVERSE_KEY = "metadata/latest-common-stock-universe.json";
const LATEST_RANKING_KEY = "metadata/latest-ranking.json";
const LATEST_TOP50_KEY = "metadata/latest-top50.json";
const DASHBOARD_KEY = "dashboard/latest.json";

async function readJson(bucket, key) {
  const object = await bucket.get(key);
  if (object === null) throw new Error(`R2 object not found: ${key}`);
  return object.json();
}

async function readJsonOrNull(bucket, key) {
  const object = await bucket.get(key);
  return object === null ? null : object.json();
}

async function writeJson(bucket, key, payload) {
  await bucket.put(key, JSON.stringify(payload), {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
  });
}

function shardForSymbol(symbol) {
  let total = 0;
  for (const character of symbol) total += character.codePointAt(0);
  return total % RANKING_STATE_SHARDS;
}

async function loadFeatures(bucket, featureKeys) {
  const features = [];
  for (const key of featureKeys) {
    const payload = await readJson(bucket, key);
    features.push(...(payload.features ?? []));
  }
  return features;
}

async function loadUniverse(bucket) {
  const metadata = await readJson(bucket, LATEST_UNIVERSE_KEY);
  if (!metadata.data_key) throw new Error("common-stock universe pointer is incomplete");
  const payload = await readJson(bucket, metadata.data_key);
  return {
    symbols: new Set((payload.symbols ?? []).map(String)),
    count: Number(payload.count ?? payload.symbols?.length ?? 0),
    asOf: payload.as_of ?? metadata.as_of ?? null,
  };
}

async function loadPriorRankingState(bucket) {
  const metadata = await readJsonOrNull(bucket, LATEST_RANKING_STATE_KEY);
  if (metadata === null) {
    return { states: new Map(), priorSessionCount: 0, asOf: null };
  }
  if (
    Number(metadata.version) !== RANKING_STATE_VERSION
    || Number(metadata.shard_count) !== RANKING_STATE_SHARDS
  ) {
    throw new Error("unsupported ranking state contract");
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
    asOf: metadata.as_of ?? null,
  };
}

export async function runProductionRanking({ bucket, featureKeys, tradingDate, workflowInstance }) {
  const features = await loadFeatures(bucket, featureKeys);
  const universe = await loadUniverse(bucket);
  const prior = await loadPriorRankingState(bucket);

  if (prior.asOf && tradingDate <= prior.asOf) {
    throw new Error(`ranking date ${tradingDate} is not newer than state ${prior.asOf}`);
  }

  const result = rankCrossSection({
    features,
    tradingDate,
    eligibleSymbols: universe.symbols,
    priorStates: prior.states,
    priorSessionCount: prior.priorSessionCount,
  });
  if (!result.rankings.length) throw new Error("production ranking produced no candidates");

  const rankingKey = `rankings/date=${tradingDate}/ranking.json`;
  const top50Key = `rankings/date=${tradingDate}/top50.json`;
  const statePrefix = `state/ranking/v${RANKING_STATE_VERSION}/date=${tradingDate}`;
  const metadataKey = `rankings/date=${tradingDate}/metadata.json`;
  const now = new Date().toISOString();
  const top50 = result.rankings.filter((row) => Number(row.rank) <= 50);

  await writeJson(bucket, rankingKey, {
    version: RANKING_STATE_VERSION,
    date: tradingDate,
    count: result.rankings.length,
    rankings: result.rankings,
    producer: "cloudflare-js",
    workflow_instance: workflowInstance,
    updated_at: now,
  });
  await writeJson(bucket, top50Key, {
    version: RANKING_STATE_VERSION,
    date: tradingDate,
    count: top50.length,
    rankings: top50,
    producer: "cloudflare-js",
    workflow_instance: workflowInstance,
    updated_at: now,
  });

  const stateShards = Array.from({ length: RANKING_STATE_SHARDS }, () => []);
  for (const [symbol, state] of result.states.entries()) {
    stateShards[shardForSymbol(symbol)].push(state);
  }

  const stateKeys = [];
  for (let shard = 0; shard < RANKING_STATE_SHARDS; shard += 1) {
    const shardName = String(shard).padStart(2, "0");
    const key = `${statePrefix}/shard=${shardName}.json`;
    const states = stateShards[shard]
      .sort((a, b) => String(a.symbol).localeCompare(String(b.symbol)));
    await writeJson(bucket, key, {
      version: RANKING_STATE_VERSION,
      as_of: tradingDate,
      shard,
      shard_count: RANKING_STATE_SHARDS,
      count: states.length,
      states,
    });
    stateKeys.push(key);
  }

  const stateMetadata = {
    version: RANKING_STATE_VERSION,
    as_of: tradingDate,
    shard_count: RANKING_STATE_SHARDS,
    symbol_count: result.states.size,
    prior_session_count: Math.min(prior.priorSessionCount + 1, 20),
    prefix: statePrefix,
    keys: stateKeys,
    producer: "cloudflare-js",
    workflow_instance: workflowInstance,
    updated_at: now,
  };
  await writeJson(bucket, `${statePrefix}/metadata.json`, stateMetadata);

  const rankingMetadata = {
    version: RANKING_STATE_VERSION,
    date: tradingDate,
    candidate_count: result.candidateCount,
    top50_count: top50.length,
    ranking_key: rankingKey,
    top50_key: top50Key,
    ranking_state_metadata_key: `${statePrefix}/metadata.json`,
    universe_as_of: universe.asOf,
    producer: "cloudflare-js",
    workflow_instance: workflowInstance,
    updated_at: now,
  };
  await writeJson(bucket, metadataKey, rankingMetadata);

  const dashboard = {
    as_of: tradingDate,
    universe_count: universe.count,
    market_regime: "Research",
    cash_posture: "Rule-based",
    rankings: top50,
    producer: "cloudflare-js",
    updated_at: now,
  };

  // Promote latest objects only after every date-scoped artifact has succeeded.
  await writeJson(bucket, LATEST_RANKING_STATE_KEY, stateMetadata);
  await writeJson(bucket, LATEST_RANKING_KEY, rankingMetadata);
  await writeJson(bucket, LATEST_TOP50_KEY, {
    date: tradingDate,
    count: top50.length,
    data_key: top50Key,
    producer: "cloudflare-js",
    updated_at: now,
  });
  await writeJson(bucket, DASHBOARD_KEY, dashboard);

  return rankingMetadata;
}

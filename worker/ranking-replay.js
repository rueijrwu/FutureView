import { rankCrossSection } from "./ranking-core.js";

const RANKING_STATE_SHARDS = 32;
const RANKING_STATE_VERSION = 1;

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

function shardForSymbol(symbol) {
  let total = 0;
  for (const character of symbol) total += character.codePointAt(0);
  return total % RANKING_STATE_SHARDS;
}

export async function runRankingReplay({
  bucket,
  featureKeys,
  tradingDate,
  rankingStateMetadataKey,
  universeKey,
  root,
}) {
  const features = [];
  for (const key of featureKeys) {
    const payload = await readJson(bucket, key);
    features.push(...(payload.features ?? []));
  }

  const universePayload = await readJson(bucket, universeKey);
  const eligibleSymbols = new Set((universePayload.symbols ?? []).map(String));

  const stateMetadata = await readJson(bucket, rankingStateMetadataKey);
  if (
    Number(stateMetadata.version) !== RANKING_STATE_VERSION
    || Number(stateMetadata.shard_count) !== RANKING_STATE_SHARDS
  ) {
    throw new Error("unsupported ranking state contract");
  }

  const priorStates = new Map();
  for (const key of stateMetadata.keys ?? []) {
    const payload = await readJson(bucket, key);
    for (const state of payload.states ?? []) {
      if (state?.symbol) priorStates.set(String(state.symbol), state);
    }
  }

  const result = rankCrossSection({
    features,
    tradingDate,
    eligibleSymbols,
    priorStates,
    priorSessionCount: Number(stateMetadata.prior_session_count ?? 20),
  });

  const rankingKey = `${root}/cloudflare/ranking/ranking.json`;
  await writeJson(bucket, rankingKey, {
    version: RANKING_STATE_VERSION,
    date: tradingDate,
    count: result.rankings.length,
    rankings: result.rankings,
    producer: "cloudflare-ranking-replay",
  });

  const stateShards = Array.from({ length: RANKING_STATE_SHARDS }, () => []);
  for (const [symbol, state] of result.states.entries()) {
    stateShards[shardForSymbol(symbol)].push(state);
  }

  const stateKeys = [];
  for (let shard = 0; shard < RANKING_STATE_SHARDS; shard += 1) {
    const shardName = String(shard).padStart(2, "0");
    const key = `${root}/cloudflare/ranking/state/shard=${shardName}.json`;
    const states = stateShards[shard].sort((a, b) => String(a.symbol).localeCompare(String(b.symbol)));
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

  const metadataKey = `${root}/cloudflare/ranking/metadata.json`;
  const metadata = {
    version: RANKING_STATE_VERSION,
    date: tradingDate,
    candidate_count: result.candidateCount,
    ranking_key: rankingKey,
    state_keys: stateKeys,
    promoted_latest: false,
    producer: "cloudflare-ranking-replay",
    updated_at: new Date().toISOString(),
  };
  await writeJson(bucket, metadataKey, metadata);
  return metadata;
}

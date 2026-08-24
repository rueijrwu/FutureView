import { WorkflowEntrypoint } from "cloudflare:workers";
import {
  promoteProductionRanking,
  runProductionRanking,
} from "./production-ranking.js";

const STATE_VERSION = 1;
const STATE_SHARDS = 32;
const LATEST_STATE_KEY = "metadata/latest-feature-state.json";
const LATEST_INGEST_KEY = "metadata/latest-cloudflare-ingest.json";
const LATEST_WORKFLOW_KEY = "metadata/latest-incremental-workflow.json";
const LATEST_FEATURES_KEY = "metadata/latest-incremental-features.json";

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

function meanLast(values, size) {
  if (values.length < size) throw new Error(`rolling window requires ${size} values`);
  let sum = 0;
  for (let i = values.length - size; i < values.length; i += 1) sum += Number(values[i]);
  return sum / size;
}

function appendTrim(values, value, size) {
  const out = [...values, Number(value)];
  return out.slice(Math.max(0, out.length - size));
}

function trueRange(high, low, previousClose) {
  return Math.max(high - low, Math.abs(high - previousClose), Math.abs(low - previousClose));
}

function updateSymbolState(state, bar, tradingDate) {
  if (tradingDate <= state.as_of) {
    throw new Error(`${state.symbol}: update date is not newer than state`);
  }
  if (state.closes.length < 200 || state.highs.length < 50 || state.volumes.length < 20) {
    throw new Error(`${state.symbol}: incremental state is not fully bootstrapped`);
  }

  const previousClose = Number(state.closes.at(-1));
  const tr = trueRange(Number(bar.high), Number(bar.low), previousClose);
  const closes = appendTrim(state.closes, bar.close, 200);
  const highs = appendTrim(state.highs, bar.high, 50);
  const volumes = appendTrim(state.volumes, bar.volume, 20);
  const trueRanges = appendTrim(state.true_ranges, tr, 14);

  const sma5 = meanLast(closes, 5);
  const sma10 = meanLast(closes, 10);
  const sma20 = meanLast(closes, 20);
  const sma50 = meanLast(closes, 50);
  const sma200 = meanLast(closes, 200);
  const avgVolume20 = meanLast(volumes, 20);
  const atr14 = meanLast(trueRanges, 14);
  const sma50History = appendTrim(state.sma50_history, sma50, 11);
  const sma50Prior10 = sma50History.length === 11 ? Number(sma50History[0]) : null;

  const priorHigh20 = Math.max(...state.highs.slice(-20).map(Number));
  const priorHigh50 = Math.max(...state.highs.slice(-50).map(Number));
  const return20 = Number(bar.close) / Number(state.closes.at(-20)) - 1;
  const return60 = Number(bar.close) / Number(state.closes.at(-60)) - 1;

  const feature = {
    symbol: state.symbol,
    date: tradingDate,
    open: Number(bar.open),
    high: Number(bar.high),
    low: Number(bar.low),
    close: Number(bar.close),
    volume: Number(bar.volume),
    sma5,
    sma10,
    sma20,
    sma50,
    sma200,
    avg_volume20: avgVolume20,
    return20,
    return60,
    high20_prior: priorHigh20,
    high50_prior: priorHigh50,
    true_range: tr,
    atr14,
    avg_dollar_volume20: Number(bar.close) * avgVolume20,
    volume_ratio20: avgVolume20 ? Number(bar.volume) / avgVolume20 : null,
    sma50_slope10: sma50Prior10 ? sma50 / sma50Prior10 - 1 : null,
    extension_atr: atr14 ? (Number(bar.close) - sma20) / atr14 : null,
    breakout20: Number(bar.close) >= priorHigh20,
    breakout50: Number(bar.close) >= priorHigh50,
    distance_from_high20: Number(bar.close) / priorHigh20 - 1,
  };

  const nextState = {
    symbol: state.symbol,
    as_of: tradingDate,
    closes,
    highs,
    volumes,
    true_ranges: trueRanges,
    sma50_history: sma50History,
  };
  return { nextState, feature };
}

function shardForSymbol(symbol) {
  let total = 0;
  for (const character of symbol) total += character.codePointAt(0);
  return total % STATE_SHARDS;
}

function replayRequest(event) {
  const payload = event.payload ?? {};
  if (payload.mode !== "replay") return null;
  const required = ["target_date", "state_metadata_key", "bars_key", "root"];
  for (const field of required) {
    if (!payload[field]) throw new Error(`replay payload is missing ${field}`);
  }
  return payload;
}

export class IncrementalFeatureWorkflow extends WorkflowEntrypoint {
  async run(event, step) {
    const replay = replayRequest(event);
    const source = await step.do("resolve source state and daily bars", async () => {
      const state = replay
        ? await readJson(this.env.RESEARCH, replay.state_metadata_key)
        : await readJson(this.env.RESEARCH, LATEST_STATE_KEY);
      const ingest = replay
        ? { date: replay.target_date, data_key: replay.bars_key }
        : await readJson(this.env.RESEARCH, LATEST_INGEST_KEY);
      if (Number(state.version) !== STATE_VERSION || Number(state.shard_count) !== STATE_SHARDS) {
        throw new Error(
          `unsupported feature state contract: v${state.version}, shards=${state.shard_count}`,
        );
      }
      if (!ingest.date || !ingest.data_key) {
        throw new Error("latest ingestion metadata is incomplete");
      }
      return { state, ingest };
    });

    const statusKey = replay ? `${replay.root}/cloudflare/status.json` : LATEST_WORKFLOW_KEY;
    if (source.ingest.date <= source.state.as_of) {
      const status = {
        status: "no_op",
        mode: replay ? "replay" : "production",
        reason: "ingested session is not newer than feature state",
        state_as_of: source.state.as_of,
        ingest_date: source.ingest.date,
        workflow_instance: event.instanceId,
        updated_at: new Date().toISOString(),
      };
      await step.do(
        "publish no-op status",
        async () => writeJson(this.env.RESEARCH, statusKey, status),
      );
      return status;
    }

    const tradingDate = source.ingest.date;
    const prepared = await step.do("partition daily bars by state shard", async () => {
      const daily = await readJson(this.env.RESEARCH, source.ingest.data_key);
      const shards = Array.from({ length: STATE_SHARDS }, () => []);
      for (const bar of daily.bars ?? []) {
        if (!bar?.symbol) continue;
        shards[shardForSymbol(String(bar.symbol))].push(bar);
      }
      const keys = [];
      for (let shard = 0; shard < STATE_SHARDS; shard += 1) {
        const shardName = String(shard).padStart(2, "0");
        const key = replay
          ? `${replay.root}/cloudflare/work/bars/shard=${shardName}.json`
          : `work/incremental/date=${tradingDate}/bars/shard=${shardName}.json`;
        await writeJson(this.env.RESEARCH, key, {
          date: tradingDate,
          shard,
          bars: shards[shard],
        });
        keys.push(key);
      }
      return { keys, input_count: daily.bars?.length ?? 0 };
    });

    const stateKeys = [];
    const featureKeys = [];
    let updatedSymbols = 0;
    let carriedSymbols = 0;

    for (let shard = 0; shard < STATE_SHARDS; shard += 1) {
      const result = await step.do(
        `update feature shard ${String(shard).padStart(2, "0")}`,
        {
          retries: { limit: 3, delay: "10 seconds", backoff: "exponential" },
          timeout: "5 minutes",
        },
        async () => {
          const sourceStateKey = source.state.keys?.[shard];
          if (!sourceStateKey) throw new Error(`source state key missing for shard ${shard}`);
          const statePayload = await readJson(this.env.RESEARCH, sourceStateKey);
          const barsPayload = await readJson(this.env.RESEARCH, prepared.keys[shard]);
          const bars = new Map(
            (barsPayload.bars ?? []).map((bar) => [String(bar.symbol), bar]),
          );
          const nextStates = [];
          const features = [];
          let updated = 0;
          let carried = 0;

          for (const state of statePayload.states ?? []) {
            const bar = bars.get(String(state.symbol));
            if (!bar) {
              nextStates.push(state);
              carried += 1;
              continue;
            }
            const { nextState, feature } = updateSymbolState(state, bar, tradingDate);
            nextStates.push(nextState);
            features.push(feature);
            updated += 1;
          }

          const shardName = String(shard).padStart(2, "0");
          const stateKey = replay
            ? `${replay.root}/cloudflare/state/shard=${shardName}.json`
            : `state/rolling/v${STATE_VERSION}/date=${tradingDate}/shard=${shardName}.json`;
          const featureKey = replay
            ? `${replay.root}/cloudflare/features/shard=${shardName}.json`
            : `features/daily/date=${tradingDate}/shard=${shardName}.json`;
          await writeJson(this.env.RESEARCH, stateKey, {
            version: STATE_VERSION,
            as_of: tradingDate,
            shard,
            shard_count: STATE_SHARDS,
            count: nextStates.length,
            states: nextStates,
          });
          await writeJson(this.env.RESEARCH, featureKey, {
            version: STATE_VERSION,
            date: tradingDate,
            shard,
            shard_count: STATE_SHARDS,
            count: features.length,
            features,
          });
          return { stateKey, featureKey, updated, carried };
        },
      );
      stateKeys.push(result.stateKey);
      featureKeys.push(result.featureKey);
      updatedSymbols += result.updated;
      carriedSymbols += result.carried;
    }

    const now = new Date().toISOString();
    const stateMetadata = {
      version: STATE_VERSION,
      as_of: tradingDate,
      shard_count: STATE_SHARDS,
      symbol_count: updatedSymbols + carriedSymbols,
      updated_symbol_count: updatedSymbols,
      carried_symbol_count: carriedSymbols,
      prefix: replay
        ? `${replay.root}/cloudflare/state`
        : `state/rolling/v${STATE_VERSION}/date=${tradingDate}`,
      keys: stateKeys,
      producer: "cloudflare-js",
      workflow_instance: event.instanceId,
      updated_at: now,
    };
    const featureMetadata = {
      version: STATE_VERSION,
      date: tradingDate,
      shard_count: STATE_SHARDS,
      feature_count: updatedSymbols,
      input_bar_count: prepared.input_count,
      keys: featureKeys,
      producer: "cloudflare-js",
      workflow_instance: event.instanceId,
      updated_at: now,
    };

    if (replay) {
      const final = await step.do("publish replay feature artifacts", async () => {
        const workflowStatus = {
          status: "complete",
          mode: "replay",
          date: tradingDate,
          state_as_of_before: source.state.as_of,
          feature_count: updatedSymbols,
          carried_symbol_count: carriedSymbols,
          workflow_instance: event.instanceId,
          updated_at: now,
        };
        const replayMetadata = {
          ...workflowStatus,
          state_keys: stateKeys,
          feature_keys: featureKeys,
          input_bar_count: prepared.input_count,
          promoted_latest: false,
        };
        await writeJson(
          this.env.RESEARCH,
          `${replay.root}/cloudflare/metadata.json`,
          replayMetadata,
        );
        await writeJson(this.env.RESEARCH, statusKey, workflowStatus);
        return replayMetadata;
      });
      return final;
    }

    await step.do("publish date-scoped feature metadata", async () => {
      await writeJson(
        this.env.RESEARCH,
        `state/rolling/v${STATE_VERSION}/date=${tradingDate}/metadata.json`,
        stateMetadata,
      );
      await writeJson(
        this.env.RESEARCH,
        `features/daily/date=${tradingDate}/metadata.json`,
        featureMetadata,
      );
    });

    const stagedRanking = await step.do(
      "build JS production ranking",
      {
        retries: { limit: 2, delay: "10 seconds", backoff: "exponential" },
        timeout: "5 minutes",
      },
      async () => runProductionRanking({
        bucket: this.env.RESEARCH,
        db: this.env.DB,
        featureKeys,
        tradingDate,
        workflowInstance: event.instanceId,
      }),
    );

    const final = await step.do("promote complete JS production snapshot", async () => {
      await promoteProductionRanking(this.env.RESEARCH, stagedRanking);
      const workflowStatus = {
        status: "complete",
        mode: "production",
        date: tradingDate,
        state_as_of_before: source.state.as_of,
        feature_count: updatedSymbols,
        carried_symbol_count: carriedSymbols,
        ranking_candidate_count: stagedRanking.rankingMetadata.candidate_count,
        top50_count: stagedRanking.rankingMetadata.top50_count,
        workflow_instance: event.instanceId,
        updated_at: new Date().toISOString(),
      };
      await writeJson(this.env.RESEARCH, LATEST_FEATURES_KEY, featureMetadata);
      await writeJson(this.env.RESEARCH, LATEST_STATE_KEY, stateMetadata);
      await writeJson(this.env.RESEARCH, LATEST_WORKFLOW_KEY, workflowStatus);
      return workflowStatus;
    });

    return final;
  }
}

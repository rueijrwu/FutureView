import { WorkflowEntrypoint } from "cloudflare:workers";
import { updateSymbolState } from "./feature-core.js";
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

function productionRequest(event) {
  const payload = event.payload ?? {};
  if (payload.mode !== "production" || !payload.ingest_date) return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(payload.ingest_date)) {
    throw new Error("production ingest_date must be YYYY-MM-DD");
  }
  return {
    date: payload.ingest_date,
    data_key: `prices/daily-json/date=${payload.ingest_date}/bars.json`,
  };
}

export class IncrementalFeatureWorkflow extends WorkflowEntrypoint {
  async run(event, step) {
    const replay = replayRequest(event);
    const production = replay ? null : productionRequest(event);
    const source = await step.do("resolve source state and daily bars", async () => {
      const state = replay
        ? await readJson(this.env.RESEARCH, replay.state_metadata_key)
        : await readJson(this.env.RESEARCH, LATEST_STATE_KEY);
      const ingest = replay
        ? { date: replay.target_date, data_key: replay.bars_key }
        : production ?? await readJson(this.env.RESEARCH, LATEST_INGEST_KEY);
      if (Number(state.version) !== STATE_VERSION || Number(state.shard_count) !== STATE_SHARDS) {
        throw new Error(
          `unsupported feature state contract: v${state.version}, shards=${state.shard_count}`,
        );
      }
      if (!ingest.date || !ingest.data_key) {
        throw new Error("ingestion metadata is incomplete");
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

    const replayTrigger = await step.do("trigger JS replay validation", async () => {
      try {
        const instance = await this.env.RANKING_REPLAY.create({
          params: { target_date: tradingDate },
        });
        return { id: instance.id };
      } catch (error) {
        console.error(`Unable to trigger JS replay validation for ${tradingDate}`, error);
        return null;
      }
    });

    return {
      ...final,
      replay_instance: replayTrigger?.id ?? null,
    };
  }
}

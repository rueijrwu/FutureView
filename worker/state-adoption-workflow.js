import { WorkflowEntrypoint } from "cloudflare:workers";

const STATE_VERSION = 1;
const STATE_SHARDS = 32;
const LATEST_STATE_KEY = "metadata/latest-feature-state.json";
const BOOTSTRAP_STATUS_KEY = "metadata/latest-feature-bootstrap.json";

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

function validateState(state) {
  return state
    && state.symbol
    && Array.isArray(state.closes)
    && state.closes.length >= 200
    && Array.isArray(state.highs)
    && state.highs.length >= 50
    && Array.isArray(state.volumes)
    && state.volumes.length >= 20
    && Array.isArray(state.true_ranges)
    && state.true_ranges.length >= 14
    && Array.isArray(state.sma50_history)
    && state.sma50_history.length >= 11;
}

export class StateAdoptionWorkflow extends WorkflowEntrypoint {
  async run(event, step) {
    const source = await step.do("resolve legacy feature state", async () => {
      const metadata = await readJson(this.env.RESEARCH, LATEST_STATE_KEY);
      if (String(metadata.producer ?? "").startsWith("cloudflare")) {
        return { alreadyCanonical: true, metadata };
      }
      if (Number(metadata.version) !== STATE_VERSION) {
        throw new Error(`unsupported legacy state version: ${metadata.version}`);
      }
      if (Number(metadata.shard_count) !== STATE_SHARDS) {
        throw new Error(`unsupported legacy shard count: ${metadata.shard_count}`);
      }
      if (!metadata.as_of) throw new Error("legacy state metadata is missing as_of");
      if (!Array.isArray(metadata.keys) || metadata.keys.length !== STATE_SHARDS) {
        throw new Error("legacy state metadata must contain 32 shard keys");
      }
      return { alreadyCanonical: false, metadata };
    });

    if (source.alreadyCanonical) {
      return {
        status: "no_op",
        reason: "feature state is already canonical Cloudflare state",
        as_of: source.metadata.as_of,
        producer: source.metadata.producer,
      };
    }

    const sourceMetadata = source.metadata;
    const targetDate = sourceMetadata.as_of;
    const stateKeys = [];
    let symbolCount = 0;
    let spyFound = false;

    for (let shard = 0; shard < STATE_SHARDS; shard += 1) {
      const shardName = String(shard).padStart(2, "0");
      const result = await step.do(
        `adopt legacy state shard ${shardName}`,
        { retries: { limit: 2, delay: "5 seconds" }, timeout: "2 minutes" },
        async () => {
          const payload = await readJson(this.env.RESEARCH, sourceMetadata.keys[shard]);
          const states = Array.isArray(payload.states) ? payload.states : [];
          const invalid = states.filter((state) => !validateState(state));
          if (invalid.length) {
            throw new Error(`legacy shard ${shardName} contains ${invalid.length} invalid states`);
          }

          const key = `state/rolling/v${STATE_VERSION}/date=${targetDate}/shard=${shardName}.json`;
          await writeJson(this.env.RESEARCH, key, {
            version: STATE_VERSION,
            as_of: targetDate,
            shard,
            shard_count: STATE_SHARDS,
            count: states.length,
            states,
            producer: "cloudflare-js-bootstrap",
            seed_source: "legacy-state-adoption",
          });

          return {
            key,
            count: states.length,
            spyFound: states.some((state) => String(state.symbol) === "SPY"),
          };
        },
      );
      stateKeys.push(result.key);
      symbolCount += result.count;
      spyFound ||= result.spyFound;
    }

    if (!spyFound) {
      throw new Error("legacy feature state does not contain SPY benchmark state");
    }

    return step.do("promote adopted feature state", async () => {
      const now = new Date().toISOString();
      const metadata = {
        version: STATE_VERSION,
        as_of: targetDate,
        shard_count: STATE_SHARDS,
        symbol_count: symbolCount,
        prefix: `state/rolling/v${STATE_VERSION}/date=${targetDate}`,
        keys: stateKeys,
        producer: "cloudflare-js-bootstrap",
        seed_source: "legacy-state-adoption",
        benchmark: "SPY",
        workflow_instance: event.instanceId,
        updated_at: now,
      };

      await writeJson(
        this.env.RESEARCH,
        `state/rolling/v${STATE_VERSION}/date=${targetDate}/metadata.json`,
        metadata,
      );
      await writeJson(this.env.RESEARCH, LATEST_STATE_KEY, metadata);
      await writeJson(this.env.RESEARCH, BOOTSTRAP_STATUS_KEY, {
        status: "complete",
        mode: "legacy-state-adoption",
        source_producer: sourceMetadata.producer ?? null,
        source_as_of: targetDate,
        symbol_count: symbolCount,
        shard_count: STATE_SHARDS,
        benchmark: "SPY",
        workflow_instance: event.instanceId,
        updated_at: now,
      });

      return {
        status: "complete",
        action: "adopt-feature-state",
        as_of: targetDate,
        symbol_count: symbolCount,
        benchmark: "SPY",
        producer: metadata.producer,
      };
    });
  }
}

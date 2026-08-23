import { WorkflowEntrypoint } from "cloudflare:workers";

import { runRankingReplay } from "./ranking-replay.js";

async function readJson(bucket, key) {
  const object = await bucket.get(key);
  if (object === null) throw new Error(`R2 object not found: ${key}`);
  return object.json();
}

export class RankingReplayWorkflow extends WorkflowEntrypoint {
  async run(event, step) {
    const payload = event.payload ?? {};
    const required = [
      "target_date",
      "root",
      "ranking_state_metadata_key",
      "universe_key",
    ];
    for (const field of required) {
      if (!payload[field]) throw new Error(`ranking replay payload is missing ${field}`);
    }

    const featureMetadata = await step.do("resolve replay feature output", async () =>
      readJson(this.env.RESEARCH, `${payload.root}/cloudflare/metadata.json`));

    const ranking = await step.do(
      "compute isolated ranking replay",
      { retries: { limit: 2, delay: "10 seconds" }, timeout: "5 minutes" },
      async () => runRankingReplay({
        bucket: this.env.RESEARCH,
        featureKeys: featureMetadata.feature_keys ?? [],
        tradingDate: payload.target_date,
        rankingStateMetadataKey: payload.ranking_state_metadata_key,
        universeKey: payload.universe_key,
        root: payload.root,
      }),
    );

    return {
      status: "complete",
      mode: "ranking-replay",
      date: payload.target_date,
      ranking_key: ranking.ranking_key,
      candidate_count: ranking.candidate_count,
      promoted_latest: false,
    };
  }
}

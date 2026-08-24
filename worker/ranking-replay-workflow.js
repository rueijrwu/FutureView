import { WorkflowEntrypoint } from "cloudflare:workers";

import { runRankingReplay } from "./ranking-replay.js";

export class RankingReplayWorkflow extends WorkflowEntrypoint {
  async run(event, step) {
    const payload = event.payload ?? {};
    if (!payload.target_date) {
      throw new Error("ranking replay payload is missing target_date");
    }

    const validation = await step.do(
      "recompute and validate JS ranking",
      { retries: { limit: 2, delay: "10 seconds" }, timeout: "5 minutes" },
      async () => runRankingReplay({
        bucket: this.env.RESEARCH,
        db: this.env.DB,
        tradingDate: payload.target_date,
      }),
    );

    return {
      status: validation.status,
      mode: "js-ranking-replay",
      date: payload.target_date,
      candidate_count: validation.candidate_count,
      top50_status: validation.top50_status,
      promoted_latest: false,
    };
  }
}

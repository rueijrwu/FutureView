import worker from "./index.js";
import { BacktestWorkflow } from "./backtest-workflow.js";
import { FeatureBootstrapWorkflow } from "./feature-bootstrap-workflow.js";
import { IncrementalFeatureWorkflow } from "./incremental-workflow.js";
import { maybeHandleManualAdmin } from "./manual-admin.js";
import { RankingReplayWorkflow } from "./ranking-replay-workflow.js";
import { StateAdoptionWorkflow } from "./state-adoption-workflow.js";

export {
  BacktestWorkflow,
  FeatureBootstrapWorkflow,
  IncrementalFeatureWorkflow,
  RankingReplayWorkflow,
  StateAdoptionWorkflow,
};

export default {
  async fetch(request, env, ctx) {
    const manual = await maybeHandleManualAdmin(request, env);
    if (manual) return manual;
    return worker.fetch(request, env, ctx);
  },

  async scheduled(controller, env, ctx) {
    return worker.scheduled(controller, env, ctx);
  },
};

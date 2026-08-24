import { WorkflowEntrypoint } from "cloudflare:workers";

import {
  advanceBacktest,
  createBacktestState,
  finalizeBacktest,
} from "./backtest-core.js";
import {
  BACKTEST_CONFIG_V1,
  STRATEGY_VERSION,
} from "./strategy-config.js";

const FEATURE_SHARDS = 32;

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
  return total % FEATURE_SHARDS;
}

function neededFeatureShards(state) {
  const symbols = new Set([
    ...Object.keys(state.positions ?? {}),
    ...(state.pendingEntries ?? []).map((item) => String(item.symbol)),
    ...(state.pendingExits ?? []).map((item) => String(item.symbol)),
  ]);
  return [...new Set([...symbols].map(shardForSymbol))].sort((a, b) => a - b);
}

async function loadSessionFeatures(bucket, date, rankings, state) {
  const bySymbol = new Map(
    (rankings ?? []).map((row) => [String(row.symbol), row]),
  );
  for (const shard of neededFeatureShards(state)) {
    const shardName = String(shard).padStart(2, "0");
    const key = `features/daily/date=${date}/shard=${shardName}.json`;
    try {
      const payload = await readJson(bucket, key);
      for (const row of payload.features ?? []) {
        if (row?.symbol) bySymbol.set(String(row.symbol), row);
      }
    } catch (error) {
      if (!String(error).includes("R2 object not found")) throw error;
    }
  }
  return bySymbol;
}

async function listRankingRuns(db, lookbackSessions) {
  const { results = [] } = await db.prepare(`
    SELECT trading_date, ranking_r2_key
    FROM ranking_runs
    WHERE strategy_version = ?
    ORDER BY trading_date DESC
    LIMIT ?
  `).bind(STRATEGY_VERSION, lookbackSessions).all();
  return [...results].reverse();
}

async function upsertBacktestRun(db, record) {
  await db.prepare(`
    INSERT INTO backtest_runs (
      id, strategy_version, start_date, end_date, status,
      result_r2_key, summary_json, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
      strategy_version=excluded.strategy_version,
      start_date=excluded.start_date,
      end_date=excluded.end_date,
      status=excluded.status,
      result_r2_key=excluded.result_r2_key,
      summary_json=excluded.summary_json,
      updated_at=excluded.updated_at
  `).bind(
    record.id,
    STRATEGY_VERSION,
    record.startDate ?? null,
    record.endDate ?? null,
    record.status,
    record.resultKey ?? null,
    JSON.stringify(record.summary ?? {}),
    record.createdAt,
    record.updatedAt,
  ).run();
}

export class BacktestWorkflow extends WorkflowEntrypoint {
  async run(event, step) {
    if (!this.env.DB) throw new Error("D1 binding is required for backtests");

    const payload = event.payload ?? {};
    const lookbackSessions = Math.max(
      20,
      Math.min(Number(payload.lookback_sessions ?? 126), 500),
    );
    const runId = String(payload.run_id ?? event.instanceId);
    const createdAt = new Date().toISOString();

    const runs = await step.do("resolve D1 ranking history", async () =>
      listRankingRuns(this.env.DB, lookbackSessions));

    if (runs.length < 2) {
      const status = {
        id: runId,
        strategy_version: STRATEGY_VERSION,
        status: "insufficient_history",
        available_sessions: runs.length,
        requested_sessions: lookbackSessions,
        updated_at: new Date().toISOString(),
      };
      await step.do("record insufficient backtest history", async () => {
        await upsertBacktestRun(this.env.DB, {
          id: runId,
          status: status.status,
          startDate: runs[0]?.trading_date ?? null,
          endDate: runs.at(-1)?.trading_date ?? null,
          summary: status,
          createdAt,
          updatedAt: status.updated_at,
        });
        await writeJson(this.env.RESEARCH, "metadata/latest-backtest.json", status);
      });
      return status;
    }

    let state = createBacktestState(BACKTEST_CONFIG_V1);
    for (let index = 0; index < runs.length; index += 1) {
      const run = runs[index];
      state = await step.do(
        `simulate ${run.trading_date}`,
        { retries: { limit: 2, delay: "5 seconds" }, timeout: "2 minutes" },
        async () => {
          const rankingPayload = await readJson(this.env.RESEARCH, run.ranking_r2_key);
          const rankings = rankingPayload.rankings ?? [];
          const features = await loadSessionFeatures(
            this.env.RESEARCH,
            run.trading_date,
            rankings,
            state,
          );
          return advanceBacktest(
            state,
            { date: run.trading_date, rankings, features },
            BACKTEST_CONFIG_V1,
          );
        },
      );
    }

    const finalized = await step.do("finalize JS backtest", async () =>
      finalizeBacktest(state, BACKTEST_CONFIG_V1));

    const startDate = runs[0].trading_date;
    const endDate = runs.at(-1).trading_date;
    const resultKey = `backtests/run=${runId}/result.json`;
    const result = {
      id: runId,
      strategy_version: STRATEGY_VERSION,
      config: BACKTEST_CONFIG_V1,
      start_date: startDate,
      end_date: endDate,
      status: "complete",
      summary: finalized.summary,
      equity_curve: finalized.equityCurve,
      trades: finalized.trades,
      producer: "cloudflare-js",
      workflow_instance: event.instanceId,
      updated_at: new Date().toISOString(),
    };

    await step.do("publish JS backtest", async () => {
      await writeJson(this.env.RESEARCH, resultKey, result);
      await upsertBacktestRun(this.env.DB, {
        id: runId,
        status: "complete",
        startDate,
        endDate,
        resultKey,
        summary: finalized.summary,
        createdAt,
        updatedAt: result.updated_at,
      });
      await writeJson(this.env.RESEARCH, "metadata/latest-backtest.json", {
        id: runId,
        strategy_version: STRATEGY_VERSION,
        start_date: startDate,
        end_date: endDate,
        status: "complete",
        result_key: resultKey,
        summary: finalized.summary,
        producer: "cloudflare-js",
        updated_at: result.updated_at,
      });
    });

    return {
      id: runId,
      status: "complete",
      start_date: startDate,
      end_date: endDate,
      summary: finalized.summary,
      result_key: resultKey,
    };
  }
}

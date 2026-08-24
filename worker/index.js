import { buildBacktestAudit } from "./backtest-audit.js";
import {
  rankingByDateFromD1,
  rankingDatesFromD1,
  symbolRankingHistoryFromD1,
} from "./d1-read.js";
import { createR2JsonStore } from "./json-store.js";

const CLOUDFLARE_INGEST_METADATA_KEY = "metadata/latest-cloudflare-ingest.json";
const FEATURE_STATE_METADATA_KEY = "metadata/latest-feature-state.json";
const RANKING_STATE_METADATA_KEY = "metadata/latest-ranking-state.json";
const UNIVERSE_METADATA_KEY = "metadata/latest-common-stock-universe.json";
const REPLAY_METADATA_KEY = "metadata/latest-js-replay.json";
const BACKTEST_METADATA_KEY = "metadata/latest-backtest.json";

async function jsonStoreResponse(store, key, unavailableMessage, status = 503) {
  const payload = await store.getJson(key);
  if (payload === null) {
    return Response.json({ error: unavailableMessage }, { status });
  }
  return Response.json(payload, {
    headers: { "cache-control": "no-store" },
  });
}

async function readLatestBacktest(store) {
  const metadata = await store.getJson(BACKTEST_METADATA_KEY);
  if (!metadata) return null;
  if (!metadata.result_key) return metadata;
  return store.getJson(metadata.result_key);
}

async function r2RankingByDate(store, tradingDate) {
  const payload = await store.getJson(`rankings/date=${tradingDate}/top50.json`);
  if (!payload) return null;
  return {
    as_of: tradingDate,
    universe_count: null,
    market_regime: "Research",
    cash_posture: "Rule-based",
    rankings: payload.rankings ?? [],
    source: "r2",
    updated_at: payload.updated_at ?? null,
  };
}

async function rankingResponse(env, store, tradingDate = null) {
  try {
    const payload = await rankingByDateFromD1(env.DB, tradingDate);
    if (payload?.rankings?.length) {
      return Response.json(payload, {
        headers: { "cache-control": "no-store" },
      });
    }
  } catch (error) {
    console.error("D1 ranking query failed; falling back to R2", error);
  }

  if (tradingDate) {
    const payload = await r2RankingByDate(store, tradingDate);
    if (payload) return Response.json(payload, { headers: { "cache-control": "no-store" } });
    return Response.json({ error: `ranking not found for ${tradingDate}` }, { status: 404 });
  }

  return jsonStoreResponse(
    store,
    "dashboard/latest.json",
    "latest ranking is not available",
  );
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const store = createR2JsonStore(env.RESEARCH);

    if (url.pathname === "/api/health") {
      return Response.json({
        service: "futureview-api",
        status: "ok",
        database: env.DB ? "d1-bound" : "unbound",
        storage: "r2",
        runtime: "cloudflare-js",
      });
    }

    if (url.pathname === "/api/rankings/latest") {
      return rankingResponse(env, store);
    }

    if (url.pathname === "/api/rankings/history") {
      try {
        const dates = await rankingDatesFromD1(env.DB, url.searchParams.get("limit") ?? 100);
        return Response.json({ count: dates.length, dates, source: "d1" });
      } catch (error) {
        console.error("Unable to query ranking history", error);
        return Response.json({ error: "ranking history is unavailable" }, { status: 503 });
      }
    }

    const rankingDateMatch = url.pathname.match(/^\/api\/rankings\/date\/(\d{4}-\d{2}-\d{2})$/);
    if (rankingDateMatch) {
      return rankingResponse(env, store, rankingDateMatch[1]);
    }

    const symbolHistoryMatch = url.pathname.match(/^\/api\/symbols\/([^/]+)\/rankings$/);
    if (symbolHistoryMatch) {
      try {
        const symbol = decodeURIComponent(symbolHistoryMatch[1]).toUpperCase();
        const rows = await symbolRankingHistoryFromD1(
          env.DB,
          symbol,
          url.searchParams.get("limit") ?? 100,
        );
        return Response.json({ symbol, count: rows.length, rankings: rows, source: "d1" });
      } catch (error) {
        console.error("Unable to query symbol ranking history", error);
        return Response.json({ error: "symbol ranking history is unavailable" }, { status: 503 });
      }
    }

    if (url.pathname === "/api/ingest/status") {
      return jsonStoreResponse(
        store,
        CLOUDFLARE_INGEST_METADATA_KEY,
        "ingestion has not completed yet",
      );
    }

    if (url.pathname === "/api/universe/status") {
      return jsonStoreResponse(
        store,
        UNIVERSE_METADATA_KEY,
        "common-stock universe has not been published yet",
      );
    }

    if (url.pathname === "/api/state/status") {
      return jsonStoreResponse(
        store,
        FEATURE_STATE_METADATA_KEY,
        "incremental feature state has not been published yet",
      );
    }

    if (url.pathname === "/api/ranking-state/status") {
      return jsonStoreResponse(
        store,
        RANKING_STATE_METADATA_KEY,
        "incremental ranking state has not been published yet",
      );
    }

    if (url.pathname === "/api/replay/status") {
      return jsonStoreResponse(
        store,
        REPLAY_METADATA_KEY,
        "JS replay validation has not completed yet",
      );
    }

    if (url.pathname === "/api/backtests/latest") {
      const result = await readLatestBacktest(store);
      if (!result) {
        return Response.json({ error: "backtest has not completed yet" }, { status: 503 });
      }
      return Response.json(result, { headers: { "cache-control": "no-store" } });
    }

    if (url.pathname === "/api/backtests/audit") {
      const result = await readLatestBacktest(store);
      if (!result) {
        return Response.json({ error: "backtest has not completed yet" }, { status: 503 });
      }
      return Response.json(buildBacktestAudit(result), {
        headers: { "cache-control": "no-store" },
      });
    }

    return env.ASSETS.fetch(request);
  },
};

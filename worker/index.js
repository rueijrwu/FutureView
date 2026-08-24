import {
  rankingByDateFromD1,
  rankingDatesFromD1,
  symbolRankingHistoryFromD1,
} from "./d1-read.js";
import { refreshCommonStockUniverse } from "./universe.js";

const MASSIVE_BASE_URL = "https://api.massive.com";
const CLOUDFLARE_INGEST_METADATA_KEY = "metadata/latest-cloudflare-ingest.json";
const FEATURE_STATE_METADATA_KEY = "metadata/latest-feature-state.json";
const FEATURE_BOOTSTRAP_METADATA_KEY = "metadata/latest-feature-bootstrap.json";
const RANKING_STATE_METADATA_KEY = "metadata/latest-ranking-state.json";
const UNIVERSE_METADATA_KEY = "metadata/latest-common-stock-universe.json";
const REPLAY_METADATA_KEY = "metadata/latest-js-replay.json";
const BACKTEST_METADATA_KEY = "metadata/latest-backtest.json";
const DAILY_CRON = "30 23 * * MON-FRI";
const BACKTEST_CRON = "0 14 * * SUN";

function newYorkDateFromTimestamp(timestampMs) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(timestampMs));

  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function shiftIsoDate(isoDate, days) {
  const date = new Date(`${isoDate}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function isWeekend(isoDate) {
  const day = new Date(`${isoDate}T12:00:00Z`).getUTCDay();
  return day === 0 || day === 6;
}

async function fetchGroupedDaily(env, tradingDate) {
  if (!env.MASSIVE_API_KEY) {
    throw new Error("MASSIVE_API_KEY Worker secret is not configured");
  }

  const url = new URL(
    `/v2/aggs/grouped/locale/us/market/stocks/${tradingDate}`,
    MASSIVE_BASE_URL,
  );
  url.searchParams.set("adjusted", "true");
  url.searchParams.set("apiKey", env.MASSIVE_API_KEY);

  const response = await fetch(url, {
    headers: {
      Accept: "application/json",
      "User-Agent": "FutureView-Cloudflare/0.1",
    },
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Massive HTTP ${response.status}: ${body.slice(0, 300)}`);
  }

  const payload = await response.json();
  if (payload.status && payload.status !== "OK") {
    throw new Error(`Massive returned status ${payload.status}`);
  }
  return payload;
}

function normalizeGroupedDaily(payload, tradingDate) {
  const results = Array.isArray(payload.results) ? payload.results : [];
  return results
    .filter((item) => item && item.T)
    .map((item) => ({
      symbol: String(item.T),
      date: tradingDate,
      open: item.o ?? null,
      high: item.h ?? null,
      low: item.l ?? null,
      close: item.c ?? null,
      volume: item.v ?? null,
    }));
}

async function writeDailySession(env, tradingDate, scheduledTime = null) {
  const dataKey = `prices/daily-json/date=${tradingDate}/bars.json`;
  const existing = await env.RESEARCH.head(dataKey);
  if (existing !== null) {
    const metadata = {
      date: tradingDate,
      source: "massive",
      producer: "cloudflare-js",
      storage_format: "json",
      data_key: dataKey,
      status: "already_exists",
      mode: "production",
      updated_at: new Date().toISOString(),
    };
    await env.RESEARCH.put(CLOUDFLARE_INGEST_METADATA_KEY, JSON.stringify(metadata), {
      httpMetadata: { contentType: "application/json; charset=utf-8" },
    });
    return metadata;
  }

  const payload = await fetchGroupedDaily(env, tradingDate);
  const bars = normalizeGroupedDaily(payload, tradingDate);
  if (!bars.length) {
    throw new Error(`Massive returned no grouped-daily bars for ${tradingDate}`);
  }

  const document = {
    date: tradingDate,
    adjusted: true,
    source: "massive",
    producer: "cloudflare-js",
    count: bars.length,
    bars,
  };

  await env.RESEARCH.put(dataKey, JSON.stringify(document), {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
  });

  const metadata = {
    date: tradingDate,
    source: "massive",
    producer: "cloudflare-js",
    storage_format: "json",
    data_key: dataKey,
    count: bars.length,
    status: "written",
    scheduled_time: scheduledTime ? new Date(scheduledTime).toISOString() : null,
    updated_at: new Date().toISOString(),
    mode: "production",
  };

  await env.RESEARCH.put(CLOUDFLARE_INGEST_METADATA_KEY, JSON.stringify(metadata), {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
  });

  console.log(`Cloudflare ingest complete for ${tradingDate}: ${bars.length} bars`);
  return metadata;
}

async function ingestLatestAvailableSession(env, scheduledTime) {
  const targetDate = newYorkDateFromTimestamp(scheduledTime);

  for (let offset = 0; offset <= 7; offset += 1) {
    const tradingDate = shiftIsoDate(targetDate, -offset);
    if (isWeekend(tradingDate)) continue;

    try {
      return await writeDailySession(env, tradingDate, scheduledTime);
    } catch (error) {
      if (String(error).includes("no grouped-daily bars")) continue;
      throw error;
    }
  }

  throw new Error(`No Massive grouped-daily session found on or before ${targetDate}`);
}

async function hasCloudflareFeatureState(env) {
  const object = await env.RESEARCH.get(FEATURE_STATE_METADATA_KEY);
  if (object === null) return false;
  const metadata = await object.json();
  return String(metadata.producer ?? "").startsWith("cloudflare");
}

async function r2JsonResponse(env, key, unavailableMessage, status = 503) {
  const object = await env.RESEARCH.get(key);
  if (object === null) {
    return Response.json({ error: unavailableMessage }, { status });
  }

  return new Response(object.body, {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

async function r2RankingByDate(env, tradingDate) {
  const object = await env.RESEARCH.get(`rankings/date=${tradingDate}/top50.json`);
  if (!object) return null;
  const payload = await object.json();
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

async function rankingResponse(env, tradingDate = null) {
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
    const payload = await r2RankingByDate(env, tradingDate);
    if (payload) return Response.json(payload, { headers: { "cache-control": "no-store" } });
    return Response.json({ error: `ranking not found for ${tradingDate}` }, { status: 404 });
  }

  return r2JsonResponse(
    env,
    "dashboard/latest.json",
    "latest ranking is not available",
  );
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

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
      return rankingResponse(env);
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
      return rankingResponse(env, rankingDateMatch[1]);
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
      return r2JsonResponse(
        env,
        CLOUDFLARE_INGEST_METADATA_KEY,
        "Cloudflare ingestion has not completed yet",
      );
    }

    if (url.pathname === "/api/universe/status") {
      return r2JsonResponse(
        env,
        UNIVERSE_METADATA_KEY,
        "common-stock universe has not been published yet",
      );
    }

    if (url.pathname === "/api/state/status") {
      return r2JsonResponse(
        env,
        FEATURE_STATE_METADATA_KEY,
        "incremental feature state has not been published yet",
      );
    }

    if (url.pathname === "/api/bootstrap/status") {
      return r2JsonResponse(
        env,
        FEATURE_BOOTSTRAP_METADATA_KEY,
        "JS feature bootstrap has not completed yet",
      );
    }

    if (url.pathname === "/api/ranking-state/status") {
      return r2JsonResponse(
        env,
        RANKING_STATE_METADATA_KEY,
        "incremental ranking state has not been published yet",
      );
    }

    if (url.pathname === "/api/replay/status") {
      return r2JsonResponse(
        env,
        REPLAY_METADATA_KEY,
        "JS replay validation has not completed yet",
      );
    }

    if (url.pathname === "/api/backtests/latest") {
      const pointer = await env.RESEARCH.get(BACKTEST_METADATA_KEY);
      if (!pointer) {
        return Response.json({ error: "backtest has not completed yet" }, { status: 503 });
      }
      const metadata = await pointer.json();
      if (!metadata.result_key) return Response.json(metadata);
      return r2JsonResponse(env, metadata.result_key, "backtest result is unavailable");
    }

    return env.ASSETS.fetch(request);
  },

  async scheduled(controller, env, ctx) {
    if (controller.cron === BACKTEST_CRON) {
      ctx.waitUntil(
        (async () => {
          const instance = await env.BACKTEST.create({
            params: { lookback_sessions: 126 },
          });
          console.log(`Weekly JS backtest started: ${instance.id}`);
        })(),
      );
      return;
    }

    if (controller.cron !== DAILY_CRON) {
      console.warn(`Ignoring unknown cron trigger: ${controller.cron}`);
      return;
    }

    ctx.waitUntil(
      (async () => {
        const targetDate = newYorkDateFromTimestamp(controller.scheduledTime);
        const universe = await refreshCommonStockUniverse(env, targetDate);
        console.log(`Common-stock universe ready for ${universe.as_of}: ${universe.count}`);

        const ingest = await ingestLatestAvailableSession(env, controller.scheduledTime);
        if (!(await hasCloudflareFeatureState(env))) {
          const bootstrap = await env.FEATURE_BOOTSTRAP.create({
            params: { target_date: ingest.date },
          });
          console.log(`JS feature bootstrap started for ${ingest.date}: ${bootstrap.id}`);
          return;
        }

        const instance = await env.INCREMENTAL_FEATURES.create({
          params: {
            mode: "production",
            ingest_date: ingest.date,
          },
        });
        console.log(
          `Incremental feature workflow started for ${ingest.date}: ${instance.id}`,
        );
      })(),
    );
  },
};

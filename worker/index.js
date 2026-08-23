const MASSIVE_BASE_URL = "https://api.massive.com";
const CLOUDFLARE_INGEST_METADATA_KEY = "metadata/latest-cloudflare-ingest.json";
const FEATURE_STATE_METADATA_KEY = "metadata/latest-feature-state.json";

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
      producer: "cloudflare-worker",
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
    producer: "cloudflare-worker",
    count: bars.length,
    bars,
  };

  await env.RESEARCH.put(dataKey, JSON.stringify(document), {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
  });

  const metadata = {
    date: tradingDate,
    source: "massive",
    producer: "cloudflare-worker",
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

async function r2JsonResponse(env, key, unavailableMessage) {
  const object = await env.RESEARCH.get(key);
  if (object === null) {
    return Response.json({ error: unavailableMessage }, { status: 503 });
  }

  return new Response(object.body, {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/api/health") {
      return Response.json({
        service: "futureview-api",
        status: "ok",
      });
    }

    if (url.pathname === "/api/rankings/latest") {
      return r2JsonResponse(
        env,
        "dashboard/latest.json",
        "latest ranking is not available",
      );
    }

    if (url.pathname === "/api/ingest/status") {
      return r2JsonResponse(
        env,
        CLOUDFLARE_INGEST_METADATA_KEY,
        "Cloudflare ingestion has not completed yet",
      );
    }

    if (url.pathname === "/api/state/status") {
      return r2JsonResponse(
        env,
        FEATURE_STATE_METADATA_KEY,
        "incremental feature state has not been published yet",
      );
    }

    return env.ASSETS.fetch(request);
  },

  async scheduled(controller, env, ctx) {
    ctx.waitUntil(ingestLatestAvailableSession(env, controller.scheduledTime));
  },
};

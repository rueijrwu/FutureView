const MASSIVE_BASE_URL = "https://api.massive.com";
const CLOUDFLARE_INGEST_METADATA_KEY = "metadata/latest-cloudflare-ingest.json";

async function writeJson(bucket, key, payload) {
  await bucket.put(key, JSON.stringify(payload), {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
  });
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

export function normalizeGroupedDaily(payload, tradingDate) {
  const results = Array.isArray(payload.results) ? payload.results : [];
  const bars = [];

  for (const item of results) {
    if (!item?.T) continue;
    const values = [item.o, item.h, item.l, item.c, item.v].map(Number);
    if (!values.every(Number.isFinite)) continue;

    bars.push({
      symbol: String(item.T),
      date: tradingDate,
      open: values[0],
      high: values[1],
      low: values[2],
      close: values[3],
      volume: values[4],
    });
  }

  return bars;
}

export async function writeDailySession(env, tradingDate) {
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
    await writeJson(env.RESEARCH, CLOUDFLARE_INGEST_METADATA_KEY, metadata);
    return metadata;
  }

  const payload = await fetchGroupedDaily(env, tradingDate);
  const bars = normalizeGroupedDaily(payload, tradingDate);
  if (!bars.length) {
    throw new Error(`Massive returned no valid grouped-daily bars for ${tradingDate}`);
  }

  const rawCount = Array.isArray(payload.results) ? payload.results.length : 0;
  const document = {
    date: tradingDate,
    adjusted: true,
    source: "massive",
    producer: "cloudflare-js",
    count: bars.length,
    bars,
  };
  await writeJson(env.RESEARCH, dataKey, document);

  const metadata = {
    date: tradingDate,
    source: "massive",
    producer: "cloudflare-js",
    storage_format: "json",
    data_key: dataKey,
    count: bars.length,
    discarded_count: Math.max(0, rawCount - bars.length),
    status: "written",
    mode: "production",
    updated_at: new Date().toISOString(),
  };
  await writeJson(env.RESEARCH, CLOUDFLARE_INGEST_METADATA_KEY, metadata);

  console.log(`Cloudflare ingest complete for ${tradingDate}: ${bars.length} bars`);
  return metadata;
}

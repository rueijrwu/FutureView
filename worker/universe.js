import { persistUniverseToD1 } from "./d1.js";

const MASSIVE_BASE_URL = "https://api.massive.com";
const LATEST_UNIVERSE_KEY = "metadata/latest-common-stock-universe.json";

async function fetchJson(url) {
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

async function collectCommonStocks(apiKey) {
  const instruments = [];
  let url = new URL("/v3/reference/tickers", MASSIVE_BASE_URL);
  url.searchParams.set("market", "stocks");
  url.searchParams.set("locale", "us");
  url.searchParams.set("active", "true");
  url.searchParams.set("type", "CS");
  url.searchParams.set("order", "asc");
  url.searchParams.set("sort", "ticker");
  url.searchParams.set("limit", "1000");
  url.searchParams.set("apiKey", apiKey);

  while (url) {
    const payload = await fetchJson(url);
    for (const item of payload.results ?? []) {
      if (item?.ticker && item.type === "CS" && item.active !== false) instruments.push(item);
    }
    if (!payload.next_url) break;
    url = new URL(payload.next_url);
    if (!url.searchParams.has("apiKey")) url.searchParams.set("apiKey", apiKey);
  }

  instruments.sort((a, b) => String(a.ticker).localeCompare(String(b.ticker)));
  return instruments;
}

async function readJsonOrNull(bucket, key) {
  const object = await bucket.get(key);
  return object === null ? null : object.json();
}

async function writeJson(bucket, key, payload) {
  await bucket.put(key, JSON.stringify(payload), {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
  });
}

export async function refreshCommonStockUniverse(env, asOf) {
  if (!env.MASSIVE_API_KEY) throw new Error("MASSIVE_API_KEY Worker secret is not configured");

  const existing = await readJsonOrNull(env.RESEARCH, LATEST_UNIVERSE_KEY);
  if (existing?.as_of === asOf && existing?.data_key) return existing;

  const instruments = await collectCommonStocks(env.MASSIVE_API_KEY);
  if (!instruments.length) throw new Error("Massive common-stock universe is empty");

  const symbols = instruments.map((item) => String(item.ticker));
  const dataKey = `reference/tickers/date=${asOf}/common-stocks.json`;
  const now = new Date().toISOString();
  const payload = {
    as_of: asOf,
    count: symbols.length,
    symbols,
    instruments,
    source: "massive",
    producer: "cloudflare-js",
    updated_at: now,
  };
  await writeJson(env.RESEARCH, dataKey, payload);

  await persistUniverseToD1(env.DB, {
    asOf,
    r2Key: dataKey,
    instruments,
    createdAt: now,
  });

  const metadata = {
    as_of: asOf,
    count: symbols.length,
    data_key: dataKey,
    source: "massive",
    producer: "cloudflare-js",
    updated_at: now,
  };
  await writeJson(env.RESEARCH, LATEST_UNIVERSE_KEY, metadata);
  return metadata;
}

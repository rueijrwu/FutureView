import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const ROOT = ".local-data";
const OBJECTS_ROOT = path.join(ROOT, "objects");
const REFERENCE_ROOT = path.join(ROOT, "reference", "ticker-overview");
const LATEST_UNIVERSE = path.join(OBJECTS_ROOT, "metadata", "latest-common-stock-universe.json");
const LOCAL_BACKTEST_SESSION_ROOT = path.join(".local-backtest", "sessions");
const MASSIVE_BASE_URL = "https://api.massive.com";
const DEFAULT_PACE_MS = 13_000;
const MAX_RETRIES = 4;

function fail(message) {
  console.error(`\n[local:sector:enrich] ERROR: ${message}`);
  process.exit(1);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function loadDevVars() {
  if (!existsSync(".dev.vars")) return {};
  const out = {};
  for (const raw of readFileSync(".dev.vars", "utf8").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const idx = line.indexOf("=");
    if (idx < 1) continue;
    let value = line.slice(idx + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    out[line.slice(0, idx).trim()] = value;
  }
  return out;
}

function massiveApiKey() {
  return process.env.MASSIVE_API_KEY || loadDevVars().MASSIVE_API_KEY || null;
}

function parseArgs() {
  const out = {
    asOf: null,
    limit: null,
    paceMs: DEFAULT_PACE_MS,
    refresh: false,
    symbols: null,
    rankingScope: "all",
    shardIndex: null,
    shardCount: null,
  };
  for (const arg of process.argv.slice(2)) {
    if (arg.startsWith("--as-of=")) out.asOf = arg.slice(8);
    else if (arg.startsWith("--limit=")) out.limit = Number(arg.slice(8));
    else if (arg.startsWith("--pace-ms=")) out.paceMs = Number(arg.slice(10));
    else if (arg.startsWith("--symbols=")) {
      out.symbols = new Set(arg.slice(10).split(",").map((value) => value.trim()).filter(Boolean));
    } else if (arg.startsWith("--ranking-scope=")) out.rankingScope = arg.slice(16);
    else if (arg.startsWith("--shard-index=")) out.shardIndex = Number(arg.slice(14));
    else if (arg.startsWith("--shard-count=")) out.shardCount = Number(arg.slice(14));
    else if (arg === "--refresh") out.refresh = true;
    else fail(`unknown argument: ${arg}`);
  }
  if (!out.asOf || !/^\d{4}-\d{2}-\d{2}$/.test(out.asOf)) {
    fail("--as-of=YYYY-MM-DD is required; use the backtest start date to keep metadata point-in-time");
  }
  if (out.limit != null && (!Number.isInteger(out.limit) || out.limit < 1)) fail("--limit must be a positive integer");
  if (!Number.isFinite(out.paceMs) || out.paceMs < 0) fail("--pace-ms must be >= 0");
  if (!new Set(["all", "ranked", "top50"]).has(out.rankingScope)) fail("--ranking-scope must be all, ranked, or top50");
  const shardSpecified = out.shardIndex != null || out.shardCount != null;
  if (shardSpecified) {
    if (!Number.isInteger(out.shardCount) || out.shardCount < 1) fail("--shard-count must be a positive integer");
    if (!Number.isInteger(out.shardIndex) || out.shardIndex < 0 || out.shardIndex >= out.shardCount) {
      fail("--shard-index must be an integer from 0 to shard-count-1");
    }
  }
  return out;
}

function objectPath(key) {
  return path.join(OBJECTS_ROOT, ...String(key).split("/"));
}

function readJson(file) {
  return JSON.parse(readFileSync(file, "utf8"));
}

function writeJson(file, payload) {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify(payload));
}

function loadUniverse() {
  if (!existsSync(LATEST_UNIVERSE)) fail("latest common-stock universe is missing; run npm run local:sync first");
  const pointer = readJson(LATEST_UNIVERSE);
  if (!pointer?.data_key) fail("latest common-stock universe pointer has no data_key");
  const file = objectPath(pointer.data_key);
  if (!existsSync(file)) fail(`universe payload is missing: ${file}`);
  const payload = readJson(file);
  if (!Array.isArray(payload?.symbols) || !payload.symbols.length) fail("common-stock universe is empty");
  return { asOf: payload.as_of ?? pointer.as_of ?? null, symbols: payload.symbols.map(String).sort() };
}

function loadRankingScope(scope) {
  if (scope === "all") return null;
  if (!existsSync(LOCAL_BACKTEST_SESSION_ROOT)) fail(".local-backtest/sessions is missing; run npm run local:backtest -- --rebuild first");
  const files = readdirSync(LOCAL_BACKTEST_SESSION_ROOT).filter((name) => /^\d{4}-\d{2}-\d{2}\.json$/.test(name)).sort();
  if (!files.length) fail("no local backtest session artifacts found");
  const symbols = new Set();
  let rankingRows = 0;
  for (const name of files) {
    let payload;
    try { payload = readJson(path.join(LOCAL_BACKTEST_SESSION_ROOT, name)); } catch { continue; }
    for (const row of Array.isArray(payload?.rankings) ? payload.rankings : []) {
      if (!row?.symbol) continue;
      if (scope === "top50" && Number(row.rank) > 50) continue;
      symbols.add(String(row.symbol));
      rankingRows += 1;
    }
  }
  if (!symbols.size) fail(`ranking scope ${scope} selected no symbols`);
  return { symbols, sessionCount: files.length, rankingRows };
}

function safeSymbol(symbol) { return encodeURIComponent(String(symbol)); }
function recordPath(asOf, symbol) { return path.join(REFERENCE_ROOT, `as-of=${asOf}`, "symbols", `${safeSymbol(symbol)}.json`); }
function manifestPath(asOf) { return path.join(REFERENCE_ROOT, `as-of=${asOf}`, "manifest.json"); }

async function fetchOverview(symbol, asOf, apiKey) {
  const url = new URL(`/v3/reference/tickers/${encodeURIComponent(symbol)}`, MASSIVE_BASE_URL);
  url.searchParams.set("date", asOf);
  url.searchParams.set("apiKey", apiKey);
  for (let attempt = 0; attempt < MAX_RETRIES; attempt += 1) {
    let response;
    try {
      response = await fetch(url, { headers: { Accept: "application/json", "User-Agent": "FutureView-Sector-Enrichment/1.0" }, signal: AbortSignal.timeout(30_000) });
    } catch (error) {
      if (attempt + 1 >= MAX_RETRIES) throw new Error(`transport error: ${error.message}`);
      const delay = 2_000 * (attempt + 1);
      console.warn(`[local:sector:enrich] ${symbol}: transport error; retry in ${(delay / 1000).toFixed(1)}s`);
      await sleep(delay);
      continue;
    }
    if (response.ok) {
      const payload = await response.json();
      if (!payload || typeof payload !== "object") throw new Error("Massive returned non-object JSON");
      if (payload.status && payload.status !== "OK") throw new Error(`Massive status ${payload.status}`);
      return { kind: "ok", payload };
    }
    const body = await response.text();
    if (response.status === 404 || response.status === 400) return { kind: "unavailable", status: response.status, detail: body.slice(0, 300) };
    if (response.status === 401 || response.status === 403) throw new Error(`FATAL_AUTH HTTP ${response.status}: ${body.slice(0, 300)}`);
    const retryable = response.status === 429 || response.status >= 500;
    if (!retryable || attempt + 1 >= MAX_RETRIES) throw new Error(`HTTP ${response.status}: ${body.slice(0, 300)}`);
    const retryAfter = Number(response.headers.get("retry-after"));
    const delay = Number.isFinite(retryAfter) && retryAfter >= 0 ? Math.max(1_000, retryAfter * 1000) : 15_000 * (attempt + 1);
    console.warn(`[local:sector:enrich] ${symbol}: HTTP ${response.status}; retry in ${(delay / 1000).toFixed(1)}s`);
    await sleep(delay);
  }
  throw new Error("request exhausted retries");
}

function normalizeOverview(symbol, asOf, response) {
  const now = new Date().toISOString();
  if (response.kind === "unavailable") return { symbol, as_of: asOf, status: "unavailable_as_of", http_status: response.status, detail: response.detail, source: "massive-ticker-overview", updated_at: now };
  const item = response.payload?.results ?? null;
  if (!item || typeof item !== "object") return { symbol, as_of: asOf, status: "missing_results", source: "massive-ticker-overview", updated_at: now };
  return {
    symbol, as_of: asOf, status: "ok", ticker: item.ticker ?? symbol, name: item.name ?? null, type: item.type ?? null,
    active: item.active ?? null, primary_exchange: item.primary_exchange ?? null, cik: item.cik ?? null,
    sic_code: item.sic_code == null ? null : String(item.sic_code), sic_description: item.sic_description ?? null,
    description: item.description ?? null, market_cap: item.market_cap ?? null, list_date: item.list_date ?? null,
    source: "massive-ticker-overview", updated_at: now,
  };
}

function summarize(asOf, universeAsOf, symbols) {
  const statusCounts = {};
  const sicCounts = {};
  const missingSic = [];
  let cached = 0;
  for (const symbol of symbols) {
    const file = recordPath(asOf, symbol);
    if (!existsSync(file)) continue;
    cached += 1;
    try {
      const row = readJson(file);
      const status = String(row.status ?? "unknown");
      statusCounts[status] = (statusCounts[status] ?? 0) + 1;
      if (row.sic_code) sicCounts[row.sic_code] = (sicCounts[row.sic_code] ?? 0) + 1;
      else if (missingSic.length < 50) missingSic.push(symbol);
    } catch { statusCounts.unreadable = (statusCounts.unreadable ?? 0) + 1; }
  }
  const withSic = Object.values(sicCounts).reduce((sum, value) => sum + Number(value), 0);
  return {
    version: 1, as_of: asOf, universe_as_of: universeAsOf, universe_count: symbols.length, cached_count: cached,
    remaining_count: Math.max(0, symbols.length - cached), with_sic_count: withSic,
    sic_coverage_of_cached: cached ? withSic / cached : null, status_counts: statusCounts, sic_code_counts: sicCounts,
    sample_missing_sic: missingSic, source: "massive-ticker-overview", producer: "codespaces-local-js", updated_at: new Date().toISOString(),
  };
}

const options = parseArgs();
const apiKey = massiveApiKey();
if (!apiKey) fail("MASSIVE_API_KEY is unavailable in the environment or .dev.vars");
const universe = loadUniverse();
const universeSet = new Set(universe.symbols);
const rankingScope = loadRankingScope(options.rankingScope);
let symbols = rankingScope ? [...rankingScope.symbols].filter((symbol) => universeSet.has(symbol)).sort() : universe.symbols;
if (options.symbols) symbols = symbols.filter((symbol) => options.symbols.has(symbol));
if (options.shardCount != null) symbols = symbols.filter((_, index) => index % options.shardCount === options.shardIndex);
if (options.limit != null) symbols = symbols.slice(0, options.limit);
if (!symbols.length) fail("no symbols selected from the current common-stock universe");

console.log(`[local:sector:enrich] point-in-time as-of=${options.asOf}`);
console.log(`[local:sector:enrich] universe snapshot=${universe.asOf ?? "unknown"}; selected=${symbols.length}`);
console.log(`[local:sector:enrich] ranking-scope=${options.rankingScope}${rankingScope ? ` sessions=${rankingScope.sessionCount} unique=${rankingScope.symbols.size}` : ""}`);
if (options.shardCount != null) console.log(`[local:sector:enrich] shard=${options.shardIndex + 1}/${options.shardCount}`);
console.log(`[local:sector:enrich] pace=${options.paceMs}ms; refresh=${options.refresh ? "yes" : "no"}`);

let fetched = 0;
let skipped = 0;
let failed = 0;
for (let index = 0; index < symbols.length; index += 1) {
  const symbol = symbols[index];
  const file = recordPath(options.asOf, symbol);
  if (!options.refresh && existsSync(file)) { skipped += 1; continue; }
  try {
    const response = await fetchOverview(symbol, options.asOf, apiKey);
    const record = normalizeOverview(symbol, options.asOf, response);
    writeJson(file, record);
    fetched += 1;
    console.log(`[local:sector:enrich] ${index + 1}/${symbols.length} ${symbol}: ${record.status}${record.sic_code ? ` SIC=${record.sic_code} ${record.sic_description ?? ""}` : ""}`);
  } catch (error) {
    if (String(error.message).startsWith("FATAL_AUTH")) fail(`${symbol}: ${error.message}`);
    failed += 1;
    console.error(`[local:sector:enrich] ${index + 1}/${symbols.length} ${symbol}: FAILED ${error.message}`);
  }
  if (index + 1 < symbols.length && options.paceMs > 0) await sleep(options.paceMs);
}

const fullSummary = summarize(options.asOf, universe.asOf, universe.symbols);
writeJson(manifestPath(options.asOf), fullSummary);
const selectedSummary = summarize(options.asOf, universe.asOf, symbols);
console.log("\n[local:sector:enrich] READY");
console.log(`[local:sector:enrich] selected=${symbols.length}; fetched=${fetched}; cached-skip=${skipped}; failed=${failed}`);
console.log(`[local:sector:enrich] selected SIC=${selectedSummary.with_sic_count}/${selectedSummary.cached_count} (${selectedSummary.cached_count ? `${(100 * selectedSummary.with_sic_count / selectedSummary.cached_count).toFixed(2)}%` : "n/a"})`);
console.log(`[local:sector:enrich] full cache=${fullSummary.cached_count}/${fullSummary.universe_count}; SIC=${fullSummary.with_sic_count}; remaining=${fullSummary.remaining_count}`);
console.log(`[local:sector:enrich] manifest: ${manifestPath(options.asOf)}`);

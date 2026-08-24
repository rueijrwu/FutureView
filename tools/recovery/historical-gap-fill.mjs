import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";

const WRANGLER_VERSION = "4.125.0";
const DATABASE = "futureview";
const BUCKET = "futureview-data";
const MASSIVE_BASE_URL = "https://api.massive.com";
const LOCAL_OBJECT_ROOT = ".local-data/objects";
const REQUIRED_SESSIONS = 337;
const REQUEST_SPACING_MS = 13_000;
const MAX_RETRIES = 4;

function fail(message) {
  console.error(`\n[history:fill] ERROR: ${message}`);
  process.exit(1);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function shiftDate(iso, days) {
  const date = new Date(`${iso}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function isWeekend(iso) {
  const day = new Date(`${iso}T12:00:00Z`).getUTCDay();
  return day === 0 || day === 6;
}

function parseArgs() {
  const out = { requiredSessions: REQUIRED_SESSIONS, limit: Infinity, dryRun: false };
  for (const arg of process.argv.slice(2)) {
    if (arg === "--dry-run") out.dryRun = true;
    else if (arg.startsWith("--required-sessions=")) out.requiredSessions = Number(arg.slice(20));
    else if (arg.startsWith("--limit=")) out.limit = Number(arg.slice(8));
    else fail(`unknown argument: ${arg}`);
  }
  if (!Number.isInteger(out.requiredSessions) || out.requiredSessions < 1) fail("--required-sessions must be a positive integer");
  if (!(out.limit === Infinity || (Number.isInteger(out.limit) && out.limit > 0))) fail("--limit must be a positive integer");
  return out;
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
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    out[line.slice(0, idx).trim()] = value;
  }
  return out;
}

const devVars = loadDevVars();
const massiveKey = process.env.MASSIVE_API_KEY || devVars.MASSIVE_API_KEY;
const accountId = process.env.R2_ACCOUNT_ID || devVars.R2_ACCOUNT_ID;
const cloudflareToken = process.env.CLOUDFLARE_API_TOKEN || devVars.CLOUDFLARE_API_TOKEN;

if (!massiveKey) fail("MASSIVE_API_KEY is required");
if (!accountId) fail("R2_ACCOUNT_ID is required");
if (!cloudflareToken) fail("CLOUDFLARE_API_TOKEN is required");

function wrangler(args, { json = false } = {}) {
  const result = spawnSync("npx", ["--yes", `wrangler@${WRANGLER_VERSION}`, ...args], {
    encoding: "utf8",
    env: { ...process.env, CLOUDFLARE_API_TOKEN: cloudflareToken, CLOUDFLARE_ACCOUNT_ID: accountId },
    maxBuffer: 128 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error((result.stderr || result.stdout || `wrangler exited ${result.status}`).trim());
  }
  if (!json) return result.stdout;
  return JSON.parse(result.stdout);
}

function quoteSql(value) {
  if (value == null) return "NULL";
  return `'${String(value).replaceAll("'", "''")}'`;
}

function ensureD1Table() {
  wrangler(["d1", "execute", DATABASE, "--remote", "--file", "migrations/0003_market_data_sessions.sql"]);
}

function localHistoricalDates() {
  const root = path.join(LOCAL_OBJECT_ROOT, "prices", "daily");
  if (!existsSync(root)) return [];
  return readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && /^date=\d{4}-\d{2}-\d{2}$/.test(entry.name))
    .map((entry) => entry.name.slice(5))
    .sort();
}

async function fetchGroupedDaily(date) {
  const url = new URL(`/v2/aggs/grouped/locale/us/market/stocks/${date}`, MASSIVE_BASE_URL);
  url.searchParams.set("adjusted", "true");
  url.searchParams.set("apiKey", massiveKey);

  for (let attempt = 0; attempt < MAX_RETRIES; attempt += 1) {
    const response = await fetch(url, { headers: { Accept: "application/json", "User-Agent": "FutureView-HistoricalGapFill/1.0" } });
    if (response.ok) {
      const payload = await response.json();
      const raw = Array.isArray(payload.results) ? payload.results : [];
      const bars = raw
        .filter((row) => row?.T && row.o != null && row.h != null && row.l != null && row.c != null && row.v != null)
        .map((row) => ({
          symbol: String(row.T),
          date,
          open: Number(row.o),
          high: Number(row.h),
          low: Number(row.l),
          close: Number(row.c),
          volume: Number(row.v),
        }))
        .filter((row) => [row.open, row.high, row.low, row.close, row.volume].every(Number.isFinite));
      return bars;
    }
    const body = await response.text();
    const retryable = response.status === 429 || response.status >= 500;
    if (!retryable || attempt + 1 >= MAX_RETRIES) throw new Error(`Massive HTTP ${response.status} for ${date}: ${body.slice(0, 300)}`);
    const retryAfter = Number(response.headers.get("retry-after"));
    const delay = Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : 15_000 * (attempt + 1);
    console.warn(`[history:fill] Massive ${response.status} for ${date}; retrying after ${(delay / 1000).toFixed(0)}s`);
    await sleep(delay);
  }
  return [];
}

async function remoteR2Json(key) {
  const url = `https://api.cloudflare.com/client/v4/accounts/${encodeURIComponent(accountId)}/r2/buckets/${encodeURIComponent(BUCKET)}/objects/${encodeURIComponent(key)}`;
  const response = await fetch(url, { headers: { Authorization: `Bearer ${cloudflareToken}` } });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`R2 GET ${key} failed HTTP ${response.status}: ${(await response.text()).slice(0, 300)}`);
  return await response.json();
}

function d1Rows(sql) {
  const payload = wrangler(["d1", "execute", DATABASE, "--remote", "--json", "--command", sql], { json: true });
  const statement = Array.isArray(payload) ? payload[0] : payload;
  return Array.isArray(statement?.results) ? statement.results : [];
}

function upsertD1(record) {
  const sql = `INSERT INTO market_data_sessions (trading_date,r2_key,row_count,sha256,source,producer,storage_format,created_at,updated_at) VALUES (${quoteSql(record.tradingDate)},${quoteSql(record.r2Key)},${record.rowCount},${quoteSql(record.sha256)},${quoteSql("massive")},${quoteSql("codespaces-gap-fill")},${quoteSql("json")},${quoteSql(record.now)},${quoteSql(record.now)}) ON CONFLICT(trading_date) DO UPDATE SET r2_key=excluded.r2_key,row_count=excluded.row_count,sha256=excluded.sha256,source=excluded.source,producer=excluded.producer,storage_format=excluded.storage_format,updated_at=excluded.updated_at;`;
  wrangler(["d1", "execute", DATABASE, "--remote", "--command", sql]);
}

async function writeAndVerify(date, bars) {
  const r2Key = `prices/daily-json/date=${date}/bars.json`;
  const now = new Date().toISOString();
  const document = {
    date,
    adjusted: true,
    source: "massive",
    producer: "codespaces-gap-fill",
    count: bars.length,
    bars,
  };
  const body = Buffer.from(`${JSON.stringify(document)}\n`);
  const sha256 = createHash("sha256").update(body).digest("hex");
  const tmpFile = `/tmp/futureview-${date}.json`;
  writeFileSync(tmpFile, body);

  wrangler(["r2", "object", "put", `${BUCKET}/${r2Key}`, "--file", tmpFile, "--content-type", "application/json", "--remote"]);
  upsertD1({ tradingDate: date, r2Key, rowCount: bars.length, sha256, now });

  const remote = await remoteR2Json(r2Key);
  if (!remote || remote.date !== date || !Array.isArray(remote.bars) || remote.bars.length !== bars.length) {
    throw new Error(`R2 read-back verification failed for ${date}`);
  }
  const rows = d1Rows(`SELECT trading_date,r2_key,row_count,sha256 FROM market_data_sessions WHERE trading_date=${quoteSql(date)} LIMIT 1`);
  const row = rows[0];
  if (!row || row.trading_date !== date || row.r2_key !== r2Key || Number(row.row_count) !== bars.length || row.sha256 !== sha256) {
    throw new Error(`D1 read-back verification failed for ${date}`);
  }
  console.log(`[history:fill] VERIFIED ${date}: ${bars.length} bars -> R2 + D1`);
}

const options = parseArgs();
const existing = localHistoricalDates();
if (!existing.length) fail("no mirrored prices/daily history found; run npm run local:sync first");
const earliest = existing[0];
const missingNeeded = Math.max(0, options.requiredSessions - existing.length);
const targetWrites = Math.min(missingNeeded, options.limit);

console.log("FutureView one-time historical gap fill");
console.log(`[history:fill] existing local sessions: ${existing.length} (${earliest} -> ${existing.at(-1)})`);
console.log(`[history:fill] required sessions: ${options.requiredSessions}; missing: ${missingNeeded}; this run limit: ${targetWrites}`);

if (missingNeeded === 0) {
  console.log("[history:fill] READY: no historical gap remains");
  process.exit(0);
}
if (options.dryRun) process.exit(0);

ensureD1Table();
let cursor = shiftDate(earliest, -1);
let written = 0;
let scanned = 0;
while (written < targetWrites && scanned < missingNeeded + 120) {
  if (isWeekend(cursor)) {
    cursor = shiftDate(cursor, -1);
    continue;
  }
  const date = cursor;
  cursor = shiftDate(cursor, -1);
  scanned += 1;

  const r2Key = `prices/daily-json/date=${date}/bars.json`;
  const existingRemote = await remoteR2Json(r2Key);
  if (existingRemote?.date === date && Array.isArray(existingRemote.bars) && existingRemote.bars.length) {
    const body = Buffer.from(`${JSON.stringify(existingRemote)}\n`);
    const sha256 = createHash("sha256").update(body).digest("hex");
    const now = new Date().toISOString();
    upsertD1({ tradingDate: date, r2Key, rowCount: existingRemote.bars.length, sha256, now });
    console.log(`[history:fill] reused existing R2 ${date}: ${existingRemote.bars.length} bars; D1 index repaired`);
    written += 1;
    continue;
  }

  const bars = await fetchGroupedDaily(date);
  if (!bars.length) {
    console.log(`[history:fill] skipped ${date}: no market session`);
    await sleep(REQUEST_SPACING_MS);
    continue;
  }
  await writeAndVerify(date, bars);
  written += 1;
  if (written < targetWrites) await sleep(REQUEST_SPACING_MS);
}

if (written < targetWrites) fail(`filled only ${written}/${targetWrites} sessions`);
console.log(`\n[history:fill] READY: ${written} historical sessions filled and verified in R2 + D1`);
console.log("[history:fill] run npm run local:sync, then npm run local:data:report to refresh the local mirror");

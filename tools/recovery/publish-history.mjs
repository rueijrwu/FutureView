import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";

const WRANGLER_VERSION = "4.125.0";
const DATABASE = "futureview";
const BUCKET = "futureview-data";
const JSON_ROOT = ".local-data/objects/prices/daily-json";
const PARQUET_ROOT = ".local-data/objects/prices/daily";

function fail(message) {
  console.error(`\n[history:publish] ERROR: ${message}`);
  process.exit(1);
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

function parseArgs() {
  const args = new Set(process.argv.slice(2));
  return { smoke: args.has("--smoke") };
}

const devVars = loadDevVars();
const accountId = process.env.R2_ACCOUNT_ID || devVars.R2_ACCOUNT_ID;
const token = process.env.CLOUDFLARE_API_TOKEN || devVars.CLOUDFLARE_API_TOKEN;
if (!accountId) fail("R2_ACCOUNT_ID is required");
if (!token) fail("CLOUDFLARE_API_TOKEN is required");

function wrangler(args, { json = false } = {}) {
  const result = spawnSync("npx", ["--yes", `wrangler@${WRANGLER_VERSION}`, ...args], {
    encoding: "utf8",
    env: { ...process.env, CLOUDFLARE_API_TOKEN: token, CLOUDFLARE_ACCOUNT_ID: accountId },
    maxBuffer: 128 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error((result.stderr || result.stdout || `wrangler exited ${result.status}`).trim());
  if (!json) return result.stdout;
  return JSON.parse(result.stdout);
}

function quoteSql(value) {
  if (value == null) return "NULL";
  return `'${String(value).replaceAll("'", "''")}'`;
}

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function recoveredSessions() {
  if (!existsSync(JSON_ROOT)) return [];
  return readdirSync(JSON_ROOT, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && /^date=\d{4}-\d{2}-\d{2}$/.test(entry.name))
    .map((entry) => entry.name.slice(5))
    .filter((date) => {
      const parquet = path.join(PARQUET_ROOT, `date=${date}`, "bars.parquet");
      return !existsSync(parquet);
    })
    .sort();
}

async function remoteObject(key) {
  const url = `https://api.cloudflare.com/client/v4/accounts/${encodeURIComponent(accountId)}/r2/buckets/${encodeURIComponent(BUCKET)}/objects/${encodeURIComponent(key)}`;
  const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`R2 GET ${key} failed HTTP ${response.status}: ${(await response.text()).slice(0, 300)}`);
  return Buffer.from(await response.arrayBuffer());
}

function d1Rows(sql) {
  const payload = wrangler(["d1", "execute", DATABASE, "--remote", "--json", "--command", sql], { json: true });
  const statement = Array.isArray(payload) ? payload[0] : payload;
  return Array.isArray(statement?.results) ? statement.results : [];
}

function ensureD1Table() {
  wrangler(["d1", "execute", DATABASE, "--remote", "--file", "migrations/0003_market_data_sessions.sql"]);
}

function upsertD1(record) {
  const sql = `INSERT INTO market_data_sessions (trading_date,r2_key,row_count,sha256,source,producer,storage_format,created_at,updated_at) VALUES (${quoteSql(record.date)},${quoteSql(record.r2Key)},${record.count},${quoteSql(record.sha)},${quoteSql(record.source)},${quoteSql(record.producer)},'json',${quoteSql(record.now)},${quoteSql(record.now)}) ON CONFLICT(trading_date) DO UPDATE SET r2_key=excluded.r2_key,row_count=excluded.row_count,sha256=excluded.sha256,source=excluded.source,producer=excluded.producer,storage_format=excluded.storage_format,updated_at=excluded.updated_at;`;
  wrangler(["d1", "execute", DATABASE, "--remote", "--command", sql]);
}

async function publishOne(date) {
  const file = path.join(JSON_ROOT, `date=${date}`, "bars.json");
  const body = readFileSync(file);
  const payload = JSON.parse(body.toString("utf8"));
  const count = Array.isArray(payload.bars) ? payload.bars.length : Number(payload.count ?? 0);
  if (!count) throw new Error(`${file} contains no bars`);
  const r2Key = `prices/daily-json/date=${date}/bars.json`;
  const localSha = sha256(body);

  const remoteBefore = await remoteObject(r2Key);
  if (remoteBefore) {
    const remoteSha = sha256(remoteBefore);
    if (remoteSha !== localSha) throw new Error(`remote R2 object exists with different checksum for ${date}`);
    console.log(`[history:publish] R2 already matches ${date}`);
  } else {
    const tmp = `/tmp/futureview-history-${date}.json`;
    writeFileSync(tmp, body);
    wrangler(["r2", "object", "put", `${BUCKET}/${r2Key}`, "--file", tmp, "--content-type", "application/json", "--remote"]);
    const remoteAfter = await remoteObject(r2Key);
    if (!remoteAfter || sha256(remoteAfter) !== localSha) throw new Error(`R2 read-back checksum failed for ${date}`);
    console.log(`[history:publish] R2 VERIFIED ${date}: ${count} bars`);
  }

  const now = new Date().toISOString();
  upsertD1({
    date,
    r2Key,
    count,
    sha: localSha,
    source: payload.source ?? "massive",
    producer: payload.producer ?? "codespaces-history-recovery",
    now,
  });
  const rows = d1Rows(`SELECT trading_date,r2_key,row_count,sha256 FROM market_data_sessions WHERE trading_date=${quoteSql(date)} LIMIT 1`);
  const row = rows[0];
  if (!row || row.trading_date !== date || row.r2_key !== r2Key || Number(row.row_count) !== count || row.sha256 !== localSha) {
    throw new Error(`D1 read-back verification failed for ${date}`);
  }
  console.log(`[history:publish] D1 VERIFIED ${date}: ${r2Key}`);
}

const options = parseArgs();
let sessions = recoveredSessions();
if (!sessions.length) fail("no recovery-only local JSON sessions found; run npm run local:history first");
if (options.smoke) sessions = sessions.slice(0, 1);

console.log(`FutureView historical Cloudflare publish (${options.smoke ? "smoke" : "full"})`);
console.log(`[history:publish] recovery sessions selected: ${sessions.length} (${sessions[0]} -> ${sessions.at(-1)})`);
console.log("[history:publish] applying D1 market_data_sessions migration");
ensureD1Table();

for (const date of sessions) await publishOne(date);

console.log("\n[history:publish] READY");
console.log(`[history:publish] ${sessions.length} recovery sessions verified in R2 + D1`);
if (options.smoke) console.log("[history:publish] smoke passed; run npm run cloudflare:history:publish for the full recovery set");

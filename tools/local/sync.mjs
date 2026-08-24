import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import process from "node:process";

const WRANGLER_VERSION = "4.125.0";
const LOCAL_CONFIG = ".wrangler.local.json";
const REMOTE_CONFIG = "wrangler.jsonc";
const LOCAL_STATE_DIR = ".local-state";
const SYNC_DIR = ".local-sync";
const MANIFEST_FILE = `${SYNC_DIR}/manifest.json`;
const R2_BUCKET = "futureview-data";
const D1_DATABASE = "futureview";
const RANKING_HISTORY_LIMIT = 20;
const FULL_SYNC = process.argv.includes("--full");

function fail(message) {
  console.error(`\n[local:sync] ERROR: ${message}`);
  process.exit(1);
}

function wranglerEnv() {
  if (!process.env.CLOUDFLARE_API_TOKEN) fail("CLOUDFLARE_API_TOKEN is not available in this environment");
  if (!process.env.R2_ACCOUNT_ID) fail("R2_ACCOUNT_ID is not available in this environment");
  return {
    ...process.env,
    CLOUDFLARE_ACCOUNT_ID: process.env.R2_ACCOUNT_ID,
  };
}

function runCapture(command, args, { allowFailure = false } = {}) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    env: wranglerEnv(),
  });
  if (result.error) fail(result.error.message);
  if (result.status !== 0 && !allowFailure) {
    const detail = (result.stderr || result.stdout || "").trim();
    fail(`${command} exited with code ${result.status}${detail ? `: ${detail}` : ""}`);
  }
  return result;
}

function wranglerArgs(...args) {
  return ["--yes", `wrangler@${WRANGLER_VERSION}`, ...args];
}

function localPersistenceArgs() {
  return ["--persist-to", LOCAL_STATE_DIR];
}

function tempPathForKey(key) {
  return `${SYNC_DIR}/${key.replace(/[^A-Za-z0-9._-]/g, "__")}`;
}

function hashBuffer(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function hashJson(value) {
  return hashBuffer(Buffer.from(JSON.stringify(value)));
}

function loadManifest() {
  if (FULL_SYNC || !existsSync(MANIFEST_FILE)) {
    return { version: 1, r2: {}, d1_runs: {} };
  }
  try {
    const manifest = JSON.parse(readFileSync(MANIFEST_FILE, "utf8"));
    return {
      version: 1,
      r2: manifest.r2 ?? {},
      d1_runs: manifest.d1_runs ?? {},
    };
  } catch (error) {
    console.warn(`[local:sync] Ignoring unreadable manifest: ${error.message}`);
    return { version: 1, r2: {}, d1_runs: {} };
  }
}

function saveManifest(manifest) {
  writeFileSync(MANIFEST_FILE, `${JSON.stringify({
    ...manifest,
    updated_at: new Date().toISOString(),
  }, null, 2)}\n`);
}

const manifest = loadManifest();
const copiedKeys = new Set();
const skippedKeys = new Set();

function fetchRemoteR2(key, { required = false } = {}) {
  const file = tempPathForKey(key);
  const result = runCapture(
    "npx",
    wranglerArgs(
      "r2", "object", "get", `${R2_BUCKET}/${key}`,
      "--file", file,
      "--remote",
      "--config", REMOTE_CONFIG,
    ),
    { allowFailure: !required },
  );
  if (result.status !== 0) return null;
  const body = readFileSync(file);
  return { file, body, hash: hashBuffer(body) };
}

function putLocalR2(key, file) {
  const result = runCapture(
    "npx",
    wranglerArgs(
      "r2", "object", "put", `${R2_BUCKET}/${key}`,
      "--file", file,
      "--content-type", "application/json",
      "--local",
      ...localPersistenceArgs(),
      "--config", LOCAL_CONFIG,
    ),
  );
  if (result.status !== 0) fail(`Unable to write local R2 object: ${key}`);
}

function copyFetchedR2(key, fetched, { force = false } = {}) {
  if (!fetched) return null;
  const unchanged = !FULL_SYNC && !force && manifest.r2[key]?.hash === fetched.hash;
  if (unchanged) {
    skippedKeys.add(key);
    return fetched;
  }
  putLocalR2(key, fetched.file);
  manifest.r2[key] = { hash: fetched.hash };
  copiedKeys.add(key);
  console.log(`[local:sync] R2 updated ${key}`);
  return fetched;
}

function syncR2Object(key, { required = false, force = false } = {}) {
  if (!key) return null;
  const fetched = fetchRemoteR2(key, { required });
  if (!fetched) {
    console.log(`[local:sync] Optional R2 object not present: ${key}`);
    return null;
  }
  return copyFetchedR2(key, fetched, { force });
}

function syncJsonPointer(key, { required = false, refs = () => [] } = {}) {
  const fetched = fetchRemoteR2(key, { required });
  if (!fetched) {
    console.log(`[local:sync] Optional R2 pointer not present: ${key}`);
    return null;
  }

  const previousHash = manifest.r2[key]?.hash ?? null;
  const pointerChanged = FULL_SYNC || previousHash !== fetched.hash;
  copyFetchedR2(key, fetched, { force: pointerChanged });

  const payload = JSON.parse(fetched.body.toString("utf8"));
  const referencedKeys = refs(payload).filter(Boolean);
  if (!pointerChanged && referencedKeys.every((ref) => manifest.r2[ref]?.hash)) {
    for (const ref of referencedKeys) skippedKeys.add(ref);
    if (referencedKeys.length) {
      console.log(`[local:sync] ${key} unchanged — skipped ${referencedKeys.length} referenced object(s)`);
    }
    return payload;
  }

  for (const ref of referencedKeys) {
    syncR2Object(ref, { required: true, force: pointerChanged });
  }
  return payload;
}

function parseWranglerJson(stdout) {
  const text = String(stdout ?? "").trim();
  if (!text) return [];
  try {
    return JSON.parse(text);
  } catch {
    const start = text.indexOf("[");
    const end = text.lastIndexOf("]");
    if (start >= 0 && end > start) return JSON.parse(text.slice(start, end + 1));
    fail(`Unable to parse Wrangler JSON output: ${text.slice(0, 300)}`);
  }
}

function d1Rows(sql, location) {
  const localArgs = location === "--local" ? localPersistenceArgs() : [];
  const result = runCapture(
    "npx",
    wranglerArgs(
      "d1", "execute", D1_DATABASE,
      location,
      ...localArgs,
      "--command", sql,
      "--json",
      "--config", location === "--remote" ? REMOTE_CONFIG : LOCAL_CONFIG,
    ),
  );
  const payload = parseWranglerJson(result.stdout);
  const executions = Array.isArray(payload) ? payload : [payload];
  return executions.flatMap((entry) => Array.isArray(entry?.results) ? entry.results : []);
}

function remoteD1Rows(sql) {
  return d1Rows(sql, "--remote");
}

function sqlValue(value) {
  if (value === null || value === undefined) return "NULL";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "NULL";
  if (typeof value === "boolean") return value ? "1" : "0";
  return `'${String(value).replaceAll("'", "''")}'`;
}

function insertStatement(table, row) {
  const columns = Object.keys(row);
  return `INSERT OR REPLACE INTO ${table} (${columns.join(", ")}) VALUES (${columns.map((column) => sqlValue(row[column])).join(", ")});`;
}

function dateListSql(dates) {
  return dates.map(sqlValue).join(", ");
}

function applyLocalD1(sql) {
  const sqlFile = `${SYNC_DIR}/d1-incremental.sql`;
  writeFileSync(sqlFile, sql);
  const result = runCapture(
    "npx",
    wranglerArgs(
      "d1", "execute", D1_DATABASE,
      "--local",
      ...localPersistenceArgs(),
      "--file", sqlFile,
      "--yes",
      "--config", LOCAL_CONFIG,
    ),
  );
  if (result.status !== 0) fail("Unable to update local D1 snapshot");
}

function syncD1Snapshot() {
  const recentCte = `WITH recent AS (SELECT trading_date FROM ranking_runs ORDER BY trading_date DESC LIMIT ${RANKING_HISTORY_LIMIT})`;
  const runs = remoteD1Rows(`${recentCte} SELECT rr.* FROM ranking_runs rr JOIN recent r ON r.trading_date = rr.trading_date ORDER BY rr.trading_date ASC`);
  if (!runs.length) {
    console.log("[local:sync] No production ranking_runs found; skipping D1 ranking snapshot");
    return { runs: 0, entries: 0, universes: 0, changed_dates: 0 };
  }

  const changedRuns = FULL_SYNC
    ? runs
    : runs.filter((row) => manifest.d1_runs[row.trading_date] !== hashJson(row));

  if (!changedRuns.length) {
    console.log(`[local:sync] D1 ranking snapshot unchanged — skipped ${runs.length} recent run(s)`);
    return { runs: 0, entries: 0, universes: 0, changed_dates: 0 };
  }

  const dates = changedRuns.map((row) => row.trading_date);
  const datesSql = dateListSql(dates);
  const entries = remoteD1Rows(`SELECT * FROM ranking_entries WHERE trading_date IN (${datesSql}) AND rank <= 50 ORDER BY trading_date ASC, rank ASC`);
  const universes = remoteD1Rows(`SELECT DISTINCT us.* FROM universe_snapshots us JOIN ranking_runs rr ON rr.universe_as_of = us.as_of WHERE rr.trading_date IN (${datesSql}) ORDER BY us.as_of ASC`);

  const sql = [
    "PRAGMA foreign_keys = ON;",
    "BEGIN TRANSACTION;",
    ...(FULL_SYNC ? [
      "DELETE FROM ranking_entries;",
      "DELETE FROM ranking_runs;",
      "DELETE FROM universe_snapshots;",
    ] : []),
    ...universes.map((row) => insertStatement("universe_snapshots", row)),
    ...changedRuns.map((row) => insertStatement("ranking_runs", row)),
    ...entries.map((row) => insertStatement("ranking_entries", row)),
    "COMMIT;",
    "",
  ].join("\n");

  applyLocalD1(sql);
  for (const row of changedRuns) manifest.d1_runs[row.trading_date] = hashJson(row);
  console.log(`[local:sync] D1 updated ${changedRuns.length} ranking date(s)`);
  return {
    runs: changedRuns.length,
    entries: entries.length,
    universes: universes.length,
    changed_dates: changedRuns.length,
  };
}

console.log(`FutureView production snapshot -> local development (${FULL_SYNC ? "full" : "incremental"})`);
console.log("Remote access is read-only by design; all writes target persistent local Wrangler state.");
console.log(`[local:sync] Local persistence: ${LOCAL_STATE_DIR}`);

if (FULL_SYNC) {
  rmSync(SYNC_DIR, { recursive: true, force: true });
  rmSync(LOCAL_STATE_DIR, { recursive: true, force: true });
}
mkdirSync(SYNC_DIR, { recursive: true });
mkdirSync(LOCAL_STATE_DIR, { recursive: true });

const universe = syncJsonPointer("metadata/latest-common-stock-universe.json", {
  required: true,
  refs: (payload) => [payload.data_key],
});

const featureState = syncJsonPointer("metadata/latest-feature-state.json", {
  required: true,
  refs: (payload) => [
    ...(payload.keys ?? []),
    payload.prefix ? `${payload.prefix}/metadata.json` : null,
  ],
});

syncJsonPointer("metadata/latest-cloudflare-ingest.json", {
  refs: (payload) => [payload.data_key],
});
syncR2Object("dashboard/latest.json");
syncJsonPointer("metadata/latest-ranking.json", {
  refs: (payload) => [payload.ranking_key, payload.top50_key, payload.ranking_state_metadata_key],
});
syncJsonPointer("metadata/latest-top50.json", {
  refs: (payload) => [payload.data_key],
});
syncJsonPointer("metadata/latest-ranking-state.json", {
  refs: (payload) => [
    ...(payload.keys ?? []),
    payload.prefix ? `${payload.prefix}/metadata.json` : null,
  ],
});
syncR2Object("metadata/latest-js-replay.json");
syncJsonPointer("metadata/latest-backtest.json", {
  refs: (payload) => [payload.result_key],
});

const d1 = syncD1Snapshot();
saveManifest(manifest);

console.log("\n[local:sync] READY");
console.log(`[local:sync] Universe: ${universe?.as_of ?? "unknown"}`);
console.log(`[local:sync] Feature state: ${featureState?.as_of ?? "unknown"}`);
console.log(`[local:sync] R2 updated: ${copiedKeys.size}; unchanged/skipped: ${skippedKeys.size}`);
console.log(`[local:sync] D1 changed dates: ${d1.changed_dates}; rows: ${d1.runs} runs / ${d1.entries} top50 entries / ${d1.universes} universes`);
console.log(`[local:sync] Manifest: ${MANIFEST_FILE}`);
console.log(`[local:sync] Persistent state: ${LOCAL_STATE_DIR}`);
console.log("Start/restart development with: npm run local:dev");

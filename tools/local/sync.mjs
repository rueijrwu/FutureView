import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import process from "node:process";

const WRANGLER_VERSION = "4.125.0";
const LOCAL_CONFIG = ".wrangler.local.json";
const REMOTE_CONFIG = "wrangler.jsonc";
const TEMP_DIR = ".local-sync";
const R2_BUCKET = "futureview-data";
const D1_DATABASE = "futureview";
const RANKING_HISTORY_LIMIT = 20;

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

function runInherit(command, args) {
  const result = spawnSync(command, args, {
    stdio: "inherit",
    env: wranglerEnv(),
  });
  if (result.error) fail(result.error.message);
  if (result.status !== 0) fail(`${command} exited with code ${result.status}`);
}

function wranglerArgs(...args) {
  return ["--yes", `wrangler@${WRANGLER_VERSION}`, ...args];
}

function tempPathForKey(key) {
  return `${TEMP_DIR}/${key.replace(/[^A-Za-z0-9._-]/g, "__")}`;
}

const copiedKeys = new Set();

function copyR2Object(key, { required = false } = {}) {
  if (!key || copiedKeys.has(key)) return null;
  const file = tempPathForKey(key);
  const getResult = runCapture(
    "npx",
    wranglerArgs(
      "r2", "object", "get", `${R2_BUCKET}/${key}`,
      "--file", file,
      "--remote",
      "--config", REMOTE_CONFIG,
    ),
    { allowFailure: !required },
  );

  if (getResult.status !== 0) {
    console.log(`[local:sync] Optional R2 object not present: ${key}`);
    return null;
  }

  runInherit(
    "npx",
    wranglerArgs(
      "r2", "object", "put", `${R2_BUCKET}/${key}`,
      "--file", file,
      "--content-type", "application/json",
      "--local",
      "--config", LOCAL_CONFIG,
    ),
  );
  copiedKeys.add(key);
  console.log(`[local:sync] R2 ${key}`);
  return file;
}

function copyJsonPointer(key, { required = false, refs = () => [] } = {}) {
  const file = copyR2Object(key, { required });
  if (!file) return null;
  const payload = JSON.parse(readFileSync(file, "utf8"));
  for (const ref of refs(payload).filter(Boolean)) copyR2Object(ref, { required: true });
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

function remoteD1Rows(sql) {
  const result = runCapture(
    "npx",
    wranglerArgs(
      "d1", "execute", D1_DATABASE,
      "--remote",
      "--command", sql,
      "--json",
      "--config", REMOTE_CONFIG,
    ),
  );
  const payload = parseWranglerJson(result.stdout);
  const executions = Array.isArray(payload) ? payload : [payload];
  return executions.flatMap((entry) => Array.isArray(entry?.results) ? entry.results : []);
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

function syncD1Snapshot() {
  const recentCte = `WITH recent AS (SELECT trading_date FROM ranking_runs ORDER BY trading_date DESC LIMIT ${RANKING_HISTORY_LIMIT})`;
  const runs = remoteD1Rows(`${recentCte} SELECT rr.* FROM ranking_runs rr JOIN recent r ON r.trading_date = rr.trading_date ORDER BY rr.trading_date ASC`);
  if (!runs.length) {
    console.log("[local:sync] No production ranking_runs found; skipping D1 ranking snapshot");
    return { runs: 0, entries: 0, universes: 0 };
  }

  const entries = remoteD1Rows(`${recentCte} SELECT re.* FROM ranking_entries re JOIN recent r ON r.trading_date = re.trading_date WHERE re.rank <= 50 ORDER BY re.trading_date ASC, re.rank ASC`);
  const universes = remoteD1Rows(`${recentCte} SELECT DISTINCT us.* FROM universe_snapshots us JOIN ranking_runs rr ON rr.universe_as_of = us.as_of JOIN recent r ON r.trading_date = rr.trading_date ORDER BY us.as_of ASC`);

  const sql = [
    "PRAGMA foreign_keys = ON;",
    "BEGIN TRANSACTION;",
    "DELETE FROM ranking_entries;",
    "DELETE FROM ranking_runs;",
    "DELETE FROM universe_snapshots;",
    ...universes.map((row) => insertStatement("universe_snapshots", row)),
    ...runs.map((row) => insertStatement("ranking_runs", row)),
    ...entries.map((row) => insertStatement("ranking_entries", row)),
    "COMMIT;",
    "",
  ].join("\n");

  const sqlFile = `${TEMP_DIR}/d1-snapshot.sql`;
  writeFileSync(sqlFile, sql);
  runInherit(
    "npx",
    wranglerArgs(
      "d1", "execute", D1_DATABASE,
      "--local",
      "--file", sqlFile,
      "--yes",
      "--config", LOCAL_CONFIG,
    ),
  );

  return { runs: runs.length, entries: entries.length, universes: universes.length };
}

console.log("FutureView production snapshot -> local development");
console.log("Remote access is read-only by design; all writes target local Wrangler state.");

rmSync(TEMP_DIR, { recursive: true, force: true });
mkdirSync(TEMP_DIR, { recursive: true });

const universe = copyJsonPointer("metadata/latest-common-stock-universe.json", {
  required: true,
  refs: (payload) => [payload.data_key],
});

const featureState = copyJsonPointer("metadata/latest-feature-state.json", {
  required: true,
  refs: (payload) => [
    ...(payload.keys ?? []),
    payload.prefix ? `${payload.prefix}/metadata.json` : null,
  ],
});

copyJsonPointer("metadata/latest-cloudflare-ingest.json", {
  refs: (payload) => [payload.data_key],
});
copyR2Object("dashboard/latest.json");
copyJsonPointer("metadata/latest-ranking.json", {
  refs: (payload) => [payload.ranking_key, payload.top50_key, payload.ranking_state_metadata_key],
});
copyJsonPointer("metadata/latest-top50.json", {
  refs: (payload) => [payload.data_key],
});
copyJsonPointer("metadata/latest-ranking-state.json", {
  refs: (payload) => [
    ...(payload.keys ?? []),
    payload.prefix ? `${payload.prefix}/metadata.json` : null,
  ],
});
copyR2Object("metadata/latest-js-replay.json");
copyJsonPointer("metadata/latest-backtest.json", {
  refs: (payload) => [payload.result_key],
});

const d1 = syncD1Snapshot();

console.log("\n[local:sync] READY");
console.log(`[local:sync] Universe: ${universe?.as_of ?? "unknown"}`);
console.log(`[local:sync] Feature state: ${featureState?.as_of ?? "unknown"}`);
console.log(`[local:sync] R2 objects copied: ${copiedKeys.size}`);
console.log(`[local:sync] D1 ranking runs: ${d1.runs}; top50 entries: ${d1.entries}; universe snapshots: ${d1.universes}`);
console.log("Start/restart development with: npm run local:dev");

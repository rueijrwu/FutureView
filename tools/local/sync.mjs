import { createHash } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

import { createFilesystemJsonStore, objectPath } from "./fs-store.mjs";

const WRANGLER_VERSION = "4.125.0";
const REMOTE_CONFIG = "wrangler.jsonc";
const LOCAL_DATA_ROOT = ".local-data";
const D1_DIR = `${LOCAL_DATA_ROOT}/d1`;
const D1_SCHEMA_FILE = `${D1_DIR}/schema.json`;
const D1_TABLE_DIR = `${D1_DIR}/tables`;
const MIGRATIONS_DIR = "migrations";
const SYNC_DIR = ".local-sync";
const MANIFEST_FILE = `${SYNC_DIR}/manifest.json`;
const R2_BUCKET = "futureview-data";
const D1_DATABASE = "futureview";
const R2_PAGE_SIZE = 1000;
const R2_CONCURRENCY = 2;
const R2_MAX_RETRIES = 8;
const D1_PAGE_SIZE = 5000;
const FULL_SYNC = process.argv.includes("--full");
const store = createFilesystemJsonStore();

function fail(message) {
  console.error(`\n[local:sync] ERROR: ${message}`);
  process.exit(1);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function retryDelayMs(response, attempt) {
  const retryAfter = response.headers.get("retry-after");
  if (retryAfter) {
    const seconds = Number(retryAfter);
    if (Number.isFinite(seconds) && seconds >= 0) return Math.max(1000, seconds * 1000);
    const at = Date.parse(retryAfter);
    if (Number.isFinite(at)) return Math.max(1000, at - Date.now());
  }
  return Math.min(60_000, 5_000 * (2 ** attempt));
}

function requireCloudflareEnv() {
  if (!process.env.CLOUDFLARE_API_TOKEN) {
    fail("CLOUDFLARE_API_TOKEN is not available in this environment");
  }
  if (!process.env.R2_ACCOUNT_ID) {
    fail("R2_ACCOUNT_ID is not available in this environment");
  }
}

function cloudflareEnv() {
  requireCloudflareEnv();
  return {
    ...process.env,
    CLOUDFLARE_ACCOUNT_ID: process.env.R2_ACCOUNT_ID,
  };
}

function cloudflareHeaders() {
  requireCloudflareEnv();
  return {
    Authorization: `Bearer ${process.env.CLOUDFLARE_API_TOKEN}`,
  };
}

function hashBuffer(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function loadManifest() {
  if (FULL_SYNC || !existsSync(MANIFEST_FILE)) {
    return { version: 6, r2: {}, d1: {} };
  }
  try {
    const raw = JSON.parse(readFileSync(MANIFEST_FILE, "utf8"));
    return {
      version: 6,
      r2: raw.r2 ?? raw.objects ?? {},
      d1: raw.d1 ?? {},
    };
  } catch (error) {
    console.warn(`[local:sync] Ignoring unreadable manifest: ${error.message}`);
    return { version: 6, r2: {}, d1: {} };
  }
}

function saveManifest(manifest) {
  mkdirSync(SYNC_DIR, { recursive: true });
  writeFileSync(MANIFEST_FILE, `${JSON.stringify({
    ...manifest,
    updated_at: new Date().toISOString(),
  }, null, 2)}\n`);
}

async function cloudflareJson(url) {
  const response = await fetch(url, { headers: cloudflareHeaders() });
  if (!response.ok) {
    throw new Error(`Cloudflare HTTP ${response.status}: ${(await response.text()).slice(0, 500)}`);
  }
  const payload = await response.json();
  if (!payload.success) {
    throw new Error(`Cloudflare API error: ${JSON.stringify(payload.errors ?? payload)}`);
  }
  return payload;
}

async function listAllR2Objects() {
  const accountId = encodeURIComponent(process.env.R2_ACCOUNT_ID);
  const bucket = encodeURIComponent(R2_BUCKET);
  const base = `https://api.cloudflare.com/client/v4/accounts/${accountId}/r2/buckets/${bucket}/objects`;
  const objects = [];
  let cursor = null;
  let page = 0;

  do {
    const url = new URL(base);
    url.searchParams.set("per_page", String(R2_PAGE_SIZE));
    if (cursor) url.searchParams.set("cursor", cursor);
    const payload = await cloudflareJson(url);
    const rows = Array.isArray(payload.result) ? payload.result : [];
    objects.push(...rows.filter((row) => row?.key));
    page += 1;
    console.log(`[local:sync] R2 inventory page ${page}: ${rows.length} objects (${objects.length} total)`);
    cursor = payload.result_info?.is_truncated ? payload.result_info?.cursor ?? null : null;
  } while (cursor);

  return objects;
}

function localObjectMatches(meta, manifestEntry) {
  if (!manifestEntry || !existsSync(objectPath(meta.key))) return false;
  const size = statSync(objectPath(meta.key)).size;
  if (Number.isFinite(Number(meta.size)) && size !== Number(meta.size)) return false;
  return manifestEntry.etag === (meta.etag ?? null)
    && Number(manifestEntry.size ?? size) === size;
}

async function downloadR2Object(meta) {
  const accountId = encodeURIComponent(process.env.R2_ACCOUNT_ID);
  const bucket = encodeURIComponent(R2_BUCKET);
  const key = encodeURIComponent(String(meta.key));
  const url = `https://api.cloudflare.com/client/v4/accounts/${accountId}/r2/buckets/${bucket}/objects/${key}`;

  for (let attempt = 0; attempt <= R2_MAX_RETRIES; attempt += 1) {
    const response = await fetch(url, { headers: cloudflareHeaders() });
    if (response.ok) {
      const body = Buffer.from(await response.arrayBuffer());
      if (Number.isFinite(Number(meta.size)) && body.length !== Number(meta.size)) {
        throw new Error(`R2 size mismatch for ${meta.key}: expected ${meta.size}, got ${body.length}`);
      }
      const file = objectPath(meta.key);
      mkdirSync(path.dirname(file), { recursive: true });
      writeFileSync(file, body);
      return body.length;
    }

    const retryable = response.status === 429 || response.status >= 500;
    const detail = (await response.text()).slice(0, 300);
    if (!retryable || attempt >= R2_MAX_RETRIES) {
      throw new Error(`R2 GET ${meta.key} failed with HTTP ${response.status}: ${detail}`);
    }

    const delay = retryDelayMs(response, attempt);
    console.warn(`[local:sync] R2 GET ${response.status} for ${meta.key}; retry ${attempt + 1}/${R2_MAX_RETRIES} after ${(delay / 1000).toFixed(1)}s`);
    await sleep(delay);
  }

  throw new Error(`R2 GET ${meta.key} exhausted retries`);
}

async function mirrorR2(manifest) {
  const inventory = await listAllR2Objects();
  let updated = 0;
  let unchanged = 0;
  let bytesDownloaded = 0;
  let nextIndex = 0;

  async function worker() {
    while (true) {
      const index = nextIndex;
      nextIndex += 1;
      if (index >= inventory.length) return;
      const meta = inventory[index];
      if (localObjectMatches(meta, manifest.r2[meta.key])) {
        unchanged += 1;
        continue;
      }
      const bytes = await downloadR2Object(meta);
      manifest.r2[meta.key] = {
        etag: meta.etag ?? null,
        size: Number(meta.size ?? bytes),
        last_modified: meta.last_modified ?? null,
        content_type: meta.http_metadata?.contentType ?? null,
      };
      updated += 1;
      bytesDownloaded += bytes;
      if (updated % 10 === 0) {
        saveManifest(manifest);
        console.log(`[local:sync] mirrored ${updated} changed R2 objects so far`);
      }
    }
  }

  await Promise.all(Array.from({ length: R2_CONCURRENCY }, () => worker()));
  saveManifest(manifest);

  const remoteKeys = new Set(inventory.map((row) => String(row.key)));
  let staleManifestEntries = 0;
  for (const key of Object.keys(manifest.r2)) {
    if (!remoteKeys.has(key)) {
      delete manifest.r2[key];
      staleManifestEntries += 1;
    }
  }

  return {
    count: inventory.length,
    updated,
    unchanged,
    bytesDownloaded,
    staleManifestEntries,
  };
}

function quoteIdentifier(value) {
  return `"${String(value).replaceAll('"', '""')}"`;
}

function safeTableFileName(value) {
  return `${String(value).replace(/[^A-Za-z0-9._-]/g, "_")}.jsonl`;
}

function migrationSchema() {
  if (!existsSync(MIGRATIONS_DIR)) {
    throw new Error(`migration directory is missing: ${MIGRATIONS_DIR}`);
  }
  const files = readdirSync(MIGRATIONS_DIR)
    .filter((name) => name.endsWith(".sql"))
    .sort();
  if (!files.length) throw new Error("no SQL migrations found");

  const migrations = files.map((name) => ({
    name,
    sql: readFileSync(path.join(MIGRATIONS_DIR, name), "utf8"),
  }));
  const tables = [];
  const seen = new Set();
  const createTable = /CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:["`\[])?([A-Za-z_][A-Za-z0-9_]*)(?:["`\]])?/gi;

  for (const migration of migrations) {
    let match;
    while ((match = createTable.exec(migration.sql)) !== null) {
      const table = match[1];
      if (table.startsWith("sqlite_") || table.startsWith("_cf_")) continue;
      if (!seen.has(table)) {
        seen.add(table);
        tables.push(table);
      }
    }
  }
  if (!tables.length) throw new Error("no application tables discovered from migrations");
  return { migrations, tables };
}

function runD1Query(sql) {
  const args = [
    "--yes",
    `wrangler@${WRANGLER_VERSION}`,
    "d1",
    "execute",
    D1_DATABASE,
    "--remote",
    "--json",
    "--command",
    sql,
    "--config",
    REMOTE_CONFIG,
  ];
  const result = spawnSync("npx", args, {
    encoding: "utf8",
    env: cloudflareEnv(),
    maxBuffer: 64 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "").trim();
    throw new Error(`D1 read query failed with code ${result.status}${detail ? `: ${detail}` : ""}`);
  }

  let payload;
  try {
    payload = JSON.parse(result.stdout);
  } catch (error) {
    throw new Error(`D1 returned unreadable JSON: ${error.message}; output=${result.stdout.slice(0, 500)}`);
  }
  const statement = Array.isArray(payload) ? payload[0] : payload;
  if (statement?.success === false) {
    throw new Error(`D1 query failed: ${JSON.stringify(statement)}`);
  }
  return Array.isArray(statement?.results) ? statement.results : [];
}

function mirrorD1(manifest) {
  mkdirSync(D1_DIR, { recursive: true });
  mkdirSync(D1_TABLE_DIR, { recursive: true });

  const source = migrationSchema();
  const schemaArtifact = {
    source: "repo-migrations",
    migrations: source.migrations,
    tables: source.tables,
  };
  const schemaBody = Buffer.from(`${JSON.stringify(schemaArtifact, null, 2)}\n`);
  writeFileSync(D1_SCHEMA_FILE, schemaBody);

  let totalRows = 0;
  let totalBytes = schemaBody.length;
  const tableManifest = {};

  for (const table of source.tables) {
    const file = `${D1_TABLE_DIR}/${safeTableFileName(table)}`;
    writeFileSync(file, "");
    let offset = 0;
    let rowCount = 0;

    while (true) {
      const rows = runD1Query(
        `SELECT * FROM ${quoteIdentifier(table)} LIMIT ${D1_PAGE_SIZE} OFFSET ${offset}`,
      );
      if (!rows.length) break;
      const chunk = rows.map((row) => JSON.stringify(row)).join("\n") + "\n";
      writeFileSync(file, chunk, { flag: "a" });
      rowCount += rows.length;
      offset += rows.length;
      if (rows.length < D1_PAGE_SIZE) break;
    }

    const bytes = statSync(file).size;
    const hash = hashBuffer(readFileSync(file));
    tableManifest[table] = { rows: rowCount, bytes, hash };
    totalRows += rowCount;
    totalBytes += bytes;
    console.log(`[local:sync] D1 table ${table}: ${rowCount} rows`);
  }

  const snapshotHash = hashBuffer(Buffer.from(JSON.stringify({ schemaArtifact, tables: tableManifest })));
  const priorHash = manifest.d1.futureview?.hash ?? null;
  manifest.d1.futureview = {
    mode: "read-query-snapshot",
    schema_source: "repo-migrations",
    hash: snapshotHash,
    tables: tableManifest,
    rows: totalRows,
    bytes: totalBytes,
    mirrored_at: new Date().toISOString(),
  };

  return {
    updated: FULL_SYNC || priorHash !== snapshotHash,
    tables: source.tables.length,
    rows: totalRows,
    bytes: totalBytes,
    hash: snapshotHash,
  };
}

async function readJsonIfPresent(key) {
  try {
    return await store.getJson(key);
  } catch {
    return null;
  }
}

if (FULL_SYNC) {
  rmSync(SYNC_DIR, { recursive: true, force: true });
  rmSync(LOCAL_DATA_ROOT, { recursive: true, force: true });
}
mkdirSync(D1_DIR, { recursive: true });
requireCloudflareEnv();

console.log(`FutureView production -> complete local mirror (${FULL_SYNC ? "full rebuild" : "incremental"})`);
console.log("Remote access is read-only; all local research data is stored under .local-data/.");

const manifest = loadManifest();
const r2 = await mirrorR2(manifest);
saveManifest(manifest);
let d1;
try {
  d1 = mirrorD1(manifest);
  saveManifest(manifest);
} catch (error) {
  fail(`D1 read-only mirror failed: ${error.message}`);
}

const universe = await readJsonIfPresent("metadata/latest-common-stock-universe.json");
const featureState = await readJsonIfPresent("metadata/latest-feature-state.json");

console.log("\n[local:sync] READY");
console.log(`[local:sync] R2 objects: ${r2.count} total; ${r2.updated} updated; ${r2.unchanged} unchanged`);
console.log(`[local:sync] R2 downloaded: ${(r2.bytesDownloaded / 1024 / 1024).toFixed(1)} MiB`);
if (r2.staleManifestEntries) {
  console.log(`[local:sync] R2 removed from manifest: ${r2.staleManifestEntries}`);
}
console.log(`[local:sync] D1 snapshot: ${d1.updated ? "updated" : "unchanged"}; ${d1.tables} tables; ${d1.rows} rows; ${(d1.bytes / 1024 / 1024).toFixed(1)} MiB`);
console.log(`[local:sync] Universe: ${universe?.as_of ?? "unknown"}`);
console.log(`[local:sync] Feature state: ${featureState?.as_of ?? "unknown"}`);
console.log(`[local:sync] R2 mirror: ${LOCAL_DATA_ROOT}/objects/`);
console.log(`[local:sync] D1 schema: ${D1_SCHEMA_FILE}`);
console.log(`[local:sync] D1 tables: ${D1_TABLE_DIR}/`);
console.log("Run npm run local:backtest, then npm run local:dev");

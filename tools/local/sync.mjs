import { createHash } from "node:crypto";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
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
const D1_EXPORT_FILE = `${D1_DIR}/futureview.sql`;
const SYNC_DIR = ".local-sync";
const TMP_DIR = `${SYNC_DIR}/tmp`;
const MANIFEST_FILE = `${SYNC_DIR}/manifest.json`;
const R2_BUCKET = "futureview-data";
const D1_DATABASE = "futureview";
const R2_PAGE_SIZE = 1000;
const R2_CONCURRENCY = 8;
const FULL_SYNC = process.argv.includes("--full");
const store = createFilesystemJsonStore();

function fail(message) {
  console.error(`\n[local:sync] ERROR: ${message}`);
  process.exit(1);
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
    return { version: 4, r2: {}, d1: {} };
  }
  try {
    const raw = JSON.parse(readFileSync(MANIFEST_FILE, "utf8"));
    return {
      version: 4,
      r2: raw.r2 ?? raw.objects ?? {},
      d1: raw.d1 ?? {},
    };
  } catch (error) {
    console.warn(`[local:sync] Ignoring unreadable manifest: ${error.message}`);
    return { version: 4, r2: {}, d1: {} };
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
  const response = await fetch(url, { headers: cloudflareHeaders() });
  if (!response.ok) {
    throw new Error(`R2 GET ${meta.key} failed with HTTP ${response.status}: ${(await response.text()).slice(0, 300)}`);
  }
  const body = Buffer.from(await response.arrayBuffer());
  if (Number.isFinite(Number(meta.size)) && body.length !== Number(meta.size)) {
    throw new Error(`R2 size mismatch for ${meta.key}: expected ${meta.size}, got ${body.length}`);
  }
  const file = objectPath(meta.key);
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, body);
  return body.length;
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
      if (updated % 25 === 0) {
        saveManifest(manifest);
        console.log(`[local:sync] mirrored ${updated} changed R2 objects so far`);
      }
    }
  }

  await Promise.all(Array.from({ length: R2_CONCURRENCY }, () => worker()));

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

function exportD1(manifest) {
  mkdirSync(D1_DIR, { recursive: true });
  mkdirSync(TMP_DIR, { recursive: true });
  const tmpExport = `${TMP_DIR}/futureview.sql`;
  rmSync(tmpExport, { force: true });

  const args = [
    "--yes",
    `wrangler@${WRANGLER_VERSION}`,
    "d1",
    "export",
    D1_DATABASE,
    "--remote",
    "--output",
    tmpExport,
    "--skip-confirmation",
    "--config",
    REMOTE_CONFIG,
  ];
  const result = spawnSync("npx", args, {
    encoding: "utf8",
    env: cloudflareEnv(),
  });
  if (result.error) fail(result.error.message);
  if (result.status !== 0) {
    const detail = (result.stderr || result.stdout || "").trim();
    fail(`D1 export failed with code ${result.status}${detail ? `: ${detail}` : ""}`);
  }
  if (!existsSync(tmpExport)) fail("D1 export completed without creating an output file");

  const body = readFileSync(tmpExport);
  const hash = hashBuffer(body);
  const priorHash = manifest.d1.futureview?.hash ?? null;
  const same = !FULL_SYNC && priorHash === hash && existsSync(D1_EXPORT_FILE);
  if (!same) copyFileSync(tmpExport, D1_EXPORT_FILE);
  manifest.d1.futureview = {
    hash,
    bytes: body.length,
    exported_at: new Date().toISOString(),
  };
  return { updated: !same, bytes: body.length, hash };
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
mkdirSync(TMP_DIR, { recursive: true });
mkdirSync(D1_DIR, { recursive: true });
requireCloudflareEnv();

console.log(`FutureView production -> complete local mirror (${FULL_SYNC ? "full rebuild" : "incremental"})`);
console.log("Remote access is read-only; all local research data is stored under .local-data/.");

const manifest = loadManifest();
const r2 = await mirrorR2(manifest);
saveManifest(manifest);
const d1 = exportD1(manifest);
saveManifest(manifest);

const universe = await readJsonIfPresent("metadata/latest-common-stock-universe.json");
const featureState = await readJsonIfPresent("metadata/latest-feature-state.json");

console.log("\n[local:sync] READY");
console.log(`[local:sync] R2 objects: ${r2.count} total; ${r2.updated} updated; ${r2.unchanged} unchanged`);
console.log(`[local:sync] R2 downloaded: ${(r2.bytesDownloaded / 1024 / 1024).toFixed(1)} MiB`);
if (r2.staleManifestEntries) {
  console.log(`[local:sync] R2 removed from manifest: ${r2.staleManifestEntries}`);
}
console.log(`[local:sync] D1 export: ${d1.updated ? "updated" : "unchanged"}; ${(d1.bytes / 1024 / 1024).toFixed(1)} MiB`);
console.log(`[local:sync] Universe: ${universe?.as_of ?? "unknown"}`);
console.log(`[local:sync] Feature state: ${featureState?.as_of ?? "unknown"}`);
console.log(`[local:sync] R2 mirror: ${LOCAL_DATA_ROOT}/objects/`);
console.log(`[local:sync] D1 mirror: ${D1_EXPORT_FILE}`);
console.log("Run npm run local:backtest, then npm run local:dev");

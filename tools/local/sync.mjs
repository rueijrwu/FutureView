import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

import { createFilesystemJsonStore } from "./fs-store.mjs";

const WRANGLER_VERSION = "4.125.0";
const REMOTE_CONFIG = "wrangler.jsonc";
const SYNC_DIR = ".local-sync";
const TMP_DIR = `${SYNC_DIR}/tmp`;
const MANIFEST_FILE = `${SYNC_DIR}/manifest.json`;
const R2_BUCKET = "futureview-data";
const FULL_SYNC = process.argv.includes("--full");
const store = createFilesystemJsonStore();

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

function run(command, args, { allowFailure = false } = {}) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    env: wranglerEnv(),
  });
  if (result.error) fail(result.error.message);
  if (result.status !== 0 && !allowFailure) {
    const detail = (result.stderr || result.stdout || "").trim();
    fail(`${command} exited with ${result.status}${detail ? `: ${detail}` : ""}`);
  }
  return result;
}

function wranglerArgs(...args) {
  return ["--yes", `wrangler@${WRANGLER_VERSION}`, ...args];
}

function hashBuffer(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function tempPathForKey(key) {
  return `${TMP_DIR}/${String(key).replace(/[^A-Za-z0-9._-]/g, "__")}`;
}

function loadManifest() {
  if (FULL_SYNC || !existsSync(MANIFEST_FILE)) return { version: 2, objects: {} };
  try {
    const raw = JSON.parse(readFileSync(MANIFEST_FILE, "utf8"));
    return { version: 2, objects: raw.objects ?? raw.r2 ?? {} };
  } catch (error) {
    console.warn(`[local:sync] Ignoring unreadable manifest: ${error.message}`);
    return { version: 2, objects: {} };
  }
}

function saveManifest(manifest) {
  writeFileSync(MANIFEST_FILE, `${JSON.stringify({
    ...manifest,
    updated_at: new Date().toISOString(),
  }, null, 2)}\n`);
}

async function fetchRemoteJson(key, { required = false } = {}) {
  const file = tempPathForKey(key);
  const result = run(
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
  return {
    payload: JSON.parse(body.toString("utf8")),
    hash: hashBuffer(body),
  };
}

const manifest = loadManifest();
let updated = 0;
let unchanged = 0;

async function syncObject(key, { required = false } = {}) {
  if (!key) return null;
  const remote = await fetchRemoteJson(key, { required });
  if (!remote) {
    console.log(`[local:sync] Optional object not present: ${key}`);
    return null;
  }

  const same = !FULL_SYNC
    && manifest.objects[key]?.hash === remote.hash
    && await store.exists(key);
  if (same) {
    unchanged += 1;
    return remote.payload;
  }

  await store.putJson(key, remote.payload);
  manifest.objects[key] = { hash: remote.hash };
  updated += 1;
  console.log(`[local:sync] updated ${key}`);
  return remote.payload;
}

async function syncPointer(key, { required = false, refs = () => [] } = {}) {
  const payload = await syncObject(key, { required });
  if (!payload) return null;
  for (const ref of refs(payload).filter(Boolean)) {
    await syncObject(ref, { required: true });
  }
  return payload;
}

if (FULL_SYNC) {
  rmSync(SYNC_DIR, { recursive: true, force: true });
  rmSync(".local-data", { recursive: true, force: true });
}
mkdirSync(TMP_DIR, { recursive: true });

console.log(`FutureView production snapshot -> local filesystem (${FULL_SYNC ? "full" : "incremental"})`);
console.log("Remote access is read-only; local research data is stored under .local-data/.");

const universe = await syncPointer("metadata/latest-common-stock-universe.json", {
  required: true,
  refs: (payload) => [payload.data_key],
});

const featureState = await syncPointer("metadata/latest-feature-state.json", {
  required: true,
});

await syncPointer("metadata/latest-cloudflare-ingest.json", {
  refs: (payload) => [payload.data_key],
});
await syncObject("dashboard/latest.json");
await syncPointer("metadata/latest-ranking.json", {
  refs: (payload) => [payload.ranking_key, payload.top50_key],
});
await syncPointer("metadata/latest-top50.json", {
  refs: (payload) => [payload.data_key],
});
await syncPointer("metadata/latest-ranking-state.json");
await syncPointer("metadata/latest-js-replay.json", {
  refs: (payload) => [payload.data_key],
});
await syncPointer("metadata/latest-backtest.json", {
  refs: (payload) => [payload.result_key],
});

saveManifest(manifest);

console.log("\n[local:sync] READY");
console.log(`[local:sync] Universe: ${universe?.as_of ?? "unknown"}`);
console.log(`[local:sync] Feature state: ${featureState?.as_of ?? "unknown"}`);
console.log(`[local:sync] Objects updated: ${updated}; unchanged: ${unchanged}`);
console.log("[local:sync] Canonical local store: .local-data/");
console.log("Run npm run local:backtest, then npm run local:dev");

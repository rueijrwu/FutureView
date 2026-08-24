import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

export const LOCAL_DATA_ROOT = ".local-data";
const OBJECT_ROOT = path.join(LOCAL_DATA_ROOT, "objects");

function safeKey(key) {
  const normalized = path.posix.normalize(String(key)).replace(/^\/+/, "");
  if (!normalized || normalized.startsWith("..") || normalized.includes("/../")) {
    throw new Error(`invalid local object key: ${key}`);
  }
  return normalized;
}

export function objectPath(key) {
  return path.join(OBJECT_ROOT, ...safeKey(key).split("/"));
}

export function createFilesystemJsonStore() {
  return {
    async getJson(key) {
      const file = objectPath(key);
      if (!existsSync(file)) return null;
      return JSON.parse(readFileSync(file, "utf8"));
    },

    async putJson(key, value) {
      const file = objectPath(key);
      mkdirSync(path.dirname(file), { recursive: true });
      writeFileSync(file, `${JSON.stringify(value)}\n`);
      return { key };
    },

    async exists(key) {
      return existsSync(objectPath(key));
    },
  };
}

export function readSyncCacheJson(key) {
  const file = `.local-sync/${String(key).replace(/[^A-Za-z0-9._-]/g, "__")}`;
  if (!existsSync(file)) return null;
  return JSON.parse(readFileSync(file, "utf8"));
}

export async function materializeFromSyncCache(store, key) {
  const existing = await store.getJson(key);
  if (existing !== null) return existing;
  const cached = readSyncCacheJson(key);
  if (cached === null) return null;
  await store.putJson(key, cached);
  return cached;
}

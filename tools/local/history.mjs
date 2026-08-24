import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { asyncBufferFromFile, parquetReadObjects } from "hyparquet";

const ROOT = ".local-data";
const OBJECTS = path.join(ROOT, "objects");
const PARQUET_ROOT = path.join(OBJECTS, "prices", "daily");
const JSON_ROOT = path.join(OBJECTS, "prices", "daily-json");
const CLOSED_ROOT = path.join(ROOT, "history-closed");
const LATEST_FEATURE = path.join(OBJECTS, "metadata", "latest-feature-state.json");
const MASSIVE_BASE_URL = "https://api.massive.com";
const DEFAULT_REQUIRED_SESSIONS = 337;
const PACE_MS = 13_000;
const MAX_RETRIES = 4;

function fail(message) {
  console.error(`\n[local:history] ERROR: ${message}`);
  process.exit(1);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseArgs() {
  const out = { mode: "ensure", sessions: DEFAULT_REQUIRED_SESSIONS, end: null };
  for (const arg of process.argv.slice(2)) {
    if (arg.startsWith("--mode=")) out.mode = arg.slice(7);
    else if (arg.startsWith("--sessions=")) out.sessions = Number(arg.slice(11));
    else if (arg.startsWith("--end=")) out.end = arg.slice(6);
    else fail(`unknown argument: ${arg}`);
  }
  if (!new Set(["ensure", "materialize"]).has(out.mode)) fail("--mode must be ensure or materialize");
  if (!Number.isInteger(out.sessions) || out.sessions < 1) fail("--sessions must be a positive integer");
  if (out.end && !/^\d{4}-\d{2}-\d{2}$/.test(out.end)) fail("--end must be YYYY-MM-DD");
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

function shiftDate(iso, days) {
  const value = new Date(`${iso}T12:00:00Z`);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

function isWeekend(iso) {
  const day = new Date(`${iso}T12:00:00Z`).getUTCDay();
  return day === 0 || day === 6;
}

function latestCompletedSession() {
  if (!existsSync(LATEST_FEATURE)) fail("latest feature state missing; run npm run local:sync first or pass --end=YYYY-MM-DD");
  const payload = JSON.parse(readFileSync(LATEST_FEATURE, "utf8"));
  const value = payload.as_of ?? payload.date ?? null;
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(String(value))) fail("latest feature state has no valid as_of/date; pass --end=YYYY-MM-DD");
  return String(value);
}

function jsonPath(date) {
  return path.join(JSON_ROOT, `date=${date}`, "bars.json");
}

function parquetPath(date) {
  return path.join(PARQUET_ROOT, `date=${date}`, "bars.parquet");
}

function closedPath(date) {
  return path.join(CLOSED_ROOT, `${date}.json`);
}

function normalizeDocument(date, rows, { source, producer }) {
  const bars = [];
  for (const row of rows) {
    const symbol = row?.symbol ?? row?.T ?? row?.ticker ?? null;
    const rawValues = [
      row?.open ?? row?.o,
      row?.high ?? row?.h,
      row?.low ?? row?.l,
      row?.close ?? row?.c,
      row?.volume ?? row?.v,
    ];
    if (!symbol || rawValues.some((value) => value == null || value === "")) continue;
    const values = rawValues.map(Number);
    if (!values.every(Number.isFinite)) continue;
    bars.push({
      symbol: String(symbol),
      date,
      open: values[0],
      high: values[1],
      low: values[2],
      close: values[3],
      volume: values[4],
    });
  }
  return {
    date,
    adjusted: true,
    source,
    producer,
    count: bars.length,
    bars,
  };
}

function writeJsonDocument(date, payload) {
  const file = jsonPath(date);
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify(payload));
}

async function materializeParquet(date) {
  const source = parquetPath(date);
  const target = jsonPath(date);
  if (existsSync(target)) return true;
  if (!existsSync(source)) return false;

  const file = await asyncBufferFromFile(source);
  const rows = await parquetReadObjects({ file });
  const payload = normalizeDocument(date, rows, {
    source: "r2-parquet-mirror",
    producer: "codespaces-history-materializer",
  });
  if (!payload.count) throw new Error(`parquet file contained no valid bars: ${source}`);
  writeJsonDocument(date, payload);
  return true;
}

function dateDirectories(root, fileName) {
  if (!existsSync(root)) return [];
  return readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && /^date=\d{4}-\d{2}-\d{2}$/.test(entry.name))
    .map((entry) => ({ date: entry.name.slice(5), file: path.join(root, entry.name, fileName) }))
    .filter((entry) => existsSync(entry.file))
    .sort((a, b) => a.date.localeCompare(b.date));
}

function existingSessionDates(end = null) {
  const dates = [];
  for (const entry of dateDirectories(JSON_ROOT, "bars.json")) {
    if (end && entry.date > end) continue;
    try {
      const payload = JSON.parse(readFileSync(entry.file, "utf8"));
      if (Array.isArray(payload.bars) && payload.bars.length) dates.push(entry.date);
    } catch {
      // Ignore unreadable partial/corrupt local cache; recovery can replace it.
    }
  }
  return dates;
}

async function materializeAllParquet(end = null) {
  let converted = 0;
  for (const entry of dateDirectories(PARQUET_ROOT, "bars.parquet")) {
    if (end && entry.date > end) continue;
    if (existsSync(jsonPath(entry.date))) continue;
    if (await materializeParquet(entry.date)) {
      converted += 1;
      if (converted % 25 === 0) console.log(`[local:history] materialized ${converted} parquet sessions`);
    }
  }
  return converted;
}

async function massiveGroupedDaily(date, apiKey) {
  const url = new URL(`/v2/aggs/grouped/locale/us/market/stocks/${date}`, MASSIVE_BASE_URL);
  url.searchParams.set("adjusted", "true");
  url.searchParams.set("apiKey", apiKey);

  for (let attempt = 0; attempt < MAX_RETRIES; attempt += 1) {
    let response;
    try {
      response = await fetch(url, {
        headers: { Accept: "application/json", "User-Agent": "FutureView-History-Recovery/2.0" },
        signal: AbortSignal.timeout(30_000),
      });
    } catch (error) {
      if (attempt + 1 >= MAX_RETRIES) throw new Error(`Massive transport error for ${date}: ${error.message}`);
      const delay = 2_000 * (attempt + 1);
      console.warn(`[local:history] Massive transport error; retry after ${(delay / 1000).toFixed(1)}s`);
      await sleep(delay);
      continue;
    }

    if (response.ok) {
      const payload = await response.json();
      if (!payload || typeof payload !== "object") throw new Error("Massive returned non-object JSON");
      return payload;
    }

    const body = await response.text();
    const retryable = response.status === 429 || response.status >= 500;
    if (!retryable || attempt + 1 >= MAX_RETRIES) {
      throw new Error(`Massive HTTP ${response.status} for ${date}: ${body.slice(0, 300)}`);
    }
    const retryAfter = Number(response.headers.get("retry-after"));
    const delay = Number.isFinite(retryAfter) && retryAfter >= 0
      ? Math.max(1_000, retryAfter * 1000)
      : 15_000 * (attempt + 1);
    console.warn(`[local:history] Massive HTTP ${response.status}; retry after ${(delay / 1000).toFixed(1)}s`);
    await sleep(delay);
  }

  throw new Error(`Massive request exhausted retries for ${date}`);
}

async function recoverUntilSessions(required, end) {
  let sessions = existingSessionDates(end);
  if (sessions.length >= required) return { requests: 0, sessions: sessions.length };

  const apiKey = massiveApiKey();
  if (!apiKey) fail(`need ${required - sessions.length} more sessions but MASSIVE_API_KEY is unavailable`);

  let cursor = sessions.length ? shiftDate(sessions[0], -1) : end;
  let requests = 0;
  while (sessions.length < required) {
    if (isWeekend(cursor)) {
      cursor = shiftDate(cursor, -1);
      continue;
    }

    if (existsSync(jsonPath(cursor))) {
      try {
        const payload = JSON.parse(readFileSync(jsonPath(cursor), "utf8"));
        if (Array.isArray(payload.bars) && payload.bars.length) sessions.push(cursor);
      } catch {
        // Fall through and recover this session.
      }
      cursor = shiftDate(cursor, -1);
      continue;
    }

    if (await materializeParquet(cursor)) {
      sessions.push(cursor);
      cursor = shiftDate(cursor, -1);
      continue;
    }

    if (existsSync(closedPath(cursor))) {
      cursor = shiftDate(cursor, -1);
      continue;
    }

    const payload = await massiveGroupedDaily(cursor, apiKey);
    requests += 1;
    const rows = Array.isArray(payload.results) ? payload.results : [];
    const document = normalizeDocument(cursor, rows, {
      source: "massive",
      producer: "codespaces-history-recovery",
    });

    if (document.count) {
      writeJsonDocument(cursor, document);
      sessions.push(cursor);
      sessions.sort();
      console.log(`[local:history] recovered ${cursor}: ${document.count} bars (${sessions.length}/${required} sessions)`);
    } else {
      mkdirSync(CLOSED_ROOT, { recursive: true });
      writeFileSync(closedPath(cursor), JSON.stringify({
        date: cursor,
        status: "no_market_data",
        checked_at: new Date().toISOString(),
      }));
      console.log(`[local:history] no market data ${cursor}; marked closed/unavailable`);
    }

    cursor = shiftDate(cursor, -1);
    if (sessions.length < required) await sleep(PACE_MS);
  }

  return { requests, sessions: sessions.length };
}

const options = parseArgs();
const end = options.end ?? latestCompletedSession();
console.log(`[local:history] target end=${end} mode=${options.mode}`);

const converted = await materializeAllParquet(end);
console.log(`[local:history] parquet materialized: ${converted}`);

if (options.mode === "materialize") {
  const sessions = existingSessionDates(end);
  console.log(`[local:history] READY: ${sessions.length} local sessions through ${end}`);
  process.exit(0);
}

const result = await recoverUntilSessions(options.sessions, end);
const sessions = existingSessionDates(end);
console.log("\n[local:history] READY");
console.log(`[local:history] sessions: ${result.sessions} (${sessions.at(-options.sessions)} -> ${sessions.at(-1)})`);
console.log(`[local:history] Massive recovery requests this run: ${result.requests}`);
console.log(`[local:history] canonical history: ${JSON_ROOT}/`);

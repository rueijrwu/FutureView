import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";

import { advanceBacktest, createBacktestState, finalizeBacktest } from "../../worker/backtest-core.js";
import { trueRange, updateSymbolState } from "../../worker/feature-core.js";
import { rankCrossSection } from "../../worker/ranking-core.js";
import { BACKTEST_CONFIG_V1, STRATEGY_VERSION } from "../../worker/strategy-config.js";

const WRANGLER_VERSION = "4.125.0";
const LOCAL_CONFIG = ".wrangler.local.json";
const LOCAL_STATE_DIR = ".local-state";
const SYNC_DIR = ".local-sync";
const CACHE_DIR = ".local-backtest";
const BAR_DIR = `${CACHE_DIR}/bars`;
const SESSION_DIR = `${CACHE_DIR}/sessions`;
const CHECKPOINT_FILE = `${CACHE_DIR}/checkpoint.json`;
const TMP_DIR = `${CACHE_DIR}/tmp`;
const R2_BUCKET = "futureview-data";
const MASSIVE_BASE_URL = "https://api.massive.com";
const WARMUP_SESSIONS = 211;
const DEFAULT_BACKTEST_SESSIONS = 126;

function fail(message) {
  console.error(`\n[local:backtest] ERROR: ${message}`);
  process.exit(1);
}

function parseArgs() {
  const out = { sessions: DEFAULT_BACKTEST_SESSIONS, endDate: null, rebuild: false };
  for (const arg of process.argv.slice(2)) {
    if (arg === "--rebuild") out.rebuild = true;
    else if (arg.startsWith("--sessions=")) out.sessions = Number(arg.slice(11));
    else if (arg.startsWith("--end=")) out.endDate = arg.slice(6);
    else fail(`unknown argument: ${arg}`);
  }
  if (!Number.isInteger(out.sessions) || out.sessions < 20 || out.sessions > 500) {
    fail("--sessions must be an integer from 20 to 500");
  }
  if (out.endDate && !/^\d{4}-\d{2}-\d{2}$/.test(out.endDate)) fail("--end must be YYYY-MM-DD");
  return out;
}

function ensureDirs() {
  for (const dir of [CACHE_DIR, BAR_DIR, SESSION_DIR, TMP_DIR]) mkdirSync(dir, { recursive: true });
}

function run(command, args, { allowFailure = false } = {}) {
  const result = spawnSync(command, args, { encoding: "utf8", env: process.env });
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

function syncCachePathForKey(key) {
  return `${SYNC_DIR}/${key.replace(/[^A-Za-z0-9._-]/g, "__")}`;
}

function localR2Get(key) {
  const file = `${TMP_DIR}/get-${createHash("sha1").update(key).digest("hex")}.json`;
  const result = run("npx", wranglerArgs(
    "r2", "object", "get", `${R2_BUCKET}/${key}`,
    "--file", file,
    "--local", "--persist-to", LOCAL_STATE_DIR,
    "--config", LOCAL_CONFIG,
  ), { allowFailure: true });
  if (result.status === 0 && existsSync(file)) {
    return JSON.parse(readFileSync(file, "utf8"));
  }

  const synced = syncCachePathForKey(key);
  if (existsSync(synced)) {
    console.log(`[local:backtest] using synced cache for ${key}`);
    return JSON.parse(readFileSync(synced, "utf8"));
  }
  return null;
}

function localR2Put(key, payload) {
  const file = `${TMP_DIR}/put-${createHash("sha1").update(key).digest("hex")}.json`;
  writeFileSync(file, JSON.stringify(payload));
  run("npx", wranglerArgs(
    "r2", "object", "put", `${R2_BUCKET}/${key}`,
    "--file", file,
    "--content-type", "application/json",
    "--local", "--persist-to", LOCAL_STATE_DIR,
    "--config", LOCAL_CONFIG,
  ));
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

function apiKey() {
  return process.env.MASSIVE_API_KEY || loadDevVars().MASSIVE_API_KEY || null;
}

function shiftDate(iso, days) {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

function isWeekend(iso) {
  const day = new Date(`${iso}T12:00:00Z`).getUTCDay();
  return day === 0 || day === 6;
}

function nyDate() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date());
}

function barPath(date) { return `${BAR_DIR}/${date}.json`; }
function sessionPath(date) { return `${SESSION_DIR}/${date}.json`; }

async function groupedDaily(key, date) {
  const path = barPath(date);
  if (existsSync(path)) return JSON.parse(readFileSync(path, "utf8"));
  const url = new URL(`/v2/aggs/grouped/locale/us/market/stocks/${date}`, MASSIVE_BASE_URL);
  url.searchParams.set("adjusted", "true");
  url.searchParams.set("apiKey", key);
  const response = await fetch(url, { headers: { Accept: "application/json", "User-Agent": "FutureView-LocalBacktest/1.0" } });
  if (!response.ok) throw new Error(`Massive HTTP ${response.status} for ${date}: ${(await response.text()).slice(0, 200)}`);
  const payload = await response.json();
  const bars = (Array.isArray(payload.results) ? payload.results : [])
    .filter((x) => x?.T && x.o != null && x.h != null && x.l != null && x.c != null && x.v != null)
    .map((x) => ({ symbol: String(x.T), open: Number(x.o), high: Number(x.h), low: Number(x.l), close: Number(x.c), volume: Number(x.v) }));
  const out = { date, bars };
  writeFileSync(path, JSON.stringify(out));
  console.log(`[local:backtest] cached bars ${date}: ${bars.length}`);
  return out;
}

async function collectBackward(key, endDate, count) {
  const rows = [];
  let cursor = endDate;
  let scanned = 0;
  while (rows.length < count && scanned < count + 160) {
    if (isWeekend(cursor)) { cursor = shiftDate(cursor, -1); continue; }
    const date = cursor;
    cursor = shiftDate(cursor, -1);
    scanned += 1;
    const payload = await groupedDaily(key, date);
    if (payload.bars.length) rows.push(payload);
  }
  if (rows.length < count) fail(`found only ${rows.length} valid sessions; need ${count}`);
  return rows.reverse();
}

async function collectForward(key, afterDate, endDate) {
  const rows = [];
  for (let date = shiftDate(afterDate, 1); date <= endDate; date = shiftDate(date, 1)) {
    if (isWeekend(date)) continue;
    const payload = await groupedDaily(key, date);
    if (payload.bars.length) rows.push(payload);
  }
  return rows;
}

function mean(values) { return values.reduce((a, b) => a + Number(b), 0) / values.length; }

function bootstrapStates(sessions, eligible) {
  const histories = new Map();
  for (const session of sessions) {
    for (const bar of session.bars) {
      if (!eligible.has(bar.symbol) && bar.symbol !== "SPY") continue;
      let h = histories.get(bar.symbol);
      if (!h) {
        h = { closes: [], highs: [], volumes: [], trueRanges: [], sma50History: [], lastDate: null };
        histories.set(bar.symbol, h);
      }
      const prev = h.closes.at(-1);
      if (prev != null) h.trueRanges.push(trueRange(bar.high, bar.low, prev));
      h.closes.push(bar.close);
      h.highs.push(bar.high);
      h.volumes.push(bar.volume);
      if (h.closes.length >= 50) h.sma50History.push(mean(h.closes.slice(-50)));
      h.lastDate = session.date;
    }
  }
  const states = new Map();
  for (const [symbol, h] of histories.entries()) {
    if (h.closes.length < 200 || h.highs.length < 50 || h.volumes.length < 20 || h.trueRanges.length < 14 || h.sma50History.length < 11) continue;
    states.set(symbol, {
      symbol, as_of: h.lastDate,
      closes: h.closes.slice(-200), highs: h.highs.slice(-50), volumes: h.volumes.slice(-20),
      true_ranges: h.trueRanges.slice(-14), sma50_history: h.sma50History.slice(-11),
    });
  }
  if (!states.has("SPY")) fail("SPY did not bootstrap; cannot compute relative strength");
  return states;
}

function serializeMap(map) { return [...map.entries()]; }
function deserializeMap(rows) { return new Map(rows ?? []); }

function loadCheckpoint() {
  if (!existsSync(CHECKPOINT_FILE)) return null;
  const raw = JSON.parse(readFileSync(CHECKPOINT_FILE, "utf8"));
  return {
    ...raw,
    featureStates: deserializeMap(raw.featureStates),
    rankingStates: deserializeMap(raw.rankingStates),
  };
}

function saveCheckpoint(checkpoint) {
  writeFileSync(CHECKPOINT_FILE, JSON.stringify({
    ...checkpoint,
    featureStates: serializeMap(checkpoint.featureStates),
    rankingStates: serializeMap(checkpoint.rankingStates),
  }));
}

function processSession(checkpoint, payload, eligible) {
  const bars = new Map(payload.bars.map((bar) => [bar.symbol, bar]));
  const features = [];
  const nextFeatureStates = new Map();
  for (const [symbol, state] of checkpoint.featureStates.entries()) {
    const bar = bars.get(symbol);
    if (!bar) { nextFeatureStates.set(symbol, state); continue; }
    const { nextState, feature } = updateSymbolState(state, bar, payload.date);
    nextFeatureStates.set(symbol, nextState);
    features.push(feature);
  }
  const ranked = rankCrossSection({
    features,
    tradingDate: payload.date,
    eligibleSymbols: eligible,
    priorStates: checkpoint.rankingStates,
    priorSessionCount: checkpoint.processedDates.length,
  });
  const artifact = { date: payload.date, rankings: ranked.rankings, features };
  writeFileSync(sessionPath(payload.date), JSON.stringify(artifact));
  checkpoint.featureStates = nextFeatureStates;
  checkpoint.rankingStates = ranked.states;
  checkpoint.processedDates.push(payload.date);
  checkpoint.asOf = payload.date;
  saveCheckpoint(checkpoint);
  console.log(`[local:backtest] processed ${payload.date}: ${features.length} features / ${ranked.rankings.length} ranked`);
}

function loadUniverse() {
  const pointer = localR2Get("metadata/latest-common-stock-universe.json");
  if (!pointer?.data_key) fail("local common-stock universe pointer is missing; run npm run local:sync first");
  const payload = localR2Get(pointer.data_key);
  if (!payload?.symbols?.length) fail("local common-stock universe is empty");
  return { asOf: payload.as_of ?? pointer.as_of ?? null, symbols: new Set(payload.symbols.map(String)) };
}

function runBacktest(processedDates, sessions) {
  const selected = processedDates.slice(-sessions);
  let state = createBacktestState(BACKTEST_CONFIG_V1);
  for (const date of selected) {
    const artifact = JSON.parse(readFileSync(sessionPath(date), "utf8"));
    state = advanceBacktest(state, { date, rankings: artifact.rankings, features: artifact.features }, BACKTEST_CONFIG_V1);
  }
  const finalized = finalizeBacktest(state, BACKTEST_CONFIG_V1);
  return { selected, finalized };
}

const options = parseArgs();
if (options.rebuild) rmSync(CACHE_DIR, { recursive: true, force: true });
ensureDirs();
const key = apiKey();
if (!key) fail("MASSIVE_API_KEY is required in the environment or .dev.vars");
const universe = loadUniverse();
const endDate = options.endDate ?? nyDate();
let checkpoint = loadCheckpoint();

if (!checkpoint) {
  console.log(`[local:backtest] bootstrap ${WARMUP_SESSIONS} warm-up + ${options.sessions} backtest sessions through ${endDate}`);
  const all = await collectBackward(key, endDate, WARMUP_SESSIONS + options.sessions);
  const warmup = all.slice(0, WARMUP_SESSIONS);
  checkpoint = {
    version: 1,
    strategyVersion: STRATEGY_VERSION,
    universeAsOf: universe.asOf,
    asOf: warmup.at(-1).date,
    processedDates: [],
    featureStates: bootstrapStates(warmup, universe.symbols),
    rankingStates: new Map(),
  };
  saveCheckpoint(checkpoint);
  for (const session of all.slice(WARMUP_SESSIONS)) processSession(checkpoint, session, universe.symbols);
} else {
  if (checkpoint.strategyVersion !== STRATEGY_VERSION) fail("strategy version changed; rerun npm run local:backtest -- --rebuild");
  if (checkpoint.universeAsOf !== universe.asOf) {
    console.warn(`[local:backtest] universe changed ${checkpoint.universeAsOf} -> ${universe.asOf}; keeping cached history. Use --rebuild for a clean universe-consistent run.`);
  }
  if (endDate > checkpoint.asOf) {
    const additions = await collectForward(key, checkpoint.asOf, endDate);
    for (const session of additions) processSession(checkpoint, session, universe.symbols);
  } else {
    console.log(`[local:backtest] historical features/rankings already cached through ${checkpoint.asOf}; no recomputation`);
  }
}

if (checkpoint.processedDates.length < options.sessions) fail(`only ${checkpoint.processedDates.length} processed sessions are cached; requested ${options.sessions}`);
const { selected, finalized } = runBacktest(checkpoint.processedDates, options.sessions);
const now = new Date().toISOString();
const id = `local-${selected[0]}-${selected.at(-1)}-${options.sessions}`;
const resultKey = `backtests/run=${id}/result.json`;
const result = {
  id,
  strategy_version: STRATEGY_VERSION,
  config: BACKTEST_CONFIG_V1,
  start_date: selected[0],
  end_date: selected.at(-1),
  status: "complete",
  summary: finalized.summary,
  equity_curve: finalized.equityCurve,
  trades: finalized.trades,
  producer: "codespaces-local-js",
  universe_as_of: universe.asOf,
  universe_note: "Historical local bootstrap currently uses the synced common-stock universe across the replay window; interpret results with survivorship-bias caution.",
  updated_at: now,
};
localR2Put(resultKey, result);
localR2Put("metadata/latest-backtest.json", {
  id, strategy_version: STRATEGY_VERSION,
  start_date: selected[0], end_date: selected.at(-1), status: "complete",
  result_key: resultKey, summary: finalized.summary,
  producer: "codespaces-local-js", universe_as_of: universe.asOf, updated_at: now,
});

console.log("\n[local:backtest] READY");
console.log(`[local:backtest] sessions: ${selected.length} (${selected[0]} -> ${selected.at(-1)})`);
console.log(`[local:backtest] trades: ${finalized.summary.trade_count}; win rate: ${finalized.summary.win_rate == null ? "n/a" : (finalized.summary.win_rate * 100).toFixed(2) + "%"}`);
console.log(`[local:backtest] total return: ${(finalized.summary.total_return * 100).toFixed(2)}%; max drawdown: ${(finalized.summary.max_drawdown * 100).toFixed(2)}%`);
console.log(`[local:backtest] cached through: ${checkpoint.asOf}`);
console.log(`[local:backtest] local R2: metadata/latest-backtest.json -> ${resultKey}`);
console.log("Restart npm run local:dev, then open /backtest or curl /api/backtests/audit");

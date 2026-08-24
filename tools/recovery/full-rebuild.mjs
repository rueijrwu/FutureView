import fs from "node:fs/promises";
import path from "node:path";

const MASSIVE_BASE_URL = "https://api.massive.com";
const STATE_VERSION = 1;
const STATE_SHARDS = 32;
const REQUIRED_SESSIONS = 211;

function shiftIsoDate(isoDate, days) {
  const date = new Date(`${isoDate}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function isWeekend(isoDate) {
  const day = new Date(`${isoDate}T12:00:00Z`).getUTCDay();
  return day === 0 || day === 6;
}

function shardForSymbol(symbol) {
  let total = 0;
  for (const character of symbol) total += character.codePointAt(0);
  return total % STATE_SHARDS;
}

function mean(values) {
  return values.reduce((sum, value) => sum + Number(value), 0) / values.length;
}

function trueRange(high, low, previousClose) {
  return Math.max(
    Number(high) - Number(low),
    Math.abs(Number(high) - Number(previousClose)),
    Math.abs(Number(low) - Number(previousClose)),
  );
}

async function fetchGroupedDaily(apiKey, tradingDate) {
  const url = new URL(`/v2/aggs/grouped/locale/us/market/stocks/${tradingDate}`, MASSIVE_BASE_URL);
  url.searchParams.set("adjusted", "true");
  url.searchParams.set("apiKey", apiKey);
  const response = await fetch(url, {
    headers: { Accept: "application/json", "User-Agent": "FutureView-Recovery/1.0" },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Massive HTTP ${response.status} for ${tradingDate}: ${body.slice(0, 300)}`);
  }
  const payload = await response.json();
  const results = Array.isArray(payload.results) ? payload.results : [];
  return results
    .filter((item) => item?.T && item.o != null && item.h != null
      && item.l != null && item.c != null && item.v != null)
    .map((item) => ({
      symbol: String(item.T),
      open: Number(item.o),
      high: Number(item.h),
      low: Number(item.l),
      close: Number(item.c),
      volume: Number(item.v),
    }));
}

const [targetDate, universePath, outputDir] = process.argv.slice(2);
if (!/^\d{4}-\d{2}-\d{2}$/.test(targetDate ?? "") || !universePath || !outputDir) {
  throw new Error("usage: node tools/recovery/full-rebuild.mjs <YYYY-MM-DD> <universe.json> <outputDir>");
}
const apiKey = process.env.MASSIVE_API_KEY;
if (!apiKey) throw new Error("MASSIVE_API_KEY is required");

const universe = JSON.parse(await fs.readFile(universePath, "utf8"));
const eligible = new Set((universe.symbols ?? []).map(String));
eligible.add("SPY");
if (eligible.size < 2) throw new Error("common-stock universe is empty");

const sessions = [];
let cursor = targetDate;
let scannedWeekdays = 0;
while (sessions.length < REQUIRED_SESSIONS && scannedWeekdays < 340) {
  if (isWeekend(cursor)) {
    cursor = shiftIsoDate(cursor, -1);
    continue;
  }
  const date = cursor;
  scannedWeekdays += 1;
  const bars = await fetchGroupedDaily(apiKey, date);
  if (bars.length) {
    sessions.push({
      date,
      bars: bars.filter((bar) => eligible.has(bar.symbol)),
    });
    console.log(`accepted ${date}: ${sessions.length}/${REQUIRED_SESSIONS}`);
  } else {
    console.log(`skipped ${date}: no grouped-daily bars`);
  }
  cursor = shiftIsoDate(cursor, -1);
}
if (sessions.length < REQUIRED_SESSIONS) {
  throw new Error(`found only ${sessions.length} valid sessions on or before ${targetDate}`);
}

sessions.sort((a, b) => a.date.localeCompare(b.date));
const sourceAsOf = sessions.at(-1).date;
if (sourceAsOf !== targetDate) {
  throw new Error(`target_date ${targetDate} is not a valid market session; latest session found is ${sourceAsOf}`);
}

const histories = new Map();
for (const session of sessions) {
  for (const bar of session.bars) {
    let history = histories.get(bar.symbol);
    if (!history) {
      history = {
        symbol: bar.symbol,
        closes: [], highs: [], volumes: [], trueRanges: [], sma50History: [], lastDate: null,
      };
      histories.set(bar.symbol, history);
    }
    const previousClose = history.closes.at(-1);
    if (previousClose != null) history.trueRanges.push(trueRange(bar.high, bar.low, previousClose));
    history.closes.push(bar.close);
    history.highs.push(bar.high);
    history.volumes.push(bar.volume);
    if (history.closes.length >= 50) history.sma50History.push(mean(history.closes.slice(-50)));
    history.lastDate = session.date;
  }
}

const shards = Array.from({ length: STATE_SHARDS }, () => []);
for (const history of histories.values()) {
  if (
    history.closes.length < 200
    || history.highs.length < 50
    || history.volumes.length < 20
    || history.trueRanges.length < 14
    || history.sma50History.length < 11
  ) continue;
  const state = {
    symbol: history.symbol,
    as_of: history.lastDate ?? sourceAsOf,
    closes: history.closes.slice(-200),
    highs: history.highs.slice(-50),
    volumes: history.volumes.slice(-20),
    true_ranges: history.trueRanges.slice(-14),
    sma50_history: history.sma50History.slice(-11),
  };
  shards[shardForSymbol(history.symbol)].push(state);
}

await fs.mkdir(outputDir, { recursive: true });
const keys = [];
let symbolCount = 0;
let spyFound = false;
for (let shard = 0; shard < STATE_SHARDS; shard += 1) {
  const name = String(shard).padStart(2, "0");
  const states = shards[shard].sort((a, b) => a.symbol.localeCompare(b.symbol));
  if (states.some((state) => state.symbol === "SPY")) spyFound = true;
  const payload = {
    version: STATE_VERSION,
    as_of: sourceAsOf,
    shard,
    shard_count: STATE_SHARDS,
    count: states.length,
    states,
    producer: "cloudflare-js-bootstrap",
    seed_source: "github-actions-full-rebuild",
  };
  await fs.writeFile(path.join(outputDir, `shard=${name}.json`), JSON.stringify(payload));
  keys.push(`state/rolling/v${STATE_VERSION}/date=${sourceAsOf}/shard=${name}.json`);
  symbolCount += states.length;
}
if (!spyFound) throw new Error("rebuilt state does not contain SPY benchmark state");

const now = new Date().toISOString();
const metadata = {
  version: STATE_VERSION,
  as_of: sourceAsOf,
  shard_count: STATE_SHARDS,
  symbol_count: symbolCount,
  prefix: `state/rolling/v${STATE_VERSION}/date=${sourceAsOf}`,
  keys,
  producer: "cloudflare-js-bootstrap",
  seed_source: "github-actions-full-rebuild",
  benchmark: "SPY",
  bootstrap_session_count: sessions.length,
  universe_as_of: universe.as_of ?? null,
  updated_at: now,
};
const status = {
  status: "complete",
  mode: "github-actions-full-rebuild",
  target_date: targetDate,
  source_as_of: sourceAsOf,
  symbol_count: symbolCount,
  shard_count: STATE_SHARDS,
  session_count: sessions.length,
  benchmark: "SPY",
  updated_at: now,
};
await fs.writeFile(path.join(outputDir, "metadata.json"), JSON.stringify(metadata));
await fs.writeFile(path.join(outputDir, "status.json"), JSON.stringify(status));
console.log(JSON.stringify(status, null, 2));

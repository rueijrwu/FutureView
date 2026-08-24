import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";

import { advanceBacktest, createBacktestState, finalizeBacktest } from "../../worker/backtest-core.js";
import { trueRange, updateSymbolState } from "../../worker/feature-core.js";
import { rankCrossSection } from "../../worker/ranking-core.js";
import {
  BACKTEST_CONFIG_V1,
  RANKING_CONFIG_SECTOR_RS_EXPERIMENT,
  STRATEGY_VERSION,
} from "../../worker/strategy-config.js";
import {
  createFilesystemJsonStore,
  materializeFromSyncCache,
} from "./fs-store.mjs";

const CACHE_DIR = ".local-backtest";
const SESSION_DIR = `${CACHE_DIR}/sessions`;
const CHECKPOINT_FILE = `${CACHE_DIR}/checkpoint.json`;
const DAILY_JSON_ROOT = ".local-data/objects/prices/daily-json";
const WARMUP_SESSIONS = 211;
const DEFAULT_BACKTEST_SESSIONS = 126;
const SECTOR_CORRELATION_LOOKBACK = 60;
const LOCAL_RANKING_EXPERIMENT = "sector-rs-correlation-v1";
const SECTOR_ETFS = Object.freeze([
  "XLB",
  "XLC",
  "XLE",
  "XLF",
  "XLI",
  "XLK",
  "XLP",
  "XLRE",
  "XLU",
  "XLV",
  "XLY",
]);
const BENCHMARK_SYMBOLS = new Set(["SPY", ...SECTOR_ETFS]);
const store = createFilesystemJsonStore();

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
  for (const dir of [CACHE_DIR, SESSION_DIR]) mkdirSync(dir, { recursive: true });
}

function dailyJsonPath(date) {
  return `${DAILY_JSON_ROOT}/date=${date}/bars.json`;
}

function sessionPath(date) { return `${SESSION_DIR}/${date}.json`; }

function availableSessionDates(endDate = null) {
  if (!existsSync(DAILY_JSON_ROOT)) return [];
  return readdirSync(DAILY_JSON_ROOT, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && /^date=\d{4}-\d{2}-\d{2}$/.test(entry.name))
    .map((entry) => entry.name.slice(5))
    .filter((date) => (!endDate || date <= endDate) && existsSync(dailyJsonPath(date)))
    .filter((date) => {
      try {
        const payload = JSON.parse(readFileSync(dailyJsonPath(date), "utf8"));
        return Array.isArray(payload?.bars) && payload.bars.length > 0;
      } catch {
        return false;
      }
    })
    .sort();
}

function groupedDaily(date) {
  const file = dailyJsonPath(date);
  if (!existsSync(file)) {
    fail(`local daily history is missing ${date}; run npm run recovery:history before backtesting`);
  }
  const payload = JSON.parse(readFileSync(file, "utf8"));
  const bars = (Array.isArray(payload?.bars) ? payload.bars : [])
    .filter((row) => row?.symbol && row.open != null && row.high != null && row.low != null && row.close != null && row.volume != null)
    .map((row) => ({
      symbol: String(row.symbol),
      open: Number(row.open),
      high: Number(row.high),
      low: Number(row.low),
      close: Number(row.close),
      volume: Number(row.volume),
    }));
  if (!bars.length) fail(`local daily history has no valid bars for ${date}`);
  return { date, bars };
}

function collectBackward(endDate, count) {
  const dates = availableSessionDates(endDate);
  if (dates.length < count) {
    fail(`found only ${dates.length} local sessions through ${endDate}; need ${count}. Run npm run recovery:history -- --sessions=${count} --end=${endDate}`);
  }
  return dates.slice(-count).map(groupedDaily);
}

function collectForward(afterDate, endDate) {
  return availableSessionDates(endDate)
    .filter((date) => date > afterDate)
    .map(groupedDaily);
}

function mean(values) {
  return values.reduce((sum, value) => sum + Number(value), 0) / values.length;
}

function dailyReturns(closes, lookback = SECTOR_CORRELATION_LOOKBACK) {
  const values = (closes ?? []).slice(-(lookback + 1)).map(Number);
  if (values.length < lookback + 1 || values.some((value) => !Number.isFinite(value) || value <= 0)) {
    return null;
  }
  const returns = [];
  for (let i = 1; i < values.length; i += 1) {
    returns.push(values[i] / values[i - 1] - 1);
  }
  return returns;
}

function correlation(left, right) {
  if (!left || !right || left.length !== right.length || left.length < 2) return null;
  const leftMean = mean(left);
  const rightMean = mean(right);
  let covariance = 0;
  let leftVariance = 0;
  let rightVariance = 0;
  for (let i = 0; i < left.length; i += 1) {
    const leftDelta = Number(left[i]) - leftMean;
    const rightDelta = Number(right[i]) - rightMean;
    covariance += leftDelta * rightDelta;
    leftVariance += leftDelta ** 2;
    rightVariance += rightDelta ** 2;
  }
  const denominator = Math.sqrt(leftVariance * rightVariance);
  if (!(denominator > 0)) return null;
  return covariance / denominator;
}

function closestSectorBenchmarks(featureStates, eligible) {
  const benchmarkReturns = new Map();
  for (const symbol of SECTOR_ETFS) {
    const values = dailyReturns(featureStates.get(symbol)?.closes);
    if (values) benchmarkReturns.set(symbol, values);
  }
  if (benchmarkReturns.size !== SECTOR_ETFS.length) {
    const missing = SECTOR_ETFS.filter((symbol) => !benchmarkReturns.has(symbol));
    fail(`sector ETF history is incomplete for: ${missing.join(", ")}`);
  }

  const sectorBenchmarkBySymbol = new Map();
  const correlationBySymbol = new Map();
  for (const symbol of eligible) {
    const stockReturns = dailyReturns(featureStates.get(symbol)?.closes);
    if (!stockReturns) continue;
    let bestSymbol = null;
    let bestCorrelation = -Infinity;
    for (const sectorSymbol of SECTOR_ETFS) {
      const value = correlation(stockReturns, benchmarkReturns.get(sectorSymbol));
      if (value == null) continue;
      if (value > bestCorrelation) {
        bestCorrelation = value;
        bestSymbol = sectorSymbol;
      }
    }
    if (bestSymbol) {
      sectorBenchmarkBySymbol.set(symbol, bestSymbol);
      correlationBySymbol.set(symbol, bestCorrelation);
    }
  }
  return { sectorBenchmarkBySymbol, correlationBySymbol };
}

function bootstrapStates(sessions, eligible) {
  const histories = new Map();
  for (const session of sessions) {
    for (const bar of session.bars) {
      if (!eligible.has(bar.symbol) && !BENCHMARK_SYMBOLS.has(bar.symbol)) continue;
      let history = histories.get(bar.symbol);
      if (!history) {
        history = { closes: [], highs: [], volumes: [], trueRanges: [], sma50History: [], lastDate: null };
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

  const states = new Map();
  for (const [symbol, history] of histories.entries()) {
    if (
      history.closes.length < 200
      || history.highs.length < 50
      || history.volumes.length < 20
      || history.trueRanges.length < 14
      || history.sma50History.length < 11
    ) continue;
    states.set(symbol, {
      symbol,
      as_of: history.lastDate,
      closes: history.closes.slice(-200),
      highs: history.highs.slice(-50),
      volumes: history.volumes.slice(-20),
      true_ranges: history.trueRanges.slice(-14),
      sma50_history: history.sma50History.slice(-11),
    });
  }

  const missingBenchmarks = [...BENCHMARK_SYMBOLS].filter((symbol) => !states.has(symbol));
  if (missingBenchmarks.length) {
    fail(`benchmark history did not bootstrap for: ${missingBenchmarks.join(", ")}`);
  }
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
    if (!bar) {
      nextFeatureStates.set(symbol, state);
      continue;
    }
    const { nextState, feature } = updateSymbolState(state, bar, payload.date);
    nextFeatureStates.set(symbol, nextState);
    features.push(feature);
  }

  const { sectorBenchmarkBySymbol, correlationBySymbol } = closestSectorBenchmarks(
    nextFeatureStates,
    eligible,
  );
  const ranked = rankCrossSection({
    features,
    tradingDate: payload.date,
    eligibleSymbols: eligible,
    priorStates: checkpoint.rankingStates,
    priorSessionCount: checkpoint.processedDates.length,
    sectorBenchmarkBySymbol,
    config: RANKING_CONFIG_SECTOR_RS_EXPERIMENT,
  });

  const rankings = ranked.rankings.map((row) => ({
    ...row,
    sector_benchmark_correlation: correlationBySymbol.get(String(row.symbol)) ?? null,
  }));
  writeFileSync(sessionPath(payload.date), JSON.stringify({
    date: payload.date,
    ranking_experiment: LOCAL_RANKING_EXPERIMENT,
    rankings,
    features,
  }));
  checkpoint.featureStates = nextFeatureStates;
  checkpoint.rankingStates = ranked.states;
  checkpoint.processedDates.push(payload.date);
  checkpoint.asOf = payload.date;
  saveCheckpoint(checkpoint);
  console.log(`[local:backtest] processed ${payload.date}: ${features.length} features / ${rankings.length} ranked / ${sectorBenchmarkBySymbol.size} sector mappings`);
}

async function loadUniverse() {
  const pointer = await materializeFromSyncCache(store, "metadata/latest-common-stock-universe.json");
  if (!pointer?.data_key) fail("common-stock universe is missing; run npm run local:sync first");
  const payload = await materializeFromSyncCache(store, pointer.data_key);
  if (!payload?.symbols?.length) fail("common-stock universe payload is missing or empty");
  return {
    asOf: payload.as_of ?? pointer.as_of ?? null,
    symbols: new Set(payload.symbols.map(String)),
  };
}

async function latestCompletedSession() {
  const featureState = await materializeFromSyncCache(store, "metadata/latest-feature-state.json");
  const date = featureState?.as_of ?? featureState?.date ?? null;
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    fail("latest completed feature session is missing; run npm run local:sync first or pass --end=YYYY-MM-DD");
  }
  return date;
}

function runBacktest(processedDates, sessions) {
  const selected = processedDates.slice(-sessions);
  let state = createBacktestState(BACKTEST_CONFIG_V1);
  for (const date of selected) {
    const artifact = JSON.parse(readFileSync(sessionPath(date), "utf8"));
    state = advanceBacktest(
      state,
      { date, rankings: artifact.rankings, features: artifact.features },
      BACKTEST_CONFIG_V1,
    );
  }
  return { selected, finalized: finalizeBacktest(state, BACKTEST_CONFIG_V1) };
}

const options = parseArgs();
if (options.rebuild) rmSync(CACHE_DIR, { recursive: true, force: true });
ensureDirs();

const universe = await loadUniverse();
const endDate = options.endDate ?? await latestCompletedSession();
if (!options.endDate) {
  console.log(`[local:backtest] using latest completed synced session ${endDate}`);
}
let checkpoint = loadCheckpoint();

if (!checkpoint) {
  console.log(`[local:backtest] experiment: ${LOCAL_RANKING_EXPERIMENT}`);
  console.log(`[local:backtest] bootstrap ${WARMUP_SESSIONS} warm-up + ${options.sessions} backtest sessions through ${endDate} from local history`);
  const all = collectBackward(endDate, WARMUP_SESSIONS + options.sessions);
  const warmup = all.slice(0, WARMUP_SESSIONS);
  checkpoint = {
    version: 4,
    strategyVersion: STRATEGY_VERSION,
    rankingExperiment: LOCAL_RANKING_EXPERIMENT,
    universeAsOf: universe.asOf,
    asOf: warmup.at(-1).date,
    processedDates: [],
    featureStates: bootstrapStates(warmup, universe.symbols),
    rankingStates: new Map(),
  };
  saveCheckpoint(checkpoint);
  for (const session of all.slice(WARMUP_SESSIONS)) processSession(checkpoint, session, universe.symbols);
} else {
  if (
    Number(checkpoint.version) !== 4
    || checkpoint.strategyVersion !== STRATEGY_VERSION
    || checkpoint.rankingExperiment !== LOCAL_RANKING_EXPERIMENT
  ) {
    fail("local ranking experiment changed; rerun npm run local:backtest -- --rebuild");
  }
  if (checkpoint.universeAsOf !== universe.asOf) {
    console.warn(`[local:backtest] universe changed ${checkpoint.universeAsOf} -> ${universe.asOf}; keeping cached history. Use --rebuild for a clean universe-consistent run.`);
  }
  if (endDate > checkpoint.asOf) {
    const additions = collectForward(checkpoint.asOf, endDate);
    for (const session of additions) processSession(checkpoint, session, universe.symbols);
  } else {
    console.log(`[local:backtest] historical features/rankings already cached through ${checkpoint.asOf}; no recomputation`);
  }
}

if (checkpoint.processedDates.length < options.sessions) {
  fail(`only ${checkpoint.processedDates.length} processed sessions are cached; requested ${options.sessions}`);
}

const { selected, finalized } = runBacktest(checkpoint.processedDates, options.sessions);
const now = new Date().toISOString();
const id = `local-${selected[0]}-${selected.at(-1)}-${options.sessions}`;
const resultKey = `backtests/run=${id}/result.json`;
const result = {
  id,
  strategy_version: STRATEGY_VERSION,
  ranking_experiment: LOCAL_RANKING_EXPERIMENT,
  ranking_config: RANKING_CONFIG_SECTOR_RS_EXPERIMENT,
  sector_etfs: SECTOR_ETFS,
  sector_correlation_lookback: SECTOR_CORRELATION_LOOKBACK,
  config: BACKTEST_CONFIG_V1,
  start_date: selected[0],
  end_date: selected.at(-1),
  status: "complete",
  summary: finalized.summary,
  equity_curve: finalized.equityCurve,
  trades: finalized.trades,
  producer: "codespaces-local-js",
  storage: "filesystem",
  universe_as_of: universe.asOf,
  universe_note: "Historical local bootstrap currently uses the synced common-stock universe across the replay window; interpret results with survivorship-bias caution.",
  updated_at: now,
};

await store.putJson(resultKey, result);
await store.putJson("metadata/latest-backtest.json", {
  id,
  strategy_version: STRATEGY_VERSION,
  ranking_experiment: LOCAL_RANKING_EXPERIMENT,
  start_date: selected[0],
  end_date: selected.at(-1),
  status: "complete",
  result_key: resultKey,
  summary: finalized.summary,
  producer: "codespaces-local-js",
  storage: "filesystem",
  universe_as_of: universe.asOf,
  updated_at: now,
});

console.log("\n[local:backtest] READY");
console.log(`[local:backtest] experiment: ${LOCAL_RANKING_EXPERIMENT}`);
console.log(`[local:backtest] sessions: ${selected.length} (${selected[0]} -> ${selected.at(-1)})`);
console.log(`[local:backtest] trades: ${finalized.summary.trade_count}; win rate: ${finalized.summary.win_rate == null ? "n/a" : `${(finalized.summary.win_rate * 100).toFixed(2)}%`}`);
console.log(`[local:backtest] total return: ${(finalized.summary.total_return * 100).toFixed(2)}%; max drawdown: ${(finalized.summary.max_drawdown * 100).toFixed(2)}%`);
console.log(`[local:backtest] cached through: ${checkpoint.asOf}`);
console.log(`[local:backtest] result: .local-data/objects/${resultKey}`);
console.log("Run npm run local:dev, then open /backtest or curl /api/backtests/audit");

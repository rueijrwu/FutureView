import http from "node:http";
import { existsSync, readdirSync, readFileSync } from "node:fs";

import { buildBacktestAudit } from "../../worker/backtest-audit.js";
import {
  createFilesystemJsonStore,
  materializeFromSyncCache,
} from "./fs-store.mjs";

const PORT = Number(process.env.PORT ?? 8787);
const store = createFilesystemJsonStore();
const SESSION_DIR = ".local-backtest/sessions";

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

async function readLocal(key) {
  return materializeFromSyncCache(store, key);
}

async function readLatestBacktest() {
  const metadata = await readLocal("metadata/latest-backtest.json");
  if (!metadata) return null;
  if (!metadata.result_key) return metadata;
  return readLocal(metadata.result_key);
}

function localSessionDates() {
  if (!existsSync(SESSION_DIR)) return [];
  return readdirSync(SESSION_DIR)
    .filter((name) => /^\d{4}-\d{2}-\d{2}\.json$/.test(name))
    .map((name) => name.slice(0, 10))
    .sort();
}

function readSession(date) {
  const file = `${SESSION_DIR}/${date}.json`;
  if (!existsSync(file)) return null;
  return JSON.parse(readFileSync(file, "utf8"));
}

async function latestRanking() {
  const dashboard = await readLocal("dashboard/latest.json");
  if (dashboard?.rankings?.length) return dashboard;
  const dates = localSessionDates();
  const date = dates.at(-1);
  if (!date) return null;
  const session = readSession(date);
  return {
    as_of: date,
    market_regime: "Research",
    cash_posture: "Rule-based",
    rankings: (session?.rankings ?? []).filter((row) => Number(row.rank) <= 50),
    source: "local-filesystem",
  };
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url ?? "/", `http://127.0.0.1:${PORT}`);

    if (url.pathname === "/api/health") {
      return sendJson(res, 200, {
        service: "futureview-api",
        status: "ok",
        database: "local-filesystem",
        storage: "filesystem",
        runtime: "node-local-js",
      });
    }

    if (url.pathname === "/api/rankings/latest") {
      const payload = await latestRanking();
      return payload
        ? sendJson(res, 200, payload)
        : sendJson(res, 503, { error: "latest ranking is not available" });
    }

    if (url.pathname === "/api/rankings/history") {
      const limit = Math.max(1, Math.min(Number(url.searchParams.get("limit") ?? 100), 500));
      const dates = localSessionDates().slice(-limit).reverse();
      return sendJson(res, 200, { count: dates.length, dates, source: "local-filesystem" });
    }

    const rankingDateMatch = url.pathname.match(/^\/api\/rankings\/date\/(\d{4}-\d{2}-\d{2})$/);
    if (rankingDateMatch) {
      const date = rankingDateMatch[1];
      const session = readSession(date);
      if (!session) return sendJson(res, 404, { error: `ranking not found for ${date}` });
      return sendJson(res, 200, {
        as_of: date,
        rankings: (session.rankings ?? []).filter((row) => Number(row.rank) <= 50),
        source: "local-filesystem",
      });
    }

    const symbolHistoryMatch = url.pathname.match(/^\/api\/symbols\/([^/]+)\/rankings$/);
    if (symbolHistoryMatch) {
      const symbol = decodeURIComponent(symbolHistoryMatch[1]).toUpperCase();
      const limit = Math.max(1, Math.min(Number(url.searchParams.get("limit") ?? 100), 500));
      const rows = [];
      for (const date of localSessionDates().reverse()) {
        const session = readSession(date);
        const row = (session?.rankings ?? []).find((item) => String(item.symbol).toUpperCase() === symbol);
        if (row) rows.push({ trading_date: date, ...row });
        if (rows.length >= limit) break;
      }
      return sendJson(res, 200, { symbol, count: rows.length, rankings: rows, source: "local-filesystem" });
    }

    const simplePointers = new Map([
      ["/api/ingest/status", ["metadata/latest-cloudflare-ingest.json", "ingestion has not completed yet"]],
      ["/api/universe/status", ["metadata/latest-common-stock-universe.json", "common-stock universe has not been published yet"]],
      ["/api/state/status", ["metadata/latest-feature-state.json", "incremental feature state has not been published yet"]],
      ["/api/ranking-state/status", ["metadata/latest-ranking-state.json", "incremental ranking state has not been published yet"]],
      ["/api/replay/status", ["metadata/latest-js-replay.json", "JS replay validation has not completed yet"]],
    ]);
    if (simplePointers.has(url.pathname)) {
      const [key, message] = simplePointers.get(url.pathname);
      const payload = await readLocal(key);
      return payload ? sendJson(res, 200, payload) : sendJson(res, 503, { error: message });
    }

    if (url.pathname === "/api/backtests/latest") {
      const result = await readLatestBacktest();
      return result
        ? sendJson(res, 200, result)
        : sendJson(res, 503, { error: "backtest has not completed yet" });
    }

    if (url.pathname === "/api/backtests/audit") {
      const result = await readLatestBacktest();
      return result
        ? sendJson(res, 200, buildBacktestAudit(result))
        : sendJson(res, 503, { error: "backtest has not completed yet" });
    }

    return sendJson(res, 404, { error: "not found" });
  } catch (error) {
    console.error("[local:api] request failed", error);
    return sendJson(res, 500, { error: error instanceof Error ? error.message : String(error) });
  }
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`[local:api] READY http://localhost:${PORT}`);
  console.log("[local:api] storage: .local-data (filesystem)");
});

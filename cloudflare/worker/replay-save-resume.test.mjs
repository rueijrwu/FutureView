import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

let coreSource = await fs.readFile(new URL("./replay-session-core.js", import.meta.url), "utf8");
coreSource = coreSource.replace(
  'import { DurableObject } from "cloudflare:workers";',
  "class DurableObject {}",
);
const coreModuleUrl = `data:text/javascript;base64,${Buffer.from(coreSource).toString("base64")}`;

let source = await fs.readFile(new URL("./replay-session.js", import.meta.url), "utf8");
source = source.replace("./replay-session-core.js", coreModuleUrl);
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { ReplaySession } = await import(moduleUrl);

function bar(t, price) {
  return { t, o: price, h: price + 1, l: price - 1, c: price + 0.25, v: 10 };
}

function makeDb() {
  const rows = new Map();
  const db = {
    prepare(sql) {
      return {
        bind(...args) {
          return {
            async run() {
              if (sql.includes("INSERT INTO saved_sessions")) {
                const [userId, product, contract, contractSelection, startTs, cursorTs, warmup, trading, savedAt] = args;
                rows.set(userId, { user_id: userId, product, contract, contract_selection: contractSelection, start_ts: startTs, cursor_ts: cursorTs, warmup, trading, saved_at: savedAt });
              }
              return { meta: {} };
            },
            async first() {
              if (sql.includes("SELECT") && sql.includes("saved_sessions")) return rows.get(args[0]) ?? null;
              return null;
            },
          };
        },
      };
    },
  };
  return { db, rows };
}

function makeSavedSessionInstance({ userId = 1, positionQty = 2, avgPrice = 5000 } = {}) {
  const instance = Object.create(ReplaySession.prototype);
  const trading = {
    positionQty,
    avgPrice,
    realizedPnl: 12.5,
    commission: 1.24,
    slippage: 2.5,
    pendingOrders: [{ id: "working-1", type: "limit", side: "buy", quantity: 1, limit_price: 4990, status: "working" }],
    fills: [{ id: "fill-1", sequence: 1, order_id: "o1", side: "buy", quantity: 2, fill_price: 5000, filled_at_ts: 900 }],
    nextSequence: 2,
    nextOrderSequence: 2,
    lastPrice: 5000.25,
  };
  instance.session = {
    id: "sess-1",
    userId,
    product: "MES",
    contract: "MESZ6",
    contractSelection: { reason: "prior_session_max_volume" },
    startTs: 900,
    warmup: 300,
    barIndex: 1,
    trading,
  };
  instance.shard = [bar(900, 4999), bar(960, 5000)];
  return { instance, trading };
}

test("save() persists the current cursor and trading record for the session's user", async () => {
  const { instance, trading } = makeSavedSessionInstance();
  const { db, rows } = makeDb();
  instance.env = { DB: db };

  const result = await instance.save(1);

  assert.equal(result.ok, true);
  assert.equal(result.cursor_ts, 960);
  const row = rows.get(1);
  assert.ok(row);
  assert.equal(row.contract, "MESZ6");
  assert.equal(row.cursor_ts, 960);
  const savedTrading = JSON.parse(row.trading);
  assert.equal(savedTrading.positionQty, trading.positionQty);
  assert.equal(savedTrading.avgPrice, trading.avgPrice);
  assert.equal(savedTrading.pendingOrders.length, 1);
  assert.equal(savedTrading.fills.length, 1);
  // lastPrice is intentionally not part of the saved snapshot - it is always
  // recomputed from the bar a resumed session actually lands on.
  assert.equal("lastPrice" in savedTrading, false);
});

test("save() rejects a save for a user who does not own the session", async () => {
  const { instance } = makeSavedSessionInstance({ userId: 1 });
  instance.env = { DB: makeDb().db };
  await assert.rejects(() => instance.save(2), /not authorized/i);
});

test("save() requires a database binding", async () => {
  const { instance } = makeSavedSessionInstance();
  instance.env = {};
  await assert.rejects(() => instance.save(1), /unavailable/i);
});

test("_hydrateTrading rebuilds a full trading record from a saved snapshot", async () => {
  const instance = Object.create(ReplaySession.prototype);
  const saved = {
    positionQty: -3,
    avgPrice: 4990,
    realizedPnl: 40,
    commission: 5,
    slippage: 6,
    pendingOrders: [{ id: "o1", status: "working" }],
    fills: [{ id: "f1" }],
    nextSequence: 7,
    nextOrderSequence: 9,
    lastPrice: 1, // must be ignored in favor of the explicit cursor price
  };

  const hydrated = instance._hydrateTrading(saved, 5123.5);

  assert.equal(hydrated.positionQty, -3);
  assert.equal(hydrated.avgPrice, 4990);
  assert.equal(hydrated.realizedPnl, 40);
  assert.equal(hydrated.pendingOrders.length, 1);
  assert.notEqual(hydrated.pendingOrders[0], saved.pendingOrders[0]);
  assert.equal(hydrated.fills.length, 1);
  assert.equal(hydrated.nextSequence, 7);
  assert.equal(hydrated.nextOrderSequence, 9);
  assert.equal(hydrated.lastPrice, 5123.5);
});

test("_hydrateTrading falls back to a blank record for garbage input", async () => {
  const instance = Object.create(ReplaySession.prototype);
  const hydrated = instance._hydrateTrading(null, 100);
  assert.equal(hydrated.positionQty, 0);
  assert.equal(hydrated.pendingOrders.length, 0);
  assert.equal(hydrated.lastPrice, 100);
});

test("init() hydrates trading from body.trading instead of starting blank", async () => {
  const instance = Object.create(ReplaySession.prototype);
  const shard = [bar(900, 4999), bar(960, 5000), bar(1020, 5001)];
  const contract = { contract: "MESZ6", shards: [{ key: "s0", last_time: shard.at(-1).t }] };
  instance.manifest = { contracts: { MESZ6: contract } };
  instance._manifest = async () => instance.manifest;
  instance._loadShardForContract = async () => shard;
  instance.ctx = { storage: { put: async () => {} } };
  instance.env = {};

  const savedTrading = {
    positionQty: 1,
    avgPrice: 4999,
    realizedPnl: 3,
    commission: 0.62,
    slippage: 1.25,
    pendingOrders: [],
    fills: [{ id: "f1" }],
    nextSequence: 2,
    nextOrderSequence: 1,
  };

  const result = await instance.init({
    session_id: "resumed-1",
    user_id: 1,
    product: "MES",
    contract: "MESZ6",
    start: new Date(960 * 1000).toISOString(),
    warmup: 1,
    trading: savedTrading,
  });

  assert.equal(instance.session.trading.positionQty, 1);
  assert.equal(instance.session.trading.avgPrice, 4999);
  assert.equal(instance.session.trading.fills.length, 1);
  // lastPrice always comes from the bar actually landed on, not the snapshot.
  assert.equal(instance.session.trading.lastPrice, shard[1].c);
  assert.equal(result.trading.position_qty, 1);
});

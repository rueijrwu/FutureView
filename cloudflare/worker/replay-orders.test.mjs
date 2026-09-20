import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

let coreSource = await fs.readFile(new URL("./replay-session-core.js", import.meta.url), "utf8");
coreSource = coreSource.replace(
  'import { DurableObject } from "cloudflare:workers";',
  "class DurableObject {}",
);
const coreModuleUrl = `data:text/javascript;base64,${Buffer.from(coreSource).toString("base64")}`;
const { ReplaySession } = await import(coreModuleUrl);

function bar(t, o, h, l, c) {
  return { t, o, h, l, c, v: 100 };
}

function makeSession({ product = "MES", lastPrice = 5000, positionQty = 0, avgPrice = 0 } = {}) {
  const instance = Object.create(ReplaySession.prototype);
  const trading = {
    positionQty,
    avgPrice,
    realizedPnl: 0,
    commission: 0,
    slippage: 0,
    pendingOrders: [],
    fills: [],
    nextSequence: 1,
    nextOrderSequence: 1,
    lastPrice,
  };
  instance.session = {
    id: "sess-1",
    userId: 1,
    product,
    contract: `${product}Z6`,
    state: "PAUSED",
    barIndex: 0,
    trading,
  };
  instance.shard = [bar(1000, lastPrice, lastPrice, lastPrice, lastPrice)];
  instance.env = {};
  instance.ctx = { storage: { put: async () => {} } };
  const broadcasts = [];
  instance._broadcast = (payload) => broadcasts.push(payload);
  return { instance, trading, broadcasts };
}

async function place(instance, command) {
  await instance.placeOrder(command);
  return instance._trading().pendingOrders.at(-1);
}

// --- market -----------------------------------------------------------------

test("market order fills at the next released bar open", async () => {
  const { instance, trading } = makeSession();
  await place(instance, { order_type: "market", side: "buy", quantity: 2 });
  await instance._fillPendingOrders(bar(1060, 5010, 5020, 5000, 5015));

  assert.equal(trading.pendingOrders.length, 0);
  assert.equal(trading.fills.length, 1);
  assert.equal(trading.fills[0].fill_price, 5010);
  assert.equal(trading.fills[0].order_type, "market");
  assert.equal(trading.positionQty, 2);
});

test("market fill charges commission per contract per side and one tick of slippage", async () => {
  const { instance, trading } = makeSession();
  await place(instance, { order_type: "market", side: "buy", quantity: 3 });
  await instance._fillPendingOrders(bar(1060, 5010, 5020, 5000, 5015));

  // MES: $0.62 per contract per side, 1 tick = 0.25 * $5 = $1.25 per contract.
  assert.equal(trading.commission, 0.62 * 3);
  assert.equal(trading.slippage, 1.25 * 3);
  assert.equal(trading.fills[0].commission, 0.62 * 3);
  assert.equal(trading.fills[0].slippage, 1.25 * 3);
});

test("ES carries its own commission and a tick worth ten times the MES tick", async () => {
  const { instance, trading } = makeSession({ product: "ES" });
  await place(instance, { order_type: "market", side: "sell", quantity: 1 });
  await instance._fillPendingOrders(bar(1060, 5010, 5020, 5000, 5015));

  assert.equal(trading.commission, 2.25);
  assert.equal(trading.slippage, 0.25 * 50);
});

// --- limit ------------------------------------------------------------------

test("buy limit rests while the bar stays above it", async () => {
  const { instance, trading } = makeSession();
  await place(instance, { order_type: "limit", side: "buy", quantity: 1, limit_price: 4990 });
  await instance._fillPendingOrders(bar(1060, 5010, 5020, 4995, 5015));

  assert.equal(trading.pendingOrders.length, 1);
  assert.equal(trading.fills.length, 0);
});

test("buy limit fills at its own price once the bar trades through it", async () => {
  const { instance, trading } = makeSession();
  await place(instance, { order_type: "limit", side: "buy", quantity: 1, limit_price: 4990 });
  await instance._fillPendingOrders(bar(1060, 5010, 5020, 4985, 5000));

  assert.equal(trading.fills.length, 1);
  assert.equal(trading.fills[0].fill_price, 4990);
  assert.equal(trading.pendingOrders.length, 0);
});

test("a bar that only touches the limit is not a fill", async () => {
  const { instance, trading } = makeSession();
  await place(instance, { order_type: "limit", side: "buy", quantity: 1, limit_price: 4990 });
  await instance._fillPendingOrders(bar(1060, 5010, 5020, 4990, 5000));

  assert.equal(trading.fills.length, 0);
  assert.equal(trading.pendingOrders.length, 1);
});

test("a bar opening through the buy limit fills at the open, better than the limit", async () => {
  const { instance, trading } = makeSession();
  await place(instance, { order_type: "limit", side: "buy", quantity: 1, limit_price: 4990 });
  await instance._fillPendingOrders(bar(1060, 4980, 4995, 4975, 4990));

  assert.equal(trading.fills[0].fill_price, 4980);
});

test("sell limit mirrors the buy rules", async () => {
  const { instance, trading } = makeSession();
  await place(instance, { order_type: "limit", side: "sell", quantity: 1, limit_price: 5020 });
  await instance._fillPendingOrders(bar(1060, 5010, 5020, 5000, 5015));
  assert.equal(trading.fills.length, 0, "touching the sell limit is not a fill");

  await instance._fillPendingOrders(bar(1120, 5010, 5030, 5005, 5025));
  assert.equal(trading.fills.length, 1);
  assert.equal(trading.fills[0].fill_price, 5020);
});

test("limit fills carry no slippage", async () => {
  const { instance, trading } = makeSession();
  await place(instance, { order_type: "limit", side: "buy", quantity: 4, limit_price: 4990 });
  await instance._fillPendingOrders(bar(1060, 5010, 5020, 4985, 5000));

  assert.equal(trading.slippage, 0);
  assert.equal(trading.commission, 0.62 * 4);
});

test("a working limit survives bars that do not reach it", async () => {
  const { instance, trading } = makeSession();
  await place(instance, { order_type: "limit", side: "buy", quantity: 1, limit_price: 4990 });
  for (const t of [1060, 1120, 1180]) {
    await instance._fillPendingOrders(bar(t, 5010, 5020, 5000, 5015));
  }
  assert.equal(trading.pendingOrders.length, 1);
  assert.equal(trading.fills.length, 0);

  await instance._fillPendingOrders(bar(1240, 5000, 5005, 4980, 4985));
  assert.equal(trading.fills.length, 1);
  assert.equal(trading.fills[0].filled_at_ts, 1240);
});

// --- stop -------------------------------------------------------------------

test("buy stop triggers on a touch and fills at the stop price", async () => {
  const { instance, trading } = makeSession();
  await place(instance, { order_type: "stop", side: "buy", quantity: 1, stop_price: 5020 });
  await instance._fillPendingOrders(bar(1060, 5010, 5020, 5005, 5018));

  assert.equal(trading.fills.length, 1);
  assert.equal(trading.fills[0].fill_price, 5020);
  assert.equal(trading.fills[0].order_type, "stop");
});

test("a bar gapping through a buy stop fills at the open, worse than the stop", async () => {
  const { instance, trading } = makeSession();
  await place(instance, { order_type: "stop", side: "buy", quantity: 1, stop_price: 5020 });
  await instance._fillPendingOrders(bar(1060, 5035, 5040, 5030, 5038));

  assert.equal(trading.fills[0].fill_price, 5035);
});

test("a bar gapping through a sell stop fills at the open, worse than the stop", async () => {
  const { instance, trading } = makeSession();
  await place(instance, { order_type: "stop", side: "sell", quantity: 1, stop_price: 4980 });
  await instance._fillPendingOrders(bar(1060, 4960, 4970, 4950, 4955));

  assert.equal(trading.fills[0].fill_price, 4960);
});

test("triggered stops are charged slippage like any market order", async () => {
  const { instance, trading } = makeSession();
  await place(instance, { order_type: "stop", side: "buy", quantity: 2, stop_price: 5020 });
  await instance._fillPendingOrders(bar(1060, 5010, 5020, 5005, 5018));

  assert.equal(trading.slippage, 1.25 * 2);
});

// --- stop-limit -------------------------------------------------------------

test("a stop-limit does not fill on the bar that triggered it", async () => {
  const { instance, trading, broadcasts } = makeSession();
  await place(instance, {
    order_type: "stop_limit", side: "buy", quantity: 1, stop_price: 5020, limit_price: 5025,
  });
  await instance._fillPendingOrders(bar(1060, 5010, 5030, 5005, 5028));

  assert.equal(trading.fills.length, 0);
  assert.equal(trading.pendingOrders.length, 1);
  assert.equal(trading.pendingOrders[0].status, "triggered");
  assert.equal(trading.pendingOrders[0].triggered_at_ts, 1060);
  assert.ok(broadcasts.some((b) => b.type === "orders_triggered"));
});

test("a triggered stop-limit rests as a limit and fills on a later bar", async () => {
  const { instance, trading } = makeSession();
  await place(instance, {
    order_type: "stop_limit", side: "buy", quantity: 1, stop_price: 5020, limit_price: 5025,
  });
  await instance._fillPendingOrders(bar(1060, 5010, 5030, 5005, 5028));
  await instance._fillPendingOrders(bar(1120, 5040, 5045, 5035, 5042));
  assert.equal(trading.fills.length, 0, "limit unreachable, order still working");

  await instance._fillPendingOrders(bar(1180, 5030, 5035, 5020, 5024));
  assert.equal(trading.fills.length, 1);
  assert.equal(trading.fills[0].fill_price, 5025);
  assert.equal(trading.fills[0].order_type, "stop_limit");
  assert.equal(trading.slippage, 0, "a stop-limit fills as a limit, so it does not slip");
});

// --- ordering and validation ------------------------------------------------

test("stops are applied before limits inside one bar", async () => {
  const { instance, trading } = makeSession();
  await place(instance, { order_type: "limit", side: "sell", quantity: 1, limit_price: 5030 });
  await place(instance, { order_type: "stop", side: "buy", quantity: 1, stop_price: 5020 });
  await instance._fillPendingOrders(bar(1060, 5010, 5040, 5005, 5035));

  assert.deepEqual(trading.fills.map((f) => f.order_type), ["stop", "limit"]);
  assert.equal(trading.positionQty, 0, "bought on the stop, sold on the limit, back to flat");
});

test("orders placed at the same rank keep their placement sequence", async () => {
  const { instance, trading } = makeSession();
  await place(instance, { order_type: "limit", side: "buy", quantity: 1, limit_price: 4990 });
  await place(instance, { order_type: "limit", side: "buy", quantity: 1, limit_price: 4995 });
  await instance._fillPendingOrders(bar(1060, 5010, 5020, 4980, 4985));

  assert.deepEqual(trading.fills.map((f) => f.fill_price), [4990, 4995]);
});

test("prices off the tick grid are rejected", async () => {
  const { instance } = makeSession();
  await assert.rejects(
    () => instance.placeOrder({ order_type: "limit", side: "buy", quantity: 1, limit_price: 4990.1 }),
    /multiple of 0.25/,
  );
});

test("a stop already through the market is rejected", async () => {
  const { instance } = makeSession({ lastPrice: 5000 });
  await assert.rejects(
    () => instance.placeOrder({ order_type: "stop", side: "buy", quantity: 1, stop_price: 4990 }),
    /buy stop must be above/,
  );
  await assert.rejects(
    () => instance.placeOrder({ order_type: "stop", side: "sell", quantity: 1, stop_price: 5010 }),
    /sell stop must be below/,
  );
});

test("unknown order types are rejected", async () => {
  const { instance } = makeSession();
  await assert.rejects(
    () => instance.placeOrder({ order_type: "trailing_stop", side: "buy", quantity: 1 }),
    /Unsupported order type/,
  );
});

test("a limit without a price is rejected", async () => {
  const { instance } = makeSession();
  await assert.rejects(
    () => instance.placeOrder({ order_type: "limit", side: "buy", quantity: 1 }),
    /Limit price must be a positive price/,
  );
});

test("cancel removes a working order and leaves the rest alone", async () => {
  const { instance, trading, broadcasts } = makeSession();
  const first = await place(instance, { order_type: "limit", side: "buy", quantity: 1, limit_price: 4990 });
  const second = await place(instance, { order_type: "limit", side: "buy", quantity: 1, limit_price: 4980 });

  await instance.cancelOrder(first.id);
  assert.deepEqual(trading.pendingOrders.map((o) => o.id), [second.id]);
  assert.ok(broadcasts.some((b) => b.type === "order_cancelled"));

  await assert.rejects(() => instance.cancelOrder("no-such-order"), /No working order/);
});

test("an order legacy-persisted without a type is still treated as a market order", async () => {
  const { instance, trading } = makeSession();
  trading.pendingOrders.push({ id: "legacy", side: "buy", quantity: 1, requested_at_ts: 1000 });
  await instance._fillPendingOrders(bar(1060, 5010, 5020, 5000, 5015));

  assert.equal(trading.fills.length, 1);
  assert.equal(trading.fills[0].fill_price, 5010);
  assert.equal(trading.fills[0].order_type, "market");
});

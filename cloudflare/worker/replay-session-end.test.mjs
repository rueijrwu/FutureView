// Auto-flatten at the daily session end: forces a market close on any open
// position and cancels resting orders (including bracket legs) at the CME
// 18:00 ET session roll, mirroring a real day-trading account that cannot
// carry risk through the close. Selectable per session (default on) via
// session.autoFlattenAtSessionEnd / the "set_auto_flatten" ws command.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

let coreSource = await fs.readFile(new URL("./replay-session-core.js", import.meta.url), "utf8");
coreSource = coreSource.replace(
  'import { DurableObject } from "cloudflare:workers";',
  "class DurableObject {}",
);
const coreModuleUrl = `data:text/javascript;base64,${Buffer.from(coreSource).toString("base64")}`;
const { ReplaySession: CoreReplaySession } = await import(coreModuleUrl);

let releaseSource = await fs.readFile(new URL("./replay-session.js", import.meta.url), "utf8");
releaseSource = releaseSource.replace("./replay-session-core.js", coreModuleUrl);
const releaseModuleUrl = `data:text/javascript;base64,${Buffer.from(releaseSource).toString("base64")}`;
const { ReplaySession } = await import(releaseModuleUrl);

// EDT: 18:00 ET session roll is 22:00 UTC. 2026-09-16 has no DST edge nearby.
const sec = (iso) => Math.floor(Date.parse(iso) / 1000);
const DAY1_LAST = sec("2026-09-16T17:59:00-04:00"); // last minute of day 1's session
const DAY2_ROLL = sec("2026-09-16T18:00:00-04:00"); // first bar of day 2's session
const DAY2_NEXT = sec("2026-09-16T18:01:00-04:00");

function bar(t, o, h, l, c) {
  return { t, o, h, l, c, v: 100 };
}

function makeCoreSession({ positionQty = 0, avgPrice = 0, pendingOrders = [], lastPrice = 5000 } = {}) {
  const instance = Object.create(CoreReplaySession.prototype);
  const trading = {
    positionQty,
    avgPrice,
    realizedPnl: 0,
    commission: 0,
    slippage: 0,
    pendingOrders,
    fills: [],
    nextSequence: 1,
    nextOrderSequence: 1,
    lastPrice,
    lastBarTs: DAY1_LAST,
  };
  instance.session = {
    id: "sess-1",
    userId: 1,
    product: "MES",
    contract: "MESZ6",
    state: "PAUSED",
    barIndex: 0,
    trading,
    autoFlattenAtSessionEnd: true,
    currentSessionDate: "2026-09-16",
  };
  instance.env = {};
  instance.ctx = { storage: { put: async () => {} } };
  const broadcasts = [];
  instance._broadcast = (payload) => broadcasts.push(payload);
  return { instance, trading, broadcasts };
}

// --- _forceCloseSessionEnd ----------------------------------------------------

test("force-close flattens a long position at the given close price", async () => {
  const { instance, trading, broadcasts } = makeCoreSession({ positionQty: 4, avgPrice: 5000, lastPrice: 5012 });
  await instance._forceCloseSessionEnd(5012, DAY1_LAST);

  assert.equal(trading.positionQty, 0);
  assert.equal(trading.fills.length, 1);
  assert.equal(trading.fills[0].side, "sell");
  assert.equal(trading.fills[0].fill_price, 5012);
  assert.equal(trading.realizedPnl, (5012 - 5000) * 4 * 5);
  // Same commission/slippage convention as any other market fill.
  assert.equal(trading.commission, 0.62 * 4);
  assert.equal(trading.slippage, 1.25 * 4);
  assert.equal(broadcasts.at(-1).type, "session_end_flatten");
  assert.equal(broadcasts.at(-1).fill.side, "sell");
});

test("force-close flattens a short position by buying back", async () => {
  const { instance, trading } = makeCoreSession({ positionQty: -2, avgPrice: 5000, lastPrice: 4990 });
  await instance._forceCloseSessionEnd(4990, DAY1_LAST);

  assert.equal(trading.positionQty, 0);
  assert.equal(trading.fills[0].side, "buy");
  assert.equal(trading.realizedPnl, (5000 - 4990) * 2 * 5);
});

test("force-close cancels every resting order, entry and bracket legs alike", async () => {
  const pendingOrders = [
    { id: "o1", status: "working", side: "buy", quantity: 1, type: "limit", limit_price: 4990 },
    { id: "o2", status: "working", side: "sell", quantity: 1, type: "limit", limit_price: 5100, oco_group: "b1", bracket_role: "take_profit" },
    { id: "o3", status: "working", side: "sell", quantity: 1, type: "stop", stop_price: 4900, oco_group: "b1", bracket_role: "stop_loss" },
  ];
  const { instance, trading, broadcasts } = makeCoreSession({ pendingOrders, positionQty: 0 });
  await instance._forceCloseSessionEnd(5000, DAY1_LAST);

  assert.equal(trading.pendingOrders.length, 0);
  const cancelled = broadcasts.at(-1);
  assert.equal(cancelled.type, "session_end_flatten");
  assert.equal(cancelled.cancelled_orders.length, 3);
  assert.ok(cancelled.cancelled_orders.every((o) => o.status === "cancelled"));
  assert.equal(cancelled.fill, null, "flat account has nothing to close");
});

test("force-close is a no-op broadcast-wise when flat with nothing resting", async () => {
  const { instance, broadcasts } = makeCoreSession({ positionQty: 0, pendingOrders: [] });
  await instance._forceCloseSessionEnd(5000, DAY1_LAST);
  assert.equal(broadcasts.length, 0);
});

// --- _maybeFlattenForSessionEnd (boundary detection) --------------------------

test("crossing the 18:00 ET session roll triggers a flatten when enabled", async () => {
  const { instance, trading } = makeCoreSession({ positionQty: 3, avgPrice: 5000, lastPrice: 5005 });
  trading.lastBarTs = DAY1_LAST;
  await instance._maybeFlattenForSessionEnd(bar(DAY2_ROLL, 5010, 5015, 5005, 5010));

  assert.equal(trading.positionQty, 0, "position force-closed at the outgoing session's last price");
  assert.equal(trading.fills[0].fill_price, 5005, "closed at the prior bar's lastPrice, not the new session's bar");
  assert.equal(instance.session.currentSessionDate, "2026-09-17");
});

test("staying inside the same session never force-closes", async () => {
  const { instance, trading } = makeCoreSession({ positionQty: 3, avgPrice: 5000, lastPrice: 5005 });
  await instance._maybeFlattenForSessionEnd(bar(DAY1_LAST, 5006, 5008, 5004, 5005));

  assert.equal(trading.positionQty, 3);
  assert.equal(trading.fills.length, 0);
  assert.equal(instance.session.currentSessionDate, "2026-09-16");
});

test("auto-flatten disabled carries the position through the roll", async () => {
  const { instance, trading } = makeCoreSession({ positionQty: 3, avgPrice: 5000, lastPrice: 5005 });
  instance.session.autoFlattenAtSessionEnd = false;
  await instance._maybeFlattenForSessionEnd(bar(DAY2_ROLL, 5010, 5015, 5005, 5010));

  assert.equal(trading.positionQty, 3, "no forced close while the toggle is off");
  assert.equal(trading.fills.length, 0);
  assert.equal(instance.session.currentSessionDate, "2026-09-17", "the tracker still advances so re-enabling only affects the next boundary");
});

test("setAutoFlatten toggles the flag and broadcasts it", async () => {
  const { instance, broadcasts } = makeCoreSession();
  await instance.setAutoFlatten(false);
  assert.equal(instance.session.autoFlattenAtSessionEnd, false);
  assert.deepEqual(broadcasts.at(-1), { type: "auto_flatten_changed", enabled: false });

  await instance.setAutoFlatten(true);
  assert.equal(instance.session.autoFlattenAtSessionEnd, true);
});

// --- integration through _release / _releaseUntilBefore -----------------------

function makeReleaseHarness({ bars, autoFlattenAtSessionEnd = true, positionQty = 3, avgPrice = 5000 }) {
  const instance = Object.create(ReplaySession.prototype);
  const contract = { contract: "MESZ6", shards: [{ key: "s0" }] };
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
    lastPrice: bars[0].c,
    lastBarTs: bars[0].t,
  };
  instance.manifest = { contracts: { MESZ6: contract } };
  instance.session = {
    id: "sess-1",
    contract: "MESZ6",
    shardIndex: 0,
    barIndex: 0,
    state: "PAUSED",
    trading,
    autoFlattenAtSessionEnd,
    currentSessionDate: "2026-09-16",
  };
  instance.shard = bars;
  instance.shardKey = "s0";
  instance.env = {};
  instance.ctx = { storage: { put: async () => {} } };
  instance._manifest = async () => instance.manifest;
  instance._trading = () => trading;
  instance._loadShard = async () => instance.shard;
  instance._loadShardForContract = async () => null;
  instance._broadcast = () => {};
  return { instance, trading };
}

test("_release force-closes exactly on the bar that crosses the session roll", async () => {
  const bars = [
    bar(DAY1_LAST - 60, 5000, 5005, 4995, 5001),
    bar(DAY1_LAST, 5001, 5006, 4996, 5005),
    bar(DAY2_ROLL, 5010, 5015, 5005, 5012),
    bar(DAY2_NEXT, 5012, 5018, 5008, 5015),
  ];
  const { instance, trading } = makeReleaseHarness({ bars });

  const released = await instance._release(3);

  assert.deepEqual(released.map((b) => b.t), [DAY1_LAST, DAY2_ROLL, DAY2_NEXT]);
  assert.equal(trading.positionQty, 0, "flattened on the roll bar, using the prior bar's close");
  assert.equal(trading.fills[0].fill_price, 5005);
  assert.equal(trading.fills[0].filled_at_ts, DAY1_LAST);
});

test("_release leaves the position open across the roll when disabled", async () => {
  const bars = [
    bar(DAY1_LAST, 5001, 5006, 4996, 5005),
    bar(DAY2_ROLL, 5010, 5015, 5005, 5012),
  ];
  const { instance, trading } = makeReleaseHarness({ bars, autoFlattenAtSessionEnd: false });

  await instance._release(2);

  assert.equal(trading.positionQty, 3);
  assert.equal(trading.fills.length, 0);
});

test("_releaseUntilBefore also force-closes on the session roll", async () => {
  const bars = [
    bar(DAY1_LAST - 60, 5000, 5005, 4995, 5001),
    bar(DAY1_LAST, 5001, 5006, 4996, 5005),
    bar(DAY2_ROLL, 5010, 5015, 5005, 5012),
    bar(DAY2_NEXT, 5012, 5018, 5008, 5015),
  ];
  const { instance, trading } = makeReleaseHarness({ bars });

  const released = await instance._releaseUntilBefore(DAY2_NEXT + 1);

  assert.deepEqual(released.map((b) => b.t), [DAY1_LAST, DAY2_ROLL, DAY2_NEXT]);
  assert.equal(trading.positionQty, 0);
  assert.equal(trading.fills[0].filled_at_ts, DAY1_LAST);
});

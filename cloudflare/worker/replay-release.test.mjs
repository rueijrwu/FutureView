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

function makeBar(t, price) {
  return { t, o: price, h: price + 1, l: price - 1, c: price + 0.25, v: 10 };
}

function makeHarness({ shards, barIndex = 0, pending = false }) {
  const instance = Object.create(ReplaySession.prototype);
  const contract = {
    contract: "MESZ6",
    shards: shards.map((_, index) => ({ key: `s${index}` })),
  };
  const trading = {
    positionQty: 0,
    avgPrice: 0,
    realizedPnl: 0,
    commission: 0,
    slippage: 0,
    pendingOrders: pending ? [{ id: "pending-order" }] : [],
    fills: [],
    nextSequence: 1,
    lastPrice: shards[0][barIndex]?.c ?? null,
  };

  instance.manifest = { contracts: { MESZ6: contract } };
  instance.session = {
    contract: "MESZ6",
    shardIndex: 0,
    barIndex,
    state: "PAUSED",
    trading,
  };
  instance.shard = shards[0];
  instance.shardKey = "s0";
  instance._manifest = async () => instance.manifest;
  instance._trading = () => trading;

  const metrics = { loaded: [], fillCalls: 0, fillBars: [] };
  instance._loadShard = async (index) => {
    metrics.loaded.push(index);
    instance.shard = shards[index] ?? null;
    instance.shardKey = instance.shard ? `s${index}` : null;
    return instance.shard;
  };

  instance._fillPendingOrders = async (bar) => {
    metrics.fillCalls += 1;
    if (!trading.pendingOrders.length) return;
    metrics.fillBars.push(bar.t);
    trading.pendingOrders.length = 0;
  };

  return { instance, trading, metrics };
}

test("release advances canonical bars in order without same-shard async churn", async () => {
  const bars = [makeBar(100, 10), makeBar(160, 11), makeBar(220, 12)];
  const { instance, trading, metrics } = makeHarness({ shards: [bars] });

  const released = await instance._release(2);

  assert.deepEqual(released.map((bar) => bar.t), [160, 220]);
  assert.equal(instance.session.shardIndex, 0);
  assert.equal(instance.session.barIndex, 2);
  assert.equal(trading.lastPrice, bars[2].c);
  assert.equal(instance.session.state, "PAUSED");
  assert.deepEqual(metrics.loaded, []);
  assert.equal(metrics.fillCalls, 0);
});

test("release crosses shard boundaries exactly once without skipping bars", async () => {
  const shard0 = [makeBar(100, 10), makeBar(160, 11)];
  const shard1 = [makeBar(220, 12), makeBar(280, 13)];
  const { instance, metrics } = makeHarness({ shards: [shard0, shard1] });

  const released = await instance._release(3);

  assert.deepEqual(released.map((bar) => bar.t), [160, 220, 280]);
  assert.equal(instance.session.shardIndex, 1);
  assert.equal(instance.session.barIndex, 1);
  assert.deepEqual(metrics.loaded, [1]);
});

test("pending orders fill once on the first newly released canonical bar", async () => {
  const bars = [makeBar(100, 10), makeBar(160, 11), makeBar(220, 12)];
  const { instance, trading, metrics } = makeHarness({ shards: [bars], pending: true });

  const released = await instance._release(2);

  assert.deepEqual(released.map((bar) => bar.t), [160, 220]);
  assert.deepEqual(metrics.fillBars, [160]);
  assert.equal(metrics.fillCalls, 1);
  assert.equal(trading.pendingOrders.length, 0);
});

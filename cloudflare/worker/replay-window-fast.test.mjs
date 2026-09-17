import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

let baselineSource = await fs.readFile(new URL("./replay-session-display.js", import.meta.url), "utf8");
baselineSource = baselineSource.replace(
  'import { ReplaySession as FrameReplaySession } from "./replay-session-frame.js";',
  "class FrameReplaySession {}",
);
const baselineUrl = `data:text/javascript;base64,${Buffer.from(baselineSource).toString("base64")}`;

let fastSource = await fs.readFile(new URL("./replay-session-display-fast.js", import.meta.url), "utf8");
fastSource = fastSource.replace("./replay-session-display.js", baselineUrl);
const fastUrl = `data:text/javascript;base64,${Buffer.from(fastSource).toString("base64")}`;
const { ReplaySession } = await import(fastUrl);

function harness(resolution = "5") {
  const instance = Object.create(ReplaySession.prototype);
  instance.displayResolution = resolution;
  instance.displayWindowIndex = -1;
  instance.displayWindows = new Map();
  instance.displayPrefetchAt = -Infinity;
  instance.displayPrefetchedIndex = -1;
  instance.displayNextCheckAt = -Infinity;

  const metas = [
    { key: "w0", first_time: 100, last_time: 199 },
    { key: "w1", first_time: 200, last_time: 299 },
    { key: "w2", first_time: 300, last_time: 399 },
  ];
  const bars = {
    0: [{ t: 100 }, { t: 130 }, { t: 160 }, { t: 190 }],
    1: [{ t: 200 }, { t: 230 }, { t: 260 }, { t: 290 }],
    2: [{ t: 300 }, { t: 330 }, { t: 360 }, { t: 390 }],
  };

  let inFlight = 0;
  let maxInFlight = 0;
  const calls = [];
  instance._displayShardMeta = async () => metas;
  instance._loadDisplayWindow = async (index) => {
    calls.push(index);
    inFlight += 1;
    maxInFlight = Math.max(maxInFlight, inFlight);
    await new Promise((resolve) => setTimeout(resolve, 8));
    inFlight -= 1;
    const meta = metas[index];
    return meta ? { index, meta, bars: bars[index] || [] } : null;
  };
  instance._trimDisplayWindows = () => {};

  return {
    instance,
    calls,
    maxInFlight: () => maxInFlight,
  };
}

test("5m display cache loads current and next windows concurrently", async () => {
  const { instance, calls, maxInFlight } = harness("5");

  await instance._ensureDisplayWindows(150);

  assert.deepEqual(calls, [0, 1]);
  assert.equal(maxInFlight(), 2);
  assert.equal(instance.displayWindowIndex, 0);
  assert.equal(instance.displayPrefetchAt, 160);
  assert.equal(instance.displayPrefetchedIndex, -1);
  assert.equal(instance.displayNextCheckAt, 160);
});

test("prefetching N+2 keeps the same threshold and edge policy", async () => {
  const { instance, calls, maxInFlight } = harness("5");

  await instance._ensureDisplayWindows(170);

  assert.deepEqual(calls, [0, 1, 2]);
  assert.equal(maxInFlight(), 2);
  assert.equal(instance.displayWindowIndex, 0);
  assert.equal(instance.displayPrefetchAt, 160);
  assert.equal(instance.displayPrefetchedIndex, 2);
  assert.equal(instance.displayNextCheckAt, 200);
});

test("1m cache keeps a single-window load", async () => {
  const { instance, calls, maxInFlight } = harness("1");

  await instance._ensureDisplayWindows(150);

  assert.deepEqual(calls, [0]);
  assert.equal(maxInFlight(), 1);
  assert.equal(instance.displayWindowIndex, 0);
  assert.equal(instance.displayNextCheckAt, 200);
});

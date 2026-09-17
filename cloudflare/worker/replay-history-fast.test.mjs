import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

let baselineSource = await fs.readFile(new URL("./replay-session-display.js", import.meta.url), "utf8");
baselineSource = baselineSource.replace(
  'import { ReplaySession as FrameReplaySession } from "./replay-session-frame.js";',
  "class FrameReplaySession {}",
);
const baselineUrl = `data:text/javascript;base64,${Buffer.from(baselineSource).toString("base64")}`;

const { ReplaySession: BaselineReplaySession } = await import(baselineUrl);

let fastSource = await fs.readFile(new URL("./replay-session-display-fast.js", import.meta.url), "utf8");
fastSource = fastSource.replace("./replay-session-display.js", baselineUrl);
const fastUrl = `data:text/javascript;base64,${Buffer.from(fastSource).toString("base64")}`;
const { ReplaySession } = await import(fastUrl);

function harness() {
  const instance = Object.create(ReplaySession.prototype);
  instance.displayResolution = "5";
  instance.historyRange = "3M";
  instance.displayWindowIndex = 7;
  instance.displayWindows = new Map([
    ["5:6", { index: 6 }],
    ["5:7", { index: 7 }],
  ]);
  instance.displayNextCheckAt = Infinity;

  const metas = Array.from({ length: 8 }, (_, index) => ({
    key: `w${index}`,
    first_time: index * 100,
    last_time: index * 100 + 99,
  }));
  instance._ensureDisplayWindows = async () => {};
  instance._displayShardMeta = async () => metas;

  let inFlight = 0;
  let maxInFlight = 0;
  const calls = [];
  instance._loadDisplayWindow = async (index, resolution) => {
    calls.push(index);
    inFlight += 1;
    maxInFlight = Math.max(maxInFlight, inFlight);
    await new Promise((resolve) => setTimeout(resolve, 8));
    inFlight -= 1;
    const value = { index, meta: metas[index], bars: [] };
    instance.displayWindows.set(`${resolution}:${index}`, value);
    return value;
  };

  return { instance, calls, maxInFlight: () => maxInFlight };
}

test("long history preloads missing windows with bounded concurrency", async () => {
  const { instance, calls, maxInFlight } = harness();

  await instance._preloadDisplayHistory(799, "5", "3M");

  assert.deepEqual(calls, [0, 1, 2, 3, 4, 5]);
  assert.equal(maxInFlight(), 4);
  for (let index = 0; index <= 7; index += 1) {
    assert.ok(instance.displayWindows.has(`5:${index}`));
  }
});

test("history preload skips windows that are already cached", async () => {
  const { instance, calls } = harness();
  instance.displayWindows.set("5:2", { index: 2 });
  instance.displayWindows.set("5:4", { index: 4 });

  await instance._preloadDisplayHistory(799, "5", "3M");

  assert.deepEqual(calls, [0, 1, 3, 5]);
});

test("preload is a no-op for a non-selected resolution", async () => {
  const { instance, calls } = harness();

  await instance._preloadDisplayHistory(799, "30", "3M");

  assert.deepEqual(calls, []);
});


test("causal history consumes preloaded windows without async loader calls", async () => {
  const instance = Object.create(BaselineReplaySession.prototype);
  instance.displayResolution = "1";
  instance.historyRange = "3M";
  instance.displayWindowIndex = 2;
  const metas = [
    { key: "w0", first_time: 0, last_time: 99 },
    { key: "w1", first_time: 100, last_time: 199 },
    { key: "w2", first_time: 200, last_time: 299 },
  ];
  instance.displayWindows = new Map([
    ["1:0", { index: 0, meta: metas[0], bars: [{ t: 10 }, { t: 90 }] }],
    ["1:1", { index: 1, meta: metas[1], bars: [{ t: 110 }, { t: 190 }] }],
    ["1:2", { index: 2, meta: metas[2], bars: [{ t: 210 }, { t: 290 }] }],
  ]);
  instance._ensureDisplayWindows = async () => {};
  instance._displayShardMeta = async () => metas;
  instance._trimDisplayWindows = () => {};
  let loaderCalls = 0;
  instance._loadDisplayWindow = async () => {
    loaderCalls += 1;
    throw new Error("preloaded window should not hit loader");
  };

  const bars = await instance._causalDisplayWindow(299, "1", "3M");

  assert.equal(loaderCalls, 0);
  assert.deepEqual(bars.map((bar) => bar.t), [10, 90, 110, 190, 210, 290]);
});

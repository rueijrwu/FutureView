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
const { ReplaySession: FastReplaySession } = await import(fastUrl);

test("duplicate display-window callers share one in-flight load", async () => {
  const instance = Object.create(FastReplaySession.prototype);
  instance.displayResolution = "5";
  instance.displayWindows = new Map();

  const original = BaselineReplaySession.prototype._loadDisplayWindow;
  let calls = 0;
  BaselineReplaySession.prototype._loadDisplayWindow = async function (index, resolution) {
    calls += 1;
    await new Promise((resolve) => setTimeout(resolve, 10));
    const value = { index, meta: { key: `w${index}` }, bars: [{ t: 100 }] };
    this.displayWindows.set(`${resolution}:${index}`, value);
    return value;
  };

  try {
    const [first, second] = await Promise.all([
      instance._loadDisplayWindow(2, "5"),
      instance._loadDisplayWindow(2, "5"),
    ]);
    assert.equal(calls, 1);
    assert.equal(first, second);
    assert.equal(instance._fvDisplayWindowLoads.size, 0);
  } finally {
    BaselineReplaySession.prototype._loadDisplayWindow = original;
  }
});

test("N+2 prefetch uses waitUntil instead of blocking the replay path", async () => {
  const instance = Object.create(FastReplaySession.prototype);
  instance.displayResolution = "5";
  instance.displayWindowIndex = -1;
  instance.displayPrefetchAt = -Infinity;
  instance.displayPrefetchedIndex = -1;
  instance.displayNextCheckAt = -Infinity;
  instance.displayWindows = new Map();

  const metas = [
    { key: "w0", first_time: 100, last_time: 199 },
    { key: "w1", first_time: 200, last_time: 299 },
    { key: "w2", first_time: 300, last_time: 399 },
  ];
  instance._displayShardMeta = async () => metas;
  instance._trimDisplayWindows = () => {};

  let releasePrefetch;
  const prefetchGate = new Promise((resolve) => { releasePrefetch = resolve; });
  let prefetchResolved = false;
  instance._loadDisplayWindow = async (index) => {
    if (index === 2) {
      await prefetchGate;
      prefetchResolved = true;
    }
    const meta = metas[index];
    return meta ? {
      index,
      meta,
      bars: index === 0 ? [{ t: 100 }, { t: 130 }, { t: 160 }, { t: 190 }] : [],
    } : null;
  };

  const waits = [];
  instance.ctx = { waitUntil(promise) { waits.push(promise); } };

  await instance._ensureDisplayWindows(170);

  assert.equal(prefetchResolved, false);
  assert.equal(instance.displayPrefetchedIndex, 2);
  assert.equal(instance.displayNextCheckAt, 200);
  assert.equal(waits.length, 1);

  releasePrefetch();
  await waits[0];
  assert.equal(prefetchResolved, true);
});

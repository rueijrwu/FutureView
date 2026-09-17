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

const sec = (iso) => Math.floor(Date.parse(iso) / 1000);

function minuteBars(start, count, priceBase = 100) {
  const first = sec(start);
  return Array.from({ length: count }, (_, index) => ({
    t: first + index * 60,
    o: priceBase + index,
    h: priceBase + index + 1.5,
    l: priceBase + index - 0.75,
    c: priceBase + index + 0.5,
    v: (index % 5) + 1,
  }));
}

function aggregateHarness(Type, resolution, warmup) {
  const instance = Object.create(Type.prototype);
  const current = warmup.at(-1);
  instance.displayResolution = resolution;
  instance.displayAggregate = null;
  instance.displayAggregateResolution = null;
  instance.displayAggregateCursor = null;
  instance.session = { shardIndex: 0, barIndex: warmup.length - 1 };
  instance._ensureReplayCursor = async () => current;
  instance._warmupBars = async () => warmup;
  return instance;
}

test("fast 30m active reconstruction matches baseline exactly", async () => {
  const warmup = minuteBars("2026-09-17T09:00:00-04:00", 78, 100);
  const baseline = aggregateHarness(BaselineReplaySession, "30", warmup);
  const fast = aggregateHarness(FastReplaySession, "30", warmup);

  await baseline._ensureDisplayAggregate();
  await fast._ensureDisplayAggregate();

  assert.deepEqual(fast.displayAggregate, baseline.displayAggregate);
  assert.equal(fast.displayAggregateResolution, baseline.displayAggregateResolution);
  assert.equal(fast.displayAggregateCursor, baseline.displayAggregateCursor);
  assert.equal(fast.displayAggregate.t, sec("2026-09-17T10:00:00-04:00"));
});

test("fast 4h active reconstruction matches baseline across prior buckets", async () => {
  const warmup = minuteBars("2026-09-17T18:00:00-04:00", 370, 200);
  const baseline = aggregateHarness(BaselineReplaySession, "240", warmup);
  const fast = aggregateHarness(FastReplaySession, "240", warmup);

  await baseline._ensureDisplayAggregate();
  await fast._ensureDisplayAggregate();

  assert.deepEqual(fast.displayAggregate, baseline.displayAggregate);
  assert.equal(fast.displayAggregate.t, sec("2026-09-17T22:00:00-04:00"));
});

test("intraday reconstruction uses one timezone-aware bucket seed", async () => {
  const warmup = minuteBars("2026-09-17T09:00:00-04:00", 78, 100);
  const fast = aggregateHarness(FastReplaySession, "30", warmup);

  const original = BaselineReplaySession.prototype._consumeCanonicalBars;
  let calls = 0;
  BaselineReplaySession.prototype._consumeCanonicalBars = function (...args) {
    calls += 1;
    return original.apply(this, args);
  };
  try {
    await fast._ensureDisplayAggregate();
    assert.equal(calls, 1);
  } finally {
    BaselineReplaySession.prototype._consumeCanonicalBars = original;
  }
});

test("fast 1D active reconstruction matches baseline from 18:00 ET session open", async () => {
  const warmup = minuteBars("2026-09-16T18:00:00-04:00", 960, 100);
  const baseline = aggregateHarness(BaselineReplaySession, "1D", warmup);
  const fast = aggregateHarness(FastReplaySession, "1D", warmup);

  await baseline._ensureDisplayAggregate();
  await fast._ensureDisplayAggregate();

  assert.deepEqual(fast.displayAggregate, baseline.displayAggregate);
  assert.equal(fast.displayAggregateResolution, "1D");
  assert.equal(fast.displayAggregateCursor, warmup.at(-1).t);
  assert.equal(fast.displayAggregate.t, sec("2026-09-17T00:00:00-04:00"));
  assert.equal(fast.displayAggregate.o, warmup[0].o);
});

test("fast 1D active reconstruction matches baseline after spring DST weekend", async () => {
  const warmup = minuteBars("2026-03-08T18:00:00-04:00", 900, 200);
  const baseline = aggregateHarness(BaselineReplaySession, "1D", warmup);
  const fast = aggregateHarness(FastReplaySession, "1D", warmup);

  await baseline._ensureDisplayAggregate();
  await fast._ensureDisplayAggregate();

  assert.deepEqual(fast.displayAggregate, baseline.displayAggregate);
  assert.equal(fast.displayAggregate.t, sec("2026-03-09T00:00:00-04:00"));
});

test("1D reconstruction uses one timezone-aware daily seed", async () => {
  const warmup = minuteBars("2026-09-16T18:00:00-04:00", 960, 100);
  const fast = aggregateHarness(FastReplaySession, "1D", warmup);

  const original = BaselineReplaySession.prototype._consumeCanonicalBars;
  let calls = 0;
  BaselineReplaySession.prototype._consumeCanonicalBars = function (...args) {
    calls += 1;
    return original.apply(this, args);
  };
  try {
    await fast._ensureDisplayAggregate();
    assert.equal(calls, 1);
  } finally {
    BaselineReplaySession.prototype._consumeCanonicalBars = original;
  }
});

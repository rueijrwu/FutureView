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

function barAt(t, price) {
  return {
    t: Number(t),
    o: price,
    h: price + 1.25,
    l: price - 0.75,
    c: price + 0.5,
    v: (price % 7) + 1,
  };
}

function minuteBars(start, count, priceBase = 100) {
  const first = typeof start === "number" ? start : sec(start);
  return Array.from({ length: count }, (_, index) => barAt(first + index * 60, priceBase + index));
}

function harness(Type) {
  const instance = Object.create(Type.prototype);
  instance.displayAggregate = null;
  instance.displayAggregateResolution = null;
  instance.displayAggregateCursor = null;
  return instance;
}

function run(Type, resolution, bars) {
  const instance = harness(Type);
  const completed = instance._consumeCanonicalBars(bars, resolution);
  return {
    completed,
    active: instance.displayAggregate ? { ...instance.displayAggregate } : null,
    activeResolution: instance.displayAggregateResolution,
    cursor: instance.displayAggregateCursor,
  };
}

function assertEquivalent(resolution, bars) {
  assert.deepEqual(
    run(FastReplaySession, resolution, bars),
    run(BaselineReplaySession, resolution, bars),
  );
}

function stepHarness(startIso, minutes, currentOffset, timeframe = "5") {
  const bars = minuteBars(startIso, minutes, 100);
  const instance = harness(FastReplaySession);
  instance.displayResolution = timeframe;
  instance.historyRange = "5D";
  instance.shard = bars;
  instance.shardKey = "s0";
  instance.manifest = { contracts: { MESZ6: { shards: [{ key: "s0", first_time: bars[0].t, last_time: bars.at(-1).t }] } } };
  instance.session = {
    contract: "MESZ6",
    shardIndex: 0,
    barIndex: currentOffset,
    state: "PAUSED",
    cursorTs: bars[currentOffset].t,
  };
  instance._consumeCanonicalBars(bars.slice(0, currentOffset + 1), timeframe);
  instance._ensureReplayCursor = async () => bars[instance.session.barIndex];
  instance._ensureDisplayAggregate = async () => {};
  instance._persist = async () => {};
  instance.snapshot = () => ({ type: "session_snapshot", cursor: instance.session.cursorTs });

  const releaseCounts = [];
  instance._release = async (count) => {
    releaseCounts.push(count);
    const start = instance.session.barIndex + 1;
    const released = bars.slice(start, start + count);
    instance.session.barIndex += released.length;
    return released;
  };

  const displayBroadcasts = [];
  instance._broadcastDisplayBars = (shown, resolution) => displayBroadcasts.push({ shown, resolution });
  const snapshots = [];
  instance._broadcast = (payload) => snapshots.push(payload);
  return { instance, bars, releaseCounts, displayBroadcasts, snapshots };
}

test("fast 5m aggregation is identical across many frame transitions", () => {
  assertEquivalent("5", minuteBars("2026-09-17T09:30:00-04:00", 180));
});

test("fast 4h aggregation is identical across the 17:00-18:00 ET session break", () => {
  const beforeBreak = minuteBars("2026-09-17T13:00:00-04:00", 240, 100);
  const afterBreak = minuteBars("2026-09-17T18:00:00-04:00", 360, 400);
  assertEquivalent("240", [...beforeBreak, ...afterBreak]);
});

test("fast daily aggregation is identical across the 18:00 ET trading-day roll", () => {
  const first = minuteBars("2026-09-17T16:45:00-04:00", 15, 100);
  const second = minuteBars("2026-09-17T18:00:00-04:00", 30, 200);
  const third = minuteBars("2026-09-18T17:45:00-04:00", 15, 300);
  const fourth = minuteBars("2026-09-18T18:00:00-04:00", 30, 400);
  assertEquivalent("1D", [...first, ...second, ...third, ...fourth]);
});

test("fast path falls back correctly across the spring DST weekend", () => {
  const bars = [
    ...minuteBars("2026-03-06T16:55:00-05:00", 5, 100),
    ...minuteBars("2026-03-08T18:00:00-04:00", 10, 200),
  ];
  assertEquivalent("30", bars);
});

test("normal 5m playback delegates to timezone-aware baseline only for initial seeding", () => {
  const original = BaselineReplaySession.prototype._consumeCanonicalBars;
  let baselineCalls = 0;
  BaselineReplaySession.prototype._consumeCanonicalBars = function (...args) {
    baselineCalls += 1;
    return original.apply(this, args);
  };
  try {
    const instance = harness(FastReplaySession);
    instance._consumeCanonicalBars(minuteBars("2026-09-17T09:30:00-04:00", 180), "5");
    assert.equal(baselineCalls, 1);
  } finally {
    BaselineReplaySession.prototype._consumeCanonicalBars = original;
  }
});

test("5m Next from a completed frame advances one full selected frame in one release", async () => {
  const { instance, bars, releaseCounts, displayBroadcasts } = stepHarness(
    "2026-09-17T10:15:00-04:00",
    12,
    4,
    "5",
  );

  await instance.stepFrame("5");

  assert.deepEqual(releaseCounts, [5]);
  assert.equal(instance.session.barIndex, 9);
  assert.equal(instance.session.cursorTs, bars[9].t);
  assert.equal(displayBroadcasts.length, 1);
  assert.equal(displayBroadcasts[0].resolution, "5");
  assert.equal(displayBroadcasts[0].shown[0].t, sec("2026-09-17T10:20:00-04:00"));
  assert.equal(displayBroadcasts[0].shown[0].c, bars[9].c);
});

test("5m Next from mid-frame completes only the current selected frame in one release", async () => {
  const { instance, bars, releaseCounts, displayBroadcasts } = stepHarness(
    "2026-09-17T10:15:00-04:00",
    12,
    2,
    "5",
  );

  await instance.stepFrame("5");

  assert.deepEqual(releaseCounts, [2]);
  assert.equal(instance.session.barIndex, 4);
  assert.equal(instance.session.cursorTs, bars[4].t);
  assert.equal(displayBroadcasts[0].shown[0].t, sec("2026-09-17T10:15:00-04:00"));
  assert.equal(displayBroadcasts[0].shown[0].c, bars[4].c);
});

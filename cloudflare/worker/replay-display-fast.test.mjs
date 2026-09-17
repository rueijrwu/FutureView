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

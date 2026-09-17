import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

let source = await fs.readFile(new URL("./replay-session-display.js", import.meta.url), "utf8");
source = source.replace(
  'import { ReplaySession as FrameReplaySession } from "./replay-session-frame.js";',
  "class FrameReplaySession {}",
);
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { ReplaySession } = await import(moduleUrl);

const sec = (iso) => Math.floor(Date.parse(iso) / 1000);

function bar(iso, price, volume = 1) {
  const t = sec(iso);
  return { t, o: price, h: price + 1, l: price - 1, c: price + 0.5, v: volume };
}

function harness() {
  const instance = Object.create(ReplaySession.prototype);
  instance.displayAggregate = null;
  instance.displayAggregateResolution = null;
  instance.displayAggregateCursor = null;
  return instance;
}

test("5m aggregation emits one completed selected-frame bar", () => {
  const instance = harness();
  const raw = [
    bar("2026-09-17T10:15:00-04:00", 100, 1),
    bar("2026-09-17T10:16:00-04:00", 101, 2),
    bar("2026-09-17T10:17:00-04:00", 99, 3),
    bar("2026-09-17T10:18:00-04:00", 102, 4),
    bar("2026-09-17T10:19:00-04:00", 103, 5),
    bar("2026-09-17T10:20:00-04:00", 104, 6),
  ];

  const completed = instance._consumeCanonicalBars(raw, "5");

  assert.equal(completed.length, 1);
  assert.deepEqual(completed[0], {
    t: sec("2026-09-17T10:15:00-04:00"),
    o: 100,
    h: 104,
    l: 98,
    c: 103.5,
    v: 15,
    display_resolution: "5",
  });
  assert.equal(instance.displayAggregate.t, sec("2026-09-17T10:20:00-04:00"));
  assert.equal(instance.displayAggregateCursor, sec("2026-09-17T10:20:00-04:00"));
});

test("4h frames are anchored to the 18:00 ET futures session", () => {
  const instance = harness();
  const raw = [
    bar("2026-09-17T21:59:00-04:00", 100),
    bar("2026-09-17T22:00:00-04:00", 101),
  ];

  const completed = instance._consumeCanonicalBars(raw, "240");

  assert.equal(completed.length, 1);
  assert.equal(completed[0].t, sec("2026-09-17T18:00:00-04:00"));
  assert.equal(instance.displayAggregate.t, sec("2026-09-17T22:00:00-04:00"));
});

test("daily frames roll at 18:00 ET and use trading-day midnight ET", () => {
  const instance = harness();
  const raw = [
    bar("2026-09-17T17:59:00-04:00", 100),
    bar("2026-09-17T18:00:00-04:00", 101),
  ];

  const completed = instance._consumeCanonicalBars(raw, "1D");

  assert.equal(completed.length, 1);
  assert.equal(completed[0].t, sec("2026-09-17T00:00:00-04:00"));
  assert.equal(instance.displayAggregate.t, sec("2026-09-18T00:00:00-04:00"));
});

test("daily trading-day stamps respect EST offset", () => {
  const instance = harness();
  const raw = [
    bar("2026-12-10T17:59:00-05:00", 100),
    bar("2026-12-10T18:00:00-05:00", 101),
  ];

  const completed = instance._consumeCanonicalBars(raw, "1D");

  assert.equal(completed[0].t, sec("2026-12-10T00:00:00-05:00"));
  assert.equal(instance.displayAggregate.t, sec("2026-12-11T00:00:00-05:00"));
});

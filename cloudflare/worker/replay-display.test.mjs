import assert from "node:assert/strict";
import test from "node:test";

import {
  consumeDisplayBars,
  finalizeDisplayBar,
  newDisplayAggregate,
} from "./replay-display.js";

const ts = (iso) => Math.floor(Date.parse(iso) / 1000);
const bar = (iso, price) => ({
  t: ts(iso),
  o: price,
  h: price + 1,
  l: price - 1,
  c: price + 0.5,
  v: 10,
});

test("5m frame completes at its final canonical minute without waiting for 10:20", () => {
  const initial = [
    bar("2024-06-10T14:15:00Z", 100),
    bar("2024-06-10T14:16:00Z", 101),
    bar("2024-06-10T14:17:00Z", 102),
  ];
  let aggregate = newDisplayAggregate(initial[0], "5");
  for (const item of initial.slice(1)) {
    aggregate.h = Math.max(aggregate.h, item.h);
    aggregate.l = Math.min(aggregate.l, item.l);
    aggregate.c = item.c;
    aggregate.v += item.v;
  }
  let state = {
    aggregate,
    resolution: "5",
    publishedStamp: null,
    cursor: initial.at(-1).t,
  };

  const consumed = consumeDisplayBars(state, [
    bar("2024-06-10T14:18:00Z", 103),
    bar("2024-06-10T14:19:00Z", 104),
  ], "5");
  state = consumed.state;
  assert.equal(consumed.completed.length, 0);
  assert.equal(state.cursor, ts("2024-06-10T14:19:00Z"));

  const finalized = finalizeDisplayBar(state, bar("2024-06-10T14:20:00Z", 105), "5");
  assert.equal(finalized.completed.length, 1);
  assert.equal(finalized.completed[0].t, ts("2024-06-10T14:15:00Z"));
  assert.equal(finalized.completed[0].display_resolution, "5");
  assert.equal(finalized.state.cursor, ts("2024-06-10T14:19:00Z"));
});

test("the following Next frame is 10:20 through 10:24, not a 1m display sequence", () => {
  let state = {
    aggregate: newDisplayAggregate(bar("2024-06-10T14:15:00Z", 100), "5"),
    resolution: "5",
    publishedStamp: ts("2024-06-10T14:15:00Z"),
    cursor: ts("2024-06-10T14:19:00Z"),
  };

  const released = [20, 21, 22, 23, 24].map((minute, i) =>
    bar(`2024-06-10T14:${minute}:00Z`, 110 + i)
  );
  const consumed = consumeDisplayBars(state, released, "5");
  state = consumed.state;
  assert.equal(consumed.completed.length, 0);
  assert.equal(state.aggregate.t, ts("2024-06-10T14:20:00Z"));
  assert.equal(state.cursor, ts("2024-06-10T14:24:00Z"));

  const finalized = finalizeDisplayBar(state, bar("2024-06-10T14:25:00Z", 120), "5");
  assert.deepEqual(finalized.completed.map((x) => x.t), [ts("2024-06-10T14:20:00Z")]);
});

test("1m mode passes canonical bars through one-for-one", () => {
  const raw = [
    bar("2024-06-10T14:15:00Z", 100),
    bar("2024-06-10T14:16:00Z", 101),
  ];
  const result = consumeDisplayBars({}, raw, "1");
  assert.equal(result.completed.length, 2);
  assert.equal(result.completed[0].t, raw[0].t);
  assert.equal(result.completed[1].t, raw[1].t);
  assert.equal(result.state.cursor, raw[1].t);
});

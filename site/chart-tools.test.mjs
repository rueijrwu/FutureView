// chart-tools.js memoises sessionKey on the UTC hour because _indicatorData calls
// it once per bar, and a 3M window is ~18k bars. The bucket is only sound because
// America/New_York is offset from UTC by a whole number of hours, so one UTC hour
// never straddles an ET calendar day or the 18:00 session boundary. These tests
// pin that: if the assumption breaks, VWAP silently anchors to the wrong session,
// which is the kind of thing nobody notices until a chart looks wrong.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

const source = await fs.readFile(new URL("./chart-tools.js", import.meta.url), "utf8");

const style = { getPropertyValue: () => "" };
globalThis.window = {};
globalThis.getComputedStyle = () => style;
globalThis.document = {
  documentElement: {},
  createElement: () => ({ style: {}, classList: { add() {}, remove() {}, toggle() {} }, appendChild() {} }),
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener() {},
};
globalThis.LightweightCharts = undefined;
globalThis.LightweightChartsDrawing = undefined;

await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const { sessionKey, sessionKeyUncached, SMA_ENTRIES } = window.__futureViewChartToolsInternals;

test("the memoised session key matches the direct computation hour by hour", () => {
  const spans = [
    ["2026-03-06T00:00:00Z", 24 * 6],  // spring forward, 2026-03-08
    ["2026-10-30T00:00:00Z", 24 * 6],  // fall back, 2026-11-01
    ["2026-06-15T00:00:00Z", 24 * 3],  // a plain EDT stretch
    ["2026-01-05T00:00:00Z", 24 * 3],  // a plain EST stretch
  ];
  let checked = 0;
  for (const [start, hours] of spans) {
    const base = Math.floor(Date.parse(start) / 1000);
    for (let hour = 0; hour < hours; hour += 1) {
      for (const offset of [0, 1, 1799, 3599]) {
        const seconds = base + hour * 3600 + offset;
        assert.equal(
          sessionKey(seconds),
          sessionKeyUncached(seconds),
          `mismatch at ${new Date(seconds * 1000).toISOString()}`,
        );
        checked += 1;
      }
    }
  }
  assert.ok(checked > 1000, `expected a dense sweep, checked ${checked}`);
});

test("the session key rolls at 18:00 ET, not at midnight", () => {
  const at = (iso) => Math.floor(Date.parse(iso) / 1000);
  assert.equal(sessionKey(at("2026-09-16T17:59:00-04:00")), "2026-09-16");
  assert.equal(sessionKey(at("2026-09-16T18:00:00-04:00")), "2026-09-17");
  assert.equal(sessionKey(at("2026-09-17T09:30:00-04:00")), "2026-09-17");
  assert.equal(sessionKey(at("2026-09-17T17:59:00-04:00")), "2026-09-17");
});

test("the SMA period table is hoisted, not rebuilt per bar", () => {
  assert.deepEqual(SMA_ENTRIES, [["sma5", 5], ["sma10", 10], ["sma20", 20], ["sma60", 60]]);
  // Same identity on every read: the point of hoisting it.
  assert.equal(window.__futureViewChartToolsInternals.SMA_ENTRIES, SMA_ENTRIES);
  const rebuilds = source.match(/Object\.entries\(SMA_PERIODS\)/g) || [];
  assert.equal(rebuilds.length, 1, "SMA_PERIODS should be turned into entries exactly once, at definition");
});

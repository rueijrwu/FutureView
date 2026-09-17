import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

let source = await fs.readFile(new URL("./chart-ui-repair.js", import.meta.url), "utf8");
source = source.replace(
  "function etParts(seconds) {\n    return",
  "function etParts(seconds) {\n    globalThis.__fvEtPartsCalls += 1;\n    return",
);

globalThis.__fvEtPartsCalls = 0;
globalThis.window = { FutureViewChartTools: class BaseChartTools {} };
globalThis.LightweightCharts = { LineSeries: {} };
globalThis.document = {
  querySelectorAll() { return []; },
  querySelector() { return null; },
};

await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const ChartTools = window.FutureViewChartTools;
const sec = (iso) => Math.floor(Date.parse(iso) / 1000);

function chartBar(iso, open, high, low, close, volume) {
  return { time: sec(iso), open, high, low, close, volume };
}

test("VWAP hot path computes the ET session boundary once", () => {
  const instance = Object.create(ChartTools.prototype);
  instance.bars = [
    chartBar("2026-09-16T17:00:00-04:00", 90, 92, 89, 91, 10),
    chartBar("2026-09-16T18:00:00-04:00", 100, 102, 99, 101, 20),
    chartBar("2026-09-17T09:30:00-04:00", 103, 105, 102, 104, 30),
    chartBar("2026-09-17T10:20:00-04:00", 106, 108, 105, 107, 40),
  ];

  let vwapUpdate = null;
  instance.indicators = {
    sma5: { update() {} },
    sma10: { update() {} },
    sma20: { update() {} },
    sma60: { update() {} },
    vwap: { update(value) { vwapUpdate = value; } },
  };

  globalThis.__fvEtPartsCalls = 0;
  instance._fvUpdateIndicatorsForLastBar();

  const included = instance.bars.slice(1);
  let pv = 0;
  let volume = 0;
  for (const bar of included) {
    pv += ((bar.high + bar.low + bar.close) / 3) * bar.volume;
    volume += bar.volume;
  }
  assert.equal(vwapUpdate.time, instance.bars.at(-1).time);
  assert.ok(Math.abs(vwapUpdate.value - pv / volume) < 1e-12);
  assert.ok(globalThis.__fvEtPartsCalls <= 4, `expected one sessionStart conversion, got ${globalThis.__fvEtPartsCalls} etParts calls`);
});

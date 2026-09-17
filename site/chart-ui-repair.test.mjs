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


function fullSessionVwap(bars) {
  const last = bars.at(-1);
  const local = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  });
  const parts = Object.fromEntries(
    local.formatToParts(new Date(last.time * 1000))
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, Number(part.value)]),
  );
  const day = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
  if (parts.hour < 18) day.setUTCDate(day.getUTCDate() - 1);
  const wanted = Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), 18);
  let guess = wanted;
  for (let i = 0; i < 4; i += 1) {
    const shown = Object.fromEntries(
      local.formatToParts(new Date(guess))
        .filter((part) => part.type !== "literal")
        .map((part) => [part.type, Number(part.value)]),
    );
    const shownWall = Date.UTC(shown.year, shown.month - 1, shown.day, shown.hour);
    const delta = wanted - shownWall;
    guess += delta;
    if (!delta) break;
  }
  const start = Math.floor(guess / 1000);
  let pv = 0;
  let volume = 0;
  for (const bar of bars) {
    if (bar.time < start) continue;
    const v = Number(bar.volume) || 0;
    pv += ((bar.high + bar.low + bar.close) / 3) * v;
    volume += v;
  }
  return volume > 0 ? pv / volume : null;
}

function indicatorHarness(bars) {
  const instance = Object.create(ChartTools.prototype);
  instance.bars = bars.map((bar) => ({ ...bar }));
  instance._fvVwapState = null;
  instance.vwapPriceVolume = Number.NaN;
  instance.vwapVolume = Number.NaN;
  let vwapUpdate = null;
  instance.indicators = {
    sma5: { update() {} },
    sma10: { update() {} },
    sma20: { update() {} },
    sma60: { update() {} },
    vwap: { update(value) { vwapUpdate = value; } },
  };
  return { instance, lastVwap: () => vwapUpdate };
}

test("VWAP live append is O(1) within the cached futures session", () => {
  const initial = [
    chartBar("2026-09-16T18:00:00-04:00", 100, 102, 99, 101, 20),
    chartBar("2026-09-17T09:30:00-04:00", 103, 105, 102, 104, 30),
    chartBar("2026-09-17T10:20:00-04:00", 106, 108, 105, 107, 40),
  ];
  const { instance, lastVwap } = indicatorHarness(initial);
  instance._fvUpdateIndicatorsForLastBar();

  const next = chartBar("2026-09-17T10:25:00-04:00", 108, 110, 107, 109, 50);
  instance.bars.push(next);
  globalThis.__fvEtPartsCalls = 0;
  instance._fvUpdateIndicatorsForLastBar();

  assert.equal(globalThis.__fvEtPartsCalls, 0);
  assert.ok(Math.abs(lastVwap().value - fullSessionVwap(instance.bars)) < 1e-12);
});

test("VWAP same-timestamp replacement subtracts the prior contribution", () => {
  const initial = [
    chartBar("2026-09-16T18:00:00-04:00", 100, 102, 99, 101, 20),
    chartBar("2026-09-17T10:20:00-04:00", 106, 108, 105, 107, 40),
  ];
  const { instance, lastVwap } = indicatorHarness(initial);
  instance._fvUpdateIndicatorsForLastBar();

  instance.bars[instance.bars.length - 1] =
    chartBar("2026-09-17T10:20:00-04:00", 106, 112, 104, 111, 70);
  globalThis.__fvEtPartsCalls = 0;
  instance._fvUpdateIndicatorsForLastBar();

  assert.equal(globalThis.__fvEtPartsCalls, 0);
  assert.ok(Math.abs(lastVwap().value - fullSessionVwap(instance.bars)) < 1e-12);
});

test("VWAP resets at the 18:00 ET futures-session rollover", () => {
  const initial = [
    chartBar("2026-09-17T16:55:00-04:00", 100, 102, 99, 101, 20),
  ];
  const { instance, lastVwap } = indicatorHarness(initial);
  instance._fvUpdateIndicatorsForLastBar();

  const next = chartBar("2026-09-17T18:00:00-04:00", 110, 112, 109, 111, 30);
  instance.bars.push(next);
  globalThis.__fvEtPartsCalls = 0;
  instance._fvUpdateIndicatorsForLastBar();

  const typical = (next.high + next.low + next.close) / 3;
  assert.ok(globalThis.__fvEtPartsCalls > 0);
  assert.ok(Math.abs(lastVwap().value - typical) < 1e-12);
});

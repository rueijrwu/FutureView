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


function fullSma(bars, period) {
  if (bars.length < period) return null;
  let sum = 0;
  for (let i = bars.length - period; i < bars.length; i += 1) sum += Number(bars[i].close);
  return sum / period;
}

function smaHarness(bars) {
  const instance = Object.create(ChartTools.prototype);
  instance.bars = bars.map((bar) => ({ ...bar }));
  instance._fvSmaState = null;
  instance._fvVwapState = { start: -Infinity, end: Infinity, priceVolume: 0, volume: 0, lastTime: null, lastPriceVolume: 0, lastVolume: 0 };
  const updates = {};
  instance.indicators = {
    sma5: { update(value) { updates.sma5 = value; } },
    sma10: { update(value) { updates.sma10 = value; } },
    sma20: { update(value) { updates.sma20 = value; } },
    sma60: { update(value) { updates.sma60 = value; } },
    vwap: { update() {} },
  };
  instance._fvSyncSmaState();
  return { instance, updates };
}

test("SMA live append uses rolling sums with exact values", () => {
  const bars = [];
  for (let i = 0; i < 70; i += 1) {
    bars.push(chartBar(`2026-09-17T${String(9 + Math.floor((30 + i) / 60)).padStart(2, "0")}:${String((30 + i) % 60).padStart(2, "0")}:00-04:00`, 100+i, 101+i, 99+i, 100.5+i, 10));
  }
  const { instance, updates } = smaHarness(bars);
  const next = { ...instance.bars.at(-1), time: instance.bars.at(-1).time + 60, close: 250 };
  instance.bars.push(next);
  instance._fvUpdateIndicatorsForLastBar();

  for (const [key, period] of Object.entries({ sma5: 5, sma10: 10, sma20: 20, sma60: 60 })) {
    assert.ok(Math.abs(updates[key].value - fullSma(instance.bars, period)) < 1e-12);
  }
});

test("SMA same-timestamp replacement adjusts rolling sums by delta", () => {
  const bars = [];
  for (let i = 0; i < 70; i += 1) {
    bars.push({ time: sec("2026-09-17T09:30:00-04:00") + i * 60, open: 100+i, high: 101+i, low: 99+i, close: 100.5+i, volume: 10 });
  }
  const { instance, updates } = smaHarness(bars);
  instance.bars[instance.bars.length - 1] = { ...instance.bars.at(-1), close: 333 };
  instance._fvUpdateIndicatorsForLastBar();

  for (const [key, period] of Object.entries({ sma5: 5, sma10: 10, sma20: 20, sma60: 60 })) {
    assert.ok(Math.abs(updates[key].value - fullSma(instance.bars, period)) < 1e-12);
  }
});


test("hidden indicators skip full historical point-array rebuild", () => {
  const instance = Object.create(ChartTools.prototype);
  instance.toolbar = { querySelector() { return null; } };
  instance._fvNativeCandleSetData = () => {};
  instance._fvNativeVolumeSetData = () => {};
  instance._showLegend = () => {};
  let refreshCalls = 0;
  let vwapSeeds = 0;
  let smaSeeds = 0;
  instance._refreshIndicators = () => { refreshCalls += 1; };
  instance._fvRebuildVwapState = () => { vwapSeeds += 1; return {}; };
  instance._fvSyncSmaState = () => { smaSeeds += 1; return {}; };

  const bars = [
    chartBar("2026-09-17T09:30:00-04:00", 100, 101, 99, 100.5, 10),
    chartBar("2026-09-17T09:35:00-04:00", 101, 102, 100, 101.5, 20),
  ];
  instance._fvSetDisplayData(bars);

  assert.equal(refreshCalls, 0);
  assert.equal(vwapSeeds, 1);
  assert.equal(smaSeeds, 1);
  assert.equal(instance.bars.length, 2);
});

test("active indicator preserves full historical refresh on setData", () => {
  const activeButton = {};
  const instance = Object.create(ChartTools.prototype);
  instance.toolbar = {
    querySelector(selector) {
      return selector.includes('sma20') ? activeButton : null;
    },
  };
  instance._fvNativeCandleSetData = () => {};
  instance._fvNativeVolumeSetData = () => {};
  instance._showLegend = () => {};
  let refreshCalls = 0;
  let vwapSyncs = 0;
  let smaSyncs = 0;
  instance._refreshIndicators = () => { refreshCalls += 1; };
  instance._fvSyncVwapStateFromBase = () => { vwapSyncs += 1; };
  instance._fvSyncSmaState = () => { smaSyncs += 1; };

  instance._fvSetDisplayData([
    chartBar("2026-09-17T09:30:00-04:00", 100, 101, 99, 100.5, 10),
  ]);

  assert.equal(refreshCalls, 1);
  assert.equal(vwapSyncs, 1);
  assert.equal(smaSyncs, 1);
});


test("hidden live indicators maintain rolling state without chart series updates", () => {
  const bars = [];
  for (let i = 0; i < 70; i += 1) {
    bars.push({
      time: sec("2026-09-17T09:30:00-04:00") + i * 60,
      open: 100 + i,
      high: 101 + i,
      low: 99 + i,
      close: 100.5 + i,
      volume: 10,
    });
  }
  const instance = Object.create(ChartTools.prototype);
  instance.bars = bars;
  instance.toolbar = { querySelector() { return null; } };
  instance._fvSmaState = null;
  instance._fvVwapState = null;
  let seriesUpdates = 0;
  instance.indicators = {
    sma5: { update() { seriesUpdates += 1; } },
    sma10: { update() { seriesUpdates += 1; } },
    sma20: { update() { seriesUpdates += 1; } },
    sma60: { update() { seriesUpdates += 1; } },
    vwap: { update() { seriesUpdates += 1; } },
  };

  instance._fvUpdateIndicatorsForLastBar();
  const initialSma = { ...instance._fvSmaState.sums };
  const initialVwap = instance._fvVwapState.priceVolume;

  const next = { ...bars.at(-1), time: bars.at(-1).time + 60, close: 250, high: 251, low: 249, volume: 20 };
  instance.bars.push(next);
  instance._fvUpdateIndicatorsForLastBar();

  assert.equal(seriesUpdates, 0);
  assert.notDeepEqual(instance._fvSmaState.sums, initialSma);
  assert.notEqual(instance._fvVwapState.priceVolume, initialVwap);
});

test("live indicator updates touch only active chart series", () => {
  const bars = [];
  for (let i = 0; i < 70; i += 1) {
    bars.push({
      time: sec("2026-09-17T09:30:00-04:00") + i * 60,
      open: 100 + i,
      high: 101 + i,
      low: 99 + i,
      close: 100.5 + i,
      volume: 10,
    });
  }
  const instance = Object.create(ChartTools.prototype);
  instance.bars = bars;
  instance.toolbar = {
    querySelector(selector) {
      return selector.includes('sma20') || selector.includes('vwap') ? {} : null;
    },
  };
  instance._fvSmaState = null;
  instance._fvVwapState = null;
  const updates = [];
  instance.indicators = Object.fromEntries(
    ["sma5", "sma10", "sma20", "sma60", "vwap"].map((key) => [
      key,
      { update() { updates.push(key); } },
    ]),
  );

  instance._fvUpdateIndicatorsForLastBar();

  assert.deepEqual(updates.sort(), ["sma20", "vwap"]);
});


test("cached indicator visibility avoids DOM queries on the live path", () => {
  const instance = Object.create(ChartTools.prototype);
  instance._fvIndicatorVisible = {
    sma5: true,
    sma10: false,
    sma20: false,
    sma60: false,
    vwap: true,
  };
  let queryCalls = 0;
  instance.toolbar = {
    querySelector() {
      queryCalls += 1;
      throw new Error("cached visibility should bypass the DOM");
    },
  };

  assert.equal(instance._fvIndicatorActive("sma5"), true);
  assert.equal(instance._fvIndicatorActive("sma10"), false);
  assert.equal(instance._fvIndicatorActive("vwap"), true);
  assert.equal(queryCalls, 0);
});


function rawMinuteBars(startIso, count, base = 100) {
  const start = sec(startIso);
  return Array.from({ length: count }, (_, index) => ({
    t: start + index * 60,
    o: base + index,
    h: base + index + 1,
    l: base + index - 1,
    c: base + index + 0.5,
    v: (index % 7) + 1,
  }));
}

test("reset warmup aggregation uses bounded ET conversions for 5m history", () => {
  const instance = Object.create(ChartTools.prototype);
  instance._fvTimeframe = "5";
  instance._fvHistorySeconds = 5 * 86400;
  instance._fvRawBars = [];
  instance._fvActiveAggregate = null;
  instance._cancelDrawing = () => {};
  instance._fvTrimRawTail = () => {};
  instance._fvRefreshRangeBoundaries = () => {};
  let display = null;
  instance._fvSetDisplayData = (bars) => { display = bars; };

  const raw = rawMinuteBars("2026-09-17T09:00:00-04:00", 480, 100);
  globalThis.__fvEtPartsCalls = 0;
  instance.reset(raw);

  assert.equal(display.length, 96);
  assert.ok(globalThis.__fvEtPartsCalls <= 8);
  assert.equal(display[0].time, sec("2026-09-17T09:00:00-04:00"));
  assert.equal(display.at(-1).time, sec("2026-09-17T16:55:00-04:00"));
});

test("active 4h rebuild performs one timezone bucket seed", () => {
  const instance = Object.create(ChartTools.prototype);
  instance._fvTimeframe = "240";
  instance._fvRawBars = rawMinuteBars("2026-09-17T18:00:00-04:00", 370, 200);

  globalThis.__fvEtPartsCalls = 0;
  const active = instance._fvRebuildActiveAggregate();

  assert.ok(globalThis.__fvEtPartsCalls <= 8);
  assert.equal(active.time, sec("2026-09-17T22:00:00-04:00"));
  assert.equal(active.open, instance._fvRawBars[240].o);
  assert.equal(active.close, instance._fvRawBars.at(-1).c);
});

test("active 1D rebuild begins at prior 18:00 ET session start", () => {
  const instance = Object.create(ChartTools.prototype);
  instance._fvTimeframe = "1D";
  instance._fvRawBars = rawMinuteBars("2026-09-16T18:00:00-04:00", 960, 300);

  const active = instance._fvRebuildActiveAggregate();

  assert.equal(active.time, sec("2026-09-17T00:00:00-04:00"));
  assert.equal(active.open, instance._fvRawBars[0].o);
  assert.equal(active.close, instance._fvRawBars.at(-1).c);
});

test("warmup aggregation reseeds after a DST weekend gap", () => {
  const instance = Object.create(ChartTools.prototype);
  instance._fvTimeframe = "30";
  instance._fvHistorySeconds = 5 * 86400;
  instance._fvRawBars = [];
  instance._fvActiveAggregate = null;
  instance._cancelDrawing = () => {};
  instance._fvTrimRawTail = () => {};
  instance._fvRefreshRangeBoundaries = () => {};
  let display = null;
  instance._fvSetDisplayData = (bars) => { display = bars; };

  const friday = rawMinuteBars("2026-03-06T16:30:00-05:00", 30, 100);
  const sunday = rawMinuteBars("2026-03-08T18:00:00-04:00", 30, 200);
  instance.reset([...friday, ...sunday]);

  assert.deepEqual(display.map((bar) => bar.time), [
    sec("2026-03-06T16:30:00-05:00"),
    sec("2026-03-08T18:00:00-04:00"),
  ]);
});


test("active 1D rebuild uses midnight ET during EST", () => {
  const instance = Object.create(ChartTools.prototype);
  instance._fvTimeframe = "1D";
  instance._fvRawBars = rawMinuteBars("2026-12-09T18:00:00-05:00", 960, 400);

  const active = instance._fvRebuildActiveAggregate();

  assert.equal(active.time, sec("2026-12-10T00:00:00-05:00"));
  assert.equal(active.open, instance._fvRawBars[0].o);
  assert.equal(active.close, instance._fvRawBars.at(-1).c);
});



// A controller stubbed just far enough to drive the viewport logic without a
// real chart. The chart places a viewport by bar index, not by time, so these
// record the logical range that actually reaches the axis.
const DAY = 86400;
const T0 = Math.floor(Date.UTC(2026, 0, 1) / 1000);

function viewportHarness({ count = 100, timeframe = "1D", step = DAY } = {}) {
  const instance = Object.create(ChartTools.prototype);
  const calls = { fits: 0, logical: [], time: [], price: [] };
  let visibleRange = { from: T0 + 10 * step, to: T0 + 20 * step };
  let priceRange = { from: 10, to: 20 };

  instance._fvTimeframe = timeframe;
  instance._fvHistorySeconds = 5 * DAY;
  instance._fvRawBars = [];
  instance.bars = Array.from({ length: count }, (_, i) => ({
    time: T0 + i * step, open: 1, high: 2, low: 0, close: 1, volume: 1,
  }));
  let visibleLogicalRange = { from: 10, to: 20 };
  instance._fvViewportLocked = false;
  instance._fvLockedCentre = null;
  instance._fvDesiredRange = null;
  instance._fvUserInteractionUntil = 0;
  instance._fvDataSettled = true;
  instance._cancelDrawing = () => {};
  instance._fvSetDisplayData = () => {};
  instance._fvRefreshRangeBoundaries = () => {};
  instance._fvRebuildActiveAggregate = () => null;
  instance._fvSyncTimeframeUi = () => {};
  instance._fvSyncLockUi = () => {};
  instance.fit = () => { calls.fits += 1; };
  instance._fvNativeSetVisibleLogicalRange = (range) => calls.logical.push(range);
  instance._fvNativeSetVisibleRange = (range) => calls.time.push(range);
  instance.chart = {
    timeScale: () => ({
      getVisibleRange: () => visibleRange,
      getVisibleLogicalRange: () => visibleLogicalRange,
    }),
  };
  instance.candles = {
    priceScale: () => ({
      getVisibleRange: () => priceRange,
      setVisibleRange: (range) => calls.price.push(range),
      applyOptions: () => {},
    }),
  };

  return {
    instance,
    calls,
    at: (index) => T0 + index * step,
    setVisible: (from, to) => { visibleRange = { from, to }; },
    setPrice: (from, to) => { priceRange = { from, to }; },
    setVisibleLogical: (from, to) => { visibleLogicalRange = { from, to }; },
    lastLogical: () => calls.logical.at(-1),
  };
}

// _fvApplyTimeRange defers one re-assert to the next frame.
globalThis.requestAnimationFrame = () => {};
globalThis.performance ??= { now: () => 0 };

test("a time window becomes the matching bar indices", () => {
  const h = viewportHarness();
  h.instance._fvApplyTimeRange({ from: h.at(10), to: h.at(20) });
  const got = h.lastLogical();
  assert.ok(Math.abs(got.from - 10) < 0.01, `from ${got.from}`);
  assert.ok(Math.abs(got.to - 20) < 0.01, `to ${got.to}`);
});

test("a window narrower than one bar widens to exactly one bar", () => {
  const h = viewportHarness();
  // Two hours inside bar 50 - far less than the one-day bar it lands in.
  const noon = h.at(50) + 10 * 3600;
  h.instance._fvApplyTimeRange({ from: noon, to: noon + 2 * 3600 });
  const got = h.lastLogical();
  assert.ok(Math.abs((got.to - got.from) - 1) < 0.01, `width ${got.to - got.from}`);
  // ...and stays over the bar the user was reading, not somewhere else.
  assert.ok(got.from > 49 && got.to < 52, `placed at ${got.from}..${got.to}`);
});

test("a window running past the last bar is pulled back onto it", () => {
  const h = viewportHarness({ count: 100 });
  h.instance._fvApplyTimeRange({ from: h.at(95), to: h.at(130) });
  const got = h.lastLogical();
  // There is one whitespace point beyond the last bar and no more, so the
  // window cannot keep a width that reaches into empty space. What matters is
  // that it ends on the last bar and still covers where the user was reading.
  assert.equal(got.to, 99, "right edge sits on the last bar");
  assert.ok(got.from > 92 && got.from < 97, `left edge stayed near the request, got ${got.from}`);
});

test("a window wider than the data shows the data, not the whitespace beyond it", () => {
  const h = viewportHarness({ count: 100 });
  h.instance._fvApplyTimeRange({ from: h.at(-500), to: h.at(130) });
  assert.deepEqual(h.lastLogical(), { from: 0, to: 99 });
});

test("a bar-scale switch never fits", () => {
  const h = viewportHarness({ timeframe: "5", step: 300, count: 300 });
  h.instance._fvSetTimeframe("1D");
  assert.equal(h.calls.fits, 0, "only Start/Random and Fit may fit");
});

test("re-selecting the active bar scale does nothing", () => {
  const h = viewportHarness({ timeframe: "5", step: 300 });
  h.instance._fvSetTimeframe("5");
  assert.equal(h.calls.fits, 0);
  assert.equal(h.calls.logical.length, 0);
});

test("the window is carried across the switch, not re-read from the starved middle", () => {
  const h = viewportHarness({ timeframe: "1D", step: DAY, count: 100 });
  const want = { from: h.at(80), to: h.at(90) };
  h.setVisible(want.from, want.to);

  h.instance._fvSetTimeframe("5");
  assert.deepEqual(h.instance._fvDesiredRange, want, "the pre-switch window is carried");

  // The local re-aggregation leaves the axis somewhere else entirely; the
  // authoritative window that follows must not adopt that, but the carried one.
  h.setVisible(h.at(2), h.at(4));
  h.instance._fvTimeframe = "5";
  h.instance._fvLoadCachedWindow("5", h.instance.bars.map((b) => ({ t: b.time, o: 1, h: 2, l: 0, c: 1, v: 1 })));

  const got = h.lastLogical();
  assert.ok(Math.abs(got.from - 80) < 0.01 && Math.abs(got.to - 90) < 0.01,
    `restored ${got.from}..${got.to}, expected the carried 80..90`);
  assert.equal(h.instance._fvDesiredRange, null, "and it is spent once honoured");
});

test("with nothing carried, a cached window just preserves what was on screen", () => {
  const h = viewportHarness();
  h.instance._fvLoadCachedWindow("1D", h.instance.bars.map((b) => ({ t: b.time, o: 1, h: 2, l: 0, c: 1, v: 1 })));
  assert.equal(h.calls.fits, 0, "data arrival never fits on its own");
  assert.deepEqual(h.calls.time.at(-1), { from: T0 + 10 * DAY, to: T0 + 20 * DAY });
});

test("Lock captures only the centre time and price at engage time - no span", () => {
  const h = viewportHarness();
  h.setVisible(h.at(40), h.at(50));
  h.setPrice(5580, 5620);
  h.instance._fvToggleLock();
  assert.equal(h.instance._fvViewportLocked, true);
  assert.ok(Math.abs(h.instance._fvLockedCentre.time - h.at(45)) < 0.01);
  assert.equal(h.instance._fvLockedCentre.price, 5600);
  assert.equal("span" in h.instance._fvLockedCentre, false, "span must not be captured");
  assert.equal("priceSpan" in h.instance._fvLockedCentre, false, "priceSpan must not be captured");
});

test("Lock re-centres on the anchor using the chart's current zoom width, not a captured one", () => {
  const h = viewportHarness();
  h.setVisible(h.at(40), h.at(50));
  h.instance._fvToggleLock();

  // The chart's current zoom is whatever it naturally is right now - here a
  // width of 6 bars, unrelated to whatever was on screen at engage time.
  h.setVisibleLogical(2, 8);
  h.instance._fvRecentreLocked();

  const got = h.lastLogical();
  assert.ok(Math.abs((got.from + got.to) / 2 - 45) < 0.01, `centred on ${(got.from + got.to) / 2}`);
  assert.ok(Math.abs((got.to - got.from) - 6) < 0.01, `used the chart's current width, got ${got.to - got.from} bars`);
});

test("Lock centres the price too, using the chart's current price-axis width", () => {
  const h = viewportHarness();
  h.setPrice(5580, 5620);
  h.instance._fvToggleLock();

  h.setPrice(0, 100);
  h.instance._fvRecentreLocked();
  assert.deepEqual(h.calls.price.at(-1), { from: 5550, to: 5650 });
});

test("engaging Lock does not move the chart", () => {
  const h = viewportHarness();
  h.instance._fvToggleLock();
  assert.deepEqual(h.calls.logical, []);
  assert.deepEqual(h.calls.time, []);
  assert.deepEqual(h.calls.price, []);
  assert.equal(h.calls.fits, 0);
});

test("locked, a bar-scale change re-centres on the anchor using the chart's current zoom width", () => {
  const h = viewportHarness();
  h.setVisible(h.at(40), h.at(50));
  h.instance._fvToggleLock();

  // Whatever zoom the chart naturally has after the switch's local
  // re-aggregation - here 6 bars, unrelated to the width at engage time -
  // is what the re-centre must use. No span is carried from Lock itself.
  h.setVisibleLogical(2, 8);
  h.instance._fvSetTimeframe("5");

  const got = h.lastLogical();
  assert.ok(Math.abs((got.from + got.to) / 2 - 45) < 0.01, `centred on ${(got.from + got.to) / 2}`);
  assert.ok(Math.abs((got.to - got.from) - 6) < 0.01, `used the chart's current width, got ${got.to - got.from} bars`);
});

test("a centred window may run past the last bar", () => {
  const h = viewportHarness({ count: 100 });
  // Centred on 99 (the last bar) with the chart's current width wide enough
  // that half of it reaches past the data - which is what being centred on
  // the latest bar means, so it is not pulled back onto the data.
  h.setVisible(h.at(97), h.at(101));
  h.instance._fvToggleLock();
  h.instance._fvRecentreLocked();
  const got = h.lastLogical();
  assert.ok(got.to > 99, `centre held into the empty space, got ${got.from}..${got.to}`);
  assert.ok(Math.abs((got.from + got.to) / 2 - 99) < 1.5, `centred near 99, got ${(got.from + got.to) / 2}`);
});

test("unlocked, price is never pinned and nothing is centred", () => {
  const h = viewportHarness();
  assert.equal(h.instance._fvRecentreLocked(), false);
  h.instance._fvSetTimeframe("5");
  assert.deepEqual(h.calls.price, []);
});

test("toggling Lock off clears the centre", () => {
  const h = viewportHarness();
  h.instance._fvToggleLock();
  h.instance._fvToggleLock();
  assert.equal(h.instance._fvViewportLocked, false);
  assert.equal(h.instance._fvLockedCentre, null);
  h.instance._fvSetTimeframe("5");
  assert.deepEqual(h.calls.price, [], "nothing is pinned once the lock is off");
});

test("locked, a history-range change keeps the centre", () => {
  const h = viewportHarness();
  h.setVisible(h.at(40), h.at(50));
  h.instance._fvToggleLock();
  h.instance._fvSetHistoryRange(3600);
  const got = h.lastLogical();
  assert.ok(Math.abs((got.from + got.to) / 2 - 45) < 0.01, `centred on ${(got.from + got.to) / 2}`);
});

test("a wheel pan alone (no pointer events) re-captures the locked centre", () => {
  const h = viewportHarness();
  h.setVisible(h.at(40), h.at(50));
  h.instance._fvToggleLock();

  // The user scrolled elsewhere with the wheel - no pointerdown/up at all.
  // The real path debounces this through a timer; call the same recapture
  // the timer would fire, directly, so the test needs no real delay.
  h.setVisible(h.at(10), h.at(20));
  h.instance._fvRecaptureLockedCentre();

  assert.ok(Math.abs(h.instance._fvLockedCentre.time - h.at(15)) < 0.01,
    `centre not updated by the wheel pan, got ${h.instance._fvLockedCentre.time}`);
});

test("a pan/wheel recapture during the starved bar-scale-switch render does not corrupt the anchor", () => {
  const h = viewportHarness();
  h.setVisible(h.at(40), h.at(50));
  h.instance._fvToggleLock();
  const before = h.instance._fvLockedCentre;

  // _fvSetTimeframe marks the data unsettled before its starved local
  // re-aggregation renders. A wheel/pan event (or its debounced recapture)
  // landing here must not read the live, starved chart back as the anchor -
  // this is the corruption this guards against.
  h.instance._fvDataSettled = false;
  h.setVisible(h.at(2), h.at(4));
  h.instance._fvRecaptureLockedCentre();

  assert.deepEqual(h.instance._fvLockedCentre, before,
    "anchor must be unchanged while data is unsettled");
});

test("a pan/wheel recapture once the authoritative window has settled does update the anchor", () => {
  const h = viewportHarness();
  h.setVisible(h.at(40), h.at(50));
  h.instance._fvToggleLock();

  h.instance._fvDataSettled = true;
  h.setVisible(h.at(10), h.at(20));
  h.instance._fvRecaptureLockedCentre();

  assert.ok(Math.abs(h.instance._fvLockedCentre.time - h.at(15)) < 0.01,
    `anchor should update once data is settled, got ${h.instance._fvLockedCentre.time}`);
});

test("_fvSetTimeframe marks data unsettled, _fvLoadCachedWindow settles it again", () => {
  const h = viewportHarness({ timeframe: "1D", step: DAY, count: 100 });
  assert.equal(h.instance._fvDataSettled, true, "starts settled");

  h.instance._fvSetTimeframe("5");
  assert.equal(h.instance._fvDataSettled, false,
    "the starved local re-aggregation is not the authoritative window");

  h.instance._fvTimeframe = "5";
  h.instance._fvLoadCachedWindow("5", h.instance.bars.map((b) => ({ t: b.time, o: 1, h: 2, l: 0, c: 1, v: 1 })));
  assert.equal(h.instance._fvDataSettled, true,
    "the worker's display_window is authoritative");
});

test("Start/Random clears a carried window so its own fit stands", () => {
  const h = viewportHarness();
  h.instance._fvDesiredRange = { from: h.at(10), to: h.at(20) };
  h.instance._fvTrimRawTail = () => {};
  h.instance.reset([]);
  assert.equal(h.instance._fvDesiredRange, null);
});

// Drawings could be placed but never touched again: hovering, right-click -> Delete
// and drag-to-move all missed the shape. Two causes, both pinned here.
//
// 1. lightweight-charts speaks *pane* coordinates - the series area, price axes
//    excluded - while a DOM event on the chart element is relative to the element,
//    axes included. chart-tools-fixes.js turns the left price scale on for the volume
//    overlay, so every container-derived hit test looked ~55px to the right of the
//    cursor and found nothing.
// 2. The move drag shifted each anchor by a raw time delta. Bar times are not evenly
//    spaced (session break, weekends, aggregated scales), so the result landed between
//    bars, where timeScale.timeToCoordinate() returns null - and a null there makes the
//    drawing both invisible and un-hittable, i.e. permanently un-editable.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

// ---- A chart just real enough to be wrong the same way the browser was ----

const BAR_SPACING = 10;
const LEFT_AXIS_WIDTH = 55;
const CONTAINER_LEFT = 120;
const CONTAINER_TOP = 40;
const PANE_HEIGHT = 400;
const PRICE_TOP = 5100;
const PRICE_PER_PIXEL = 0.5;

// One minute bars with a hole in them: 17:00-18:00 ET is the CME maintenance break,
// so bar times are not a uniform arithmetic series and time arithmetic cannot assume
// a shifted time is still a bar.
const GAP_AFTER = 20;
const BAR_TIMES = [];
for (let i = 0; i < 40; i += 1) {
  BAR_TIMES.push(1_700_000_000 + i * 60 + (i > GAP_AFTER ? 3600 : 0));
}

const paneX = (index) => (index + 0.5) * BAR_SPACING;
const priceToY = (price) => (PRICE_TOP - price) / PRICE_PER_PIXEL;
const yToPrice = (y) => PRICE_TOP - y * PRICE_PER_PIXEL;

function makeChart() {
  return {
    applyOptions() {},
    addSeries: () => makeSeries(),
    subscribeClick() {},
    subscribeCrosshairMove() {},
    priceScale: (id) => ({ width: () => (id === "left" ? LEFT_AXIS_WIDTH : 0), applyOptions() {} }),
    timeScale: () => ({
      width: () => BAR_TIMES.length * BAR_SPACING,
      // Exactly lightweight-charts' contract: an exact bar match or null. This is the
      // behaviour the old time-delta drag tripped over.
      timeToCoordinate: (time) => {
        const index = BAR_TIMES.indexOf(time);
        return index === -1 ? null : paneX(index);
      },
      // Snaps to the nearest bar index, null outside the data.
      coordinateToTime: (x) => {
        const index = Math.round(x / BAR_SPACING - 0.5);
        return index < 0 || index >= BAR_TIMES.length ? null : BAR_TIMES[index];
      },
      logicalToCoordinate: (l) => paneX(l),
      scrollToRealTime() {},
    }),
  };
}

function makeSeries() {
  return {
    applyOptions() {},
    options: () => ({ visible: false }),
    setData() {},
    update() {},
    priceScale: () => ({ applyOptions() {}, getVisibleRange: () => null }),
    priceToCoordinate: (price) => priceToY(price),
    coordinateToPrice: (y) => yToPrice(y),
  };
}

// ---- The drawing plugin, reduced to the parts the interaction path touches ----

function distanceToSegment(point, a, b) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lengthSquared = dx * dx + dy * dy;
  const t = lengthSquared === 0 ? 0 : Math.max(0, Math.min(1, ((point.x - a.x) * dx + (point.y - a.y) * dy) / lengthSquared));
  return Math.hypot(point.x - (a.x + t * dx), point.y - (a.y + t * dy));
}

class FakeDrawing {
  constructor(type, id, anchors, style) {
    this.type = type;
    this.id = id;
    this.anchors = anchors.map((a) => ({ ...a }));
    this.style = { lineWidth: 2, lineDash: [], ...style };
    this.options = { visible: true, locked: false };
    this.state = "normal";
  }

  setAnchors(anchors) {
    this.anchors = anchors.map((a) => ({ ...a }));
  }

  setState(state) {
    this.state = state;
  }

  _pixels(viewport) {
    return this.anchors.map((anchor) => {
      const x = viewport.timeScale.timeToCoordinate(anchor.time);
      const y = viewport.priceScale.priceToCoordinate(anchor.price);
      return x == null || y == null ? null : { x, y };
    });
  }

  // The library bails out of both hit testing and rendering when an anchor cannot be
  // placed, which is what made an off-grid anchor unrecoverable.
  testHit(point, viewport) {
    const pixels = this._pixels(viewport);
    if (pixels.some((p) => p === null)) return false;
    return distanceToSegment(point, pixels[0], pixels[1]) <= 5;
  }

  isRenderable(viewport) {
    return this._pixels(viewport).every((p) => p !== null);
  }

  hitTestAnchor(point, viewport) {
    const pixels = this._pixels(viewport);
    for (let i = 0; i < pixels.length; i += 1) {
      if (pixels[i] && Math.hypot(point.x - pixels[i].x, point.y - pixels[i].y) <= 8) return i;
    }
    return null;
  }
}

// A real horizontal-line drawing spans the full pane width and hit-tests on y alone,
// ignoring x - unlike a trend line, whose two anchors give testHit an x-bounded
// segment. That's what let a mousedown on the price axis (x outside the pane, but at
// a y that lines up with the line) match as a hit at all.
class FakeHLine extends FakeDrawing {
  testHit(point, viewport) {
    const y = viewport.priceScale.priceToCoordinate(this.anchors[0].price);
    if (y == null) return false;
    return Math.abs(point.y - y) <= 5;
  }

  isRenderable(viewport) {
    return viewport.priceScale.priceToCoordinate(this.anchors[0].price) != null;
  }
}

class FakeDrawingManager {
  constructor() {
    this.drawings = new Map();
    this.selectedId = null;
    this.viewport = null;
  }

  attach(chart, series, container) {
    this.chart = chart;
    this.series = series;
    this.container = container;
  }

  addDrawing(drawing) {
    this.drawings.set(drawing.id, drawing);
  }

  removeDrawing(id) {
    if (this.selectedId === id) this.selectedId = null;
    this.drawings.delete(id);
  }

  clearAll() {
    this.drawings.clear();
    this.selectedId = null;
  }

  selectDrawing(id) {
    this.selectedId = id;
  }

  getSelectedDrawing() {
    return (this.selectedId && this.drawings.get(this.selectedId)) || null;
  }

  hitTest(point) {
    for (const drawing of [...this.drawings.values()].reverse()) {
      if (drawing.options.visible && drawing.testHit(point, this.viewport)) return drawing;
    }
    return null;
  }
}

// ---- Enough DOM to build and click a context menu ----

function makeElement(tagName = "DIV") {
  const el = {
    tagName,
    children: [],
    style: {},
    dataset: {},
    className: "",
    textContent: "",
    isContentEditable: false,
    classList: { add() {}, remove() {}, toggle() {} },
    listeners: {},
    addEventListener(type, handler) {
      (el.listeners[type] ||= []).push(handler);
    },
    removeEventListener() {},
    setAttribute() {},
    appendChild(child) {
      el.children.push(child);
      return child;
    },
    append(...nodes) {
      el.children.push(...nodes);
    },
    remove() {},
    contains: () => false,
    querySelector: () => null,
    querySelectorAll: () => [],
    closest: () => null,
    focus() {},
  };
  return el;
}

function flatten(el, out = []) {
  for (const child of el.children || []) {
    out.push(child);
    flatten(child, out);
  }
  return out;
}

const source = await fs.readFile(new URL("./chart-tools.js", import.meta.url), "utf8");

const documentKeydown = [];
globalThis.getComputedStyle = () => ({ getPropertyValue: () => "" });
globalThis.document = {
  documentElement: {},
  body: makeElement(),
  createElement: (tag) => makeElement(tag.toUpperCase()),
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener(type, handler) {
    if (type === "keydown") documentKeydown.push(handler);
  },
  removeEventListener() {},
  execCommand() {},
};
globalThis.window = {
  LightweightCharts: { LineSeries: "line", CrosshairMode: { Magnet: 1, Normal: 0 }, PriceScaleMode: { Normal: 0, Logarithmic: 1 } },
  LightweightChartsDrawing: {
    DrawingManager: FakeDrawingManager,
    InteractionHandler: class {},
    getToolRegistry: () => ({
      get: () => ({ requiredAnchors: 2 }),
      createDrawing: (type, id, anchors, style) =>
        type === "horizontal-line" ? new FakeHLine(type, id, anchors, style) : new FakeDrawing(type, id, anchors, style),
    }),
  },
};

await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
const FutureViewChartTools = window.FutureViewChartTools;

function makeTools() {
  documentKeydown.length = 0;
  const container = makeElement();
  container.getBoundingClientRect = () => ({ left: CONTAINER_LEFT, top: CONTAINER_TOP, width: 800, height: PANE_HEIGHT + 30 });
  container.clientHeight = PANE_HEIGHT;
  const toolbar = makeElement();
  const chart = makeChart();
  const tools = new FutureViewChartTools({
    chart,
    candles: makeSeries(),
    volume: makeSeries(),
    toolbar,
    legend: makeElement(),
    container,
    formatTime: (t) => String(t),
  });
  tools.drawManager.viewport = tools._viewport();
  return tools;
}

// A trend line across the session gap, so the gap is in play for every test.
function addTrendLine(tools, startIndex = 15, endIndex = 25) {
  return tools._finalizeDrawing(
    "trend-line",
    [
      { time: BAR_TIMES[startIndex], price: yToPrice(priceToY(5000)) },
      { time: BAR_TIMES[endIndex], price: yToPrice(priceToY(5020)) },
    ],
    {},
  );
}

function addHLine(tools, price) {
  return tools._finalizeDrawing("horizontal-line", [{ time: BAR_TIMES[10], price }], {});
}

// The on-screen position of a pane point: this is what a real mouse event carries.
const clientAt = (pane) => ({ clientX: CONTAINER_LEFT + LEFT_AXIS_WIDTH + pane.x, clientY: CONTAINER_TOP + pane.y });

function midpointPane(drawing) {
  const a = { x: paneX(BAR_TIMES.indexOf(drawing.anchors[0].time)), y: priceToY(drawing.anchors[0].price) };
  const b = { x: paneX(BAR_TIMES.indexOf(drawing.anchors[1].time)), y: priceToY(drawing.anchors[1].price) };
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

test("a mouse event is converted to pane coordinates, not element coordinates", () => {
  const tools = makeTools();
  const point = tools._containerPoint({ clientX: CONTAINER_LEFT + LEFT_AXIS_WIDTH + 42, clientY: CONTAINER_TOP + 17 });
  assert.deepEqual(point, { x: 42, y: 17 });
  // The round trip the text editor relies on.
  assert.deepEqual(tools._paneToClient(point), { x: CONTAINER_LEFT + LEFT_AXIS_WIDTH + 42, y: CONTAINER_TOP + 17 });
});

test("right-clicking a trend line where it is drawn opens its menu and Delete removes it", () => {
  const tools = makeTools();
  const id = addTrendLine(tools);
  const drawing = tools.drawManager.drawings.get(id);

  let prevented = false;
  tools._handleContextMenu({ ...clientAt(midpointPane(drawing)), preventDefault: () => { prevented = true; } });

  assert.ok(prevented, "the chart's own menu should be suppressed for a drawing hit");
  assert.ok(tools.menuEl, "right-clicking the line should open the drawing menu");

  const deleteButton = flatten(tools.menuEl).find((el) => el.textContent === "Delete");
  assert.ok(deleteButton, "the drawing menu should offer Delete");
  deleteButton.onclick();
  assert.equal(tools.drawManager.drawings.has(id), false, "Delete should remove the drawing");
});

test("right-clicking empty space leaves the drawing alone but opens the chart's Lock menu", () => {
  const tools = makeTools();
  const id = addTrendLine(tools);
  const pane = midpointPane(tools.drawManager.drawings.get(id));

  let prevented = false;
  tools._handleContextMenu({ ...clientAt({ x: pane.x, y: pane.y + 120 }), preventDefault: () => { prevented = true; } });

  assert.ok(prevented);
  assert.ok(tools.menuEl, "empty-space right-click should open the chart's own menu");
  assert.equal(tools.drawManager.drawings.has(id), true, "the drawing itself is untouched");
  const lockButton = flatten(tools.menuEl).find((el) => el.textContent === "Lock");
  assert.ok(lockButton, "the chart menu should offer Lock");
});

test("a selected drawing suppresses the chart's Lock menu on empty space", () => {
  const tools = makeTools();
  const id = addTrendLine(tools);
  tools.drawManager.selectDrawing(id);
  const pane = midpointPane(tools.drawManager.drawings.get(id));
  tools._handleContextMenu({ ...clientAt({ x: pane.x, y: pane.y + 120 }), preventDefault: () => {} });
  assert.equal(tools.menuEl, null, "no chart menu while a drawing is selected");
});

test("Lock in the chart menu captures the time and price at the mouse position, not the live centre", () => {
  const tools = makeTools();
  const pane = { x: paneX(12), y: priceToY(5050) };

  tools._handleContextMenu({ ...clientAt(pane), preventDefault: () => {} });
  const lockButton = flatten(tools.menuEl).find((el) => el.textContent === "Lock");
  lockButton.onclick();

  assert.equal(tools._fvViewportLocked, true);
  assert.deepEqual(tools._fvLockedCentre, { time: BAR_TIMES[12], price: yToPrice(priceToY(5050)) });
  assert.equal(tools.menuEl, null, "the menu closes after Lock is chosen");
});

test("hovering the line offers the move cursor at the cursor's real position", () => {
  const tools = makeTools();
  const id = addTrendLine(tools);
  const pane = midpointPane(tools.drawManager.drawings.get(id));

  tools._handlePreviewMove(clientAt(pane));
  assert.equal(tools.container.style.cursor, "move");

  // Where the pre-fix code looked: one axis width to the right of the line.
  tools._handlePreviewMove({ clientX: CONTAINER_LEFT + LEFT_AXIS_WIDTH + pane.x + LEFT_AXIS_WIDTH, clientY: CONTAINER_TOP + pane.y + 200 });
  assert.equal(tools.container.style.cursor, "");
});

test("dragging a line across the session gap keeps every anchor on a real bar", () => {
  const tools = makeTools();
  // Straddling the break, so a shift measured in seconds cannot stay on the bar grid.
  const id = addTrendLine(tools, 19, 22);
  const drawing = tools.drawManager.drawings.get(id);
  const start = midpointPane(drawing);
  const shift = 3 * BAR_SPACING;

  // What the old code did: one time delta, read off the grab and release points, added
  // to every anchor. Across the break at least one anchor lands between bars, where
  // timeToCoordinate() returns null - and the line then neither renders nor hit-tests.
  const timeScale = tools.chart.timeScale();
  const naiveDelta = timeScale.coordinateToTime(start.x + shift) - timeScale.coordinateToTime(start.x);
  assert.ok(
    drawing.anchors.some((a) => !BAR_TIMES.includes(a.time + naiveDelta)),
    "the fixture must exercise the gap",
  );

  tools._handleDragStart({ button: 0, ...clientAt(start), preventDefault: () => {} });
  assert.ok(tools.dragState, "grabbing the line should start a move");

  tools._handleDragMove(clientAt({ x: start.x + shift, y: start.y + 20 }));
  tools._handleDragEnd();

  for (const anchor of drawing.anchors) {
    assert.ok(BAR_TIMES.includes(anchor.time), `anchor time ${anchor.time} is not a bar`);
  }
  assert.ok(drawing.isRenderable(tools._viewport()), "a moved line must still be drawable");
  assert.ok(drawing.testHit(midpointPane(drawing), tools._viewport()), "a moved line must still be hittable");
  assert.equal(BAR_TIMES.indexOf(drawing.anchors[0].time), 22, "the line should step three bars right");
  assert.equal(BAR_TIMES.indexOf(drawing.anchors[1].time), 25, "the line's span should survive the move");
});

test("a drag that runs off the end of the data holds the last good shape", () => {
  const tools = makeTools();
  const id = addTrendLine(tools, 30, 34);
  const drawing = tools.drawManager.drawings.get(id);
  const start = midpointPane(drawing);
  const before = drawing.anchors.map((a) => ({ ...a }));

  tools._handleDragStart({ button: 0, ...clientAt(start), preventDefault: () => {} });
  tools._handleDragMove(clientAt({ x: start.x + 50 * BAR_SPACING, y: start.y }));
  tools._handleDragEnd();

  assert.deepEqual(drawing.anchors, before);
  assert.ok(drawing.isRenderable(tools._viewport()));
});

test("a grab on an endpoint of a selected line is left to the plugin's resize drag", () => {
  const tools = makeTools();
  const id = addTrendLine(tools);
  const drawing = tools.drawManager.drawings.get(id);
  tools.drawManager.selectDrawing(id);

  const endpoint = { x: paneX(BAR_TIMES.indexOf(drawing.anchors[0].time)), y: priceToY(drawing.anchors[0].price) };
  tools._handleDragStart({ button: 0, ...clientAt(endpoint), preventDefault: () => {} });
  assert.equal(tools.dragState, null, "an endpoint grab is a resize, not a move");
});

test("the plugin's own manager is given the same corrected conversion", () => {
  const tools = makeTools();
  assert.deepEqual(
    tools.drawManager.getPointFromEvent({ clientX: CONTAINER_LEFT + LEFT_AXIS_WIDTH + 12, clientY: CONTAINER_TOP + 34 }),
    { x: 12, y: 34 },
  );
});

test("Delete removes the selected drawing, but not while a field has focus", () => {
  const tools = makeTools();
  const id = addTrendLine(tools);
  tools.drawManager.selectDrawing(id);
  const onKeyDown = documentKeydown.at(-1);

  onKeyDown({ key: "Backspace", target: { tagName: "INPUT" }, preventDefault: () => {} });
  assert.ok(tools.drawManager.drawings.has(id), "typing in a field must not delete a drawing");

  onKeyDown({ key: "Backspace", target: { isContentEditable: true }, preventDefault: () => {} });
  assert.ok(tools.drawManager.drawings.has(id));

  onKeyDown({ key: "Delete", target: { tagName: "BODY" }, preventDefault: () => {} });
  assert.equal(tools.drawManager.drawings.has(id), false);
  assert.deepEqual(tools.drawingIds, [], "the undo stack should drop it too");
});

test("Delete with nothing selected does nothing", () => {
  const tools = makeTools();
  const id = addTrendLine(tools);
  documentKeydown.at(-1)({ key: "Delete", target: { tagName: "BODY" }, preventDefault: () => {} });
  assert.ok(tools.drawManager.drawings.has(id));
});

// A mousedown on the price axis to drag-zoom the scale is the chart's own gesture, not
// a click in the pane. An h-line hit-tests on y alone (it spans the whole pane), so a
// zoom grab at a y that lines up with the line used to match anyway and hijack the
// zoom into a line move - reproducing Ruei's report: zooming the price (Y) axis with
// the mouse over the axis label area moved an existing h-line.
test("a drag-to-zoom grab on the price axis does not move an h-line at that y", () => {
  const tools = makeTools();
  const price = yToPrice(200);
  const id = addHLine(tools, price);
  const drawing = tools.drawManager.drawings.get(id);
  const before = drawing.anchors.map((a) => ({ ...a }));

  const paneWidth = tools.chart.timeScale().width();
  // Over the right price axis: same y as the line, x past the edge of the pane.
  const onAxis = { x: paneWidth + 20, y: 200 };
  tools._handleDragStart({ button: 0, ...clientAt(onAxis), preventDefault: () => {} });

  assert.equal(tools.dragState, null, "a grab on the price axis must not start a drawing move");
  tools._handleDragMove?.(clientAt({ x: onAxis.x, y: 260 }));
  assert.deepEqual(drawing.anchors, before, "the h-line must not have moved");
});

test("a drag inside the pane still moves an h-line", () => {
  const tools = makeTools();
  const price = yToPrice(200);
  const id = addHLine(tools, price);
  const drawing = tools.drawManager.drawings.get(id);

  tools._handleDragStart({ button: 0, ...clientAt({ x: 150, y: 200 }), preventDefault: () => {} });
  assert.ok(tools.dragState, "grabbing the line inside the pane should start a move");

  tools._handleDragMove(clientAt({ x: 150, y: 240 }));
  tools._handleDragEnd();

  assert.equal(drawing.anchors[0].price, yToPrice(240), "the line should follow the drag");
});

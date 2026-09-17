(() => {
  const Ctor = window.FutureViewChartTools;
  if (!Ctor) return;
  const p = Ctor.prototype;
  const DRAW_TOOLS = { trend: "trend-line", ray: "ray", hline: "horizontal-line", vline: "vertical-line", rect: "rectangle", fib: "fib-retracement", text: "text-annotation" };
  const TIMEFRAMES = new Set(["1", "5", "30", "240", "1D"]);
  const originalPreviewMove = p._handlePreviewMove;
  const originalClear = p._clearDrawings;
  const originalReset = p.reset;
  const originalAppend = p.append;
  const originalAppendMany = p.appendMany;

  const etFormatter = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });

  function normalizeRaw(raw) {
    return {
      t: Number(raw.t ?? raw.time),
      o: Number(raw.o ?? raw.open),
      h: Number(raw.h ?? raw.high),
      l: Number(raw.l ?? raw.low),
      c: Number(raw.c ?? raw.close),
      v: Number(raw.v ?? raw.volume),
    };
  }

  function etParts(seconds) {
    return Object.fromEntries(
      etFormatter.formatToParts(new Date(seconds * 1000))
        .filter((part) => part.type !== "literal")
        .map((part) => [part.type, Number(part.value)]),
    );
  }

  function wallToEpochSeconds(parts) {
    const wanted = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, 0);
    let guess = wanted;
    for (let i = 0; i < 4; i += 1) {
      const shown = etParts(guess / 1000);
      const shownWall = Date.UTC(shown.year, shown.month - 1, shown.day, shown.hour, shown.minute, 0);
      const delta = wanted - shownWall;
      guess += delta;
      if (!delta) break;
    }
    return Math.floor(guess / 1000);
  }

  function sessionStart(seconds) {
    const p = etParts(seconds);
    const local = new Date(Date.UTC(p.year, p.month - 1, p.day));
    if (p.hour < 18) local.setUTCDate(local.getUTCDate() - 1);
    return wallToEpochSeconds({
      year: local.getUTCFullYear(),
      month: local.getUTCMonth() + 1,
      day: local.getUTCDate(),
      hour: 18,
      minute: 0,
    });
  }

  function bucketTime(seconds, timeframe) {
    if (timeframe === "1") return seconds;
    if (timeframe === "1D") return sessionStart(seconds);
    const minutes = Number(timeframe);
    const start = sessionStart(seconds);
    const elapsed = Math.max(0, seconds - start);
    return start + Math.floor(elapsed / (minutes * 60)) * minutes * 60;
  }

  function aggregate(rawBars, timeframe) {
    if (timeframe === "1") return rawBars.map((bar) => ({ ...bar }));
    const out = [];
    let current = null;
    for (const bar of rawBars) {
      const t = bucketTime(bar.t, timeframe);
      if (!current || current.t !== t) {
        current = { t, o: bar.o, h: bar.h, l: bar.l, c: bar.c, v: bar.v };
        out.push(current);
      } else {
        current.h = Math.max(current.h, bar.h);
        current.l = Math.min(current.l, bar.l);
        current.c = bar.c;
        current.v += bar.v;
      }
    }
    return out;
  }

  function candle(bar) {
    return { time: bar.t, open: bar.o, high: bar.h, low: bar.l, close: bar.c };
  }

  function volume(bar) {
    return {
      time: bar.t,
      value: bar.v,
      color: bar.c >= bar.o ? "rgba(38,166,154,.46)" : "rgba(239,83,80,.46)",
    };
  }

  p._fvSyncTimeframeUi = function () {
    this.toolbar.querySelectorAll("button[data-timeframe]").forEach((button) => {
      const active = button.dataset.timeframe === this._fvTimeframe;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  };

  p._fvRenderTimeframe = function ({ preserveRange = true, fitVolume = false } = {}) {
    const ts = this.chart.timeScale();
    const visible = preserveRange ? ts.getVisibleRange?.() : null;
    const bars = aggregate(this._fvRawBars || [], this._fvTimeframe || "5");
    this.candles.setData(bars.map(candle));
    if (this.volume) this.volume.setData(bars.map(volume));
    originalReset.call(this, bars);
    if (visible) {
      try { ts.setVisibleRange(visible); } catch {}
    }
    if (fitVolume && this.volume) {
      const scale = this.volume.priceScale();
      try { scale.applyOptions({ autoScale: true }); } catch {}
      requestAnimationFrame(() => requestAnimationFrame(() => {
        try { scale.applyOptions({ autoScale: false }); } catch {}
      }));
    }
  };

  p._fvSetTimeframe = function (timeframe) {
    if (!TIMEFRAMES.has(timeframe) || timeframe === this._fvTimeframe) return;
    this._fvTimeframe = timeframe;
    this._fvSyncTimeframeUi();
    this._fvRenderTimeframe({ preserveRange: true, fitVolume: true });
  };

  p.reset = function (rawBars) {
    this._fvRawBars = (rawBars || []).map(normalizeRaw);
    this._fvRenderTimeframe({ preserveRange: false, fitVolume: false });
  };

  p.append = function (rawBar) {
    const bar = normalizeRaw(rawBar);
    const raw = this._fvRawBars || (this._fvRawBars = []);
    const last = raw.at(-1);
    if (last && bar.t === last.t) raw[raw.length - 1] = bar;
    else if (!last || bar.t > last.t) raw.push(bar);
    else return originalAppend.call(this, rawBar);
    this._fvRenderTimeframe({ preserveRange: true, fitVolume: false });
  };

  p.appendMany = function (rawBars) {
    const raw = this._fvRawBars || (this._fvRawBars = []);
    for (const item of rawBars || []) {
      const bar = normalizeRaw(item);
      const last = raw.at(-1);
      if (last && bar.t === last.t) raw[raw.length - 1] = bar;
      else if (!last || bar.t > last.t) raw.push(bar);
    }
    this._fvRenderTimeframe({ preserveRange: true, fitVolume: false });
  };

  p._syncDrawToolUi = function () {
    this.toolbar.querySelectorAll("button[data-tool]").forEach((button) => {
      const tool = button.dataset.tool;
      if (!(tool in DRAW_TOOLS)) return;
      const armed = this.activeDrawTool === tool;
      button.classList.toggle("armed", armed);
      button.setAttribute("aria-pressed", String(armed));
    });
  };

  p._armDrawTool = function (tool) {
    const wasArmed = this.activeDrawTool === tool;
    this._cancelDrawing();
    if (wasArmed) return;
    this.activeDrawTool = tool;
    this.pendingAnchors = [];
    this.interactionHandler = null;
    this.chart.applyOptions({ handleScroll: false, handleScale: false });
    this._syncDrawToolUi();
  };

  p._cancelDrawing = function () {
    this.activeDrawTool = null;
    this.pendingAnchors = [];
    this.interactionHandler = null;
    this.chart.applyOptions({ handleScroll: true, handleScale: true });
    this._clearPreview();
    this._closeEditor();
    this.container.style.cursor = "";
    this._syncDrawToolUi();
  };

  p._handleDrawClick = function (param) {
    if (this.editorEl || !this.activeDrawTool || !param?.point) return;
    const tool = this.activeDrawTool;
    if (tool === "hline" || tool === "vline") return;
    const registryType = DRAW_TOOLS[tool];
    if (!registryType) return;
    const anchor = this._anchorAtPoint(param.point);
    if (!anchor) return;
    if (tool === "text") {
      this._openTextEditor(param.point, "", (text) => {
        if (text) this._finalizeDrawing("text-annotation", [anchor], { text, backgroundColor: "transparent" });
        this._cancelDrawing();
      });
      return;
    }
    const def = this.registry.get(registryType);
    if (!def || def.requiredAnchors <= 1) {
      this._finalizeDrawing(registryType, [anchor], {});
      this._cancelDrawing();
      return;
    }
    this.pendingAnchors = this.pendingAnchors || [];
    this.pendingAnchors.push(anchor);
    if (this.pendingAnchors.length >= def.requiredAnchors) {
      const anchors = this.pendingAnchors.slice(0, def.requiredAnchors);
      this._finalizeDrawing(registryType, anchors, {});
      this._cancelDrawing();
    }
  };

  p._handlePreviewMove = function (event) {
    if (this.activeDrawTool && this.activeDrawTool !== "text") {
      const anchors = this.pendingAnchors || [];
      if (anchors.length) {
        const preview = this._anchorAtPoint(this._containerPoint(event));
        if (preview) this._renderPreview(DRAW_TOOLS[this.activeDrawTool], anchors, preview);
      }
      return;
    }
    return originalPreviewMove.call(this, event);
  };

  p._clearDrawings = function () {
    this._cancelDrawing();
    originalClear.call(this);
    this.previewId = null;
  };

  p.fit = function () {
    const priceScale = this.candles.priceScale();
    const volumeScale = this.volume ? this.volume.priceScale() : null;
    try { this.chart.timeScale().fitContent(); } catch {}
    try { priceScale.applyOptions({ autoScale: true }); } catch {}
    if (volumeScale) { try { volumeScale.applyOptions({ autoScale: true }); } catch {} }
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        try { priceScale.applyOptions({ autoScale: false }); } catch {}
        if (volumeScale) { try { volumeScale.applyOptions({ autoScale: false }); } catch {} }
      });
    });
  };

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    queueMicrotask(() => {
      const instance = window.__futureViewChartTools;
      if (instance?.activeDrawTool) instance._cancelDrawing();
    });
  }, true);

  document.addEventListener("click", (event) => {
    const button = event.target.closest?.("#start-btn, #random-btn");
    if (!button) return;
    const instance = window.__futureViewChartTools;
    if (instance) instance._clearDrawings();
  }, true);

  const Original = Ctor;
  window.FutureViewChartTools = class FutureViewChartToolsPatched extends Original {
    constructor(options) {
      super(options);
      this.pendingAnchors = [];
      this._fvTimeframe = "5";
      this._fvRawBars = [];

      try {
        this.chart.applyOptions({
          leftPriceScale: { visible: true, borderVisible: true },
          rightPriceScale: { visible: true, borderVisible: true },
        });
        this.volume?.applyOptions({ priceScaleId: "left" });
        this.volume?.priceScale().applyOptions({
          autoScale: false,
          scaleMargins: { top: 0.8, bottom: 0 },
        });
      } catch {}

      this.toolbar.addEventListener("click", (event) => {
        const button = event.target.closest?.("button[data-timeframe]");
        if (!button) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        this._fvSetTimeframe(button.dataset.timeframe);
      }, true);
      this._fvSyncTimeframeUi();

      let volumePan = null;
      const stopVolumePan = (event) => {
        if (!volumePan) return;
        if (event?.pointerId != null && volumePan.pointerId !== event.pointerId) return;
        try { this.container.releasePointerCapture?.(volumePan.pointerId); } catch {}
        volumePan = null;
        this.container.style.cursor = "";
      };
      this.container.addEventListener("pointerdown", (event) => {
        if (this.activeDrawTool || !this.volume) return;
        if (!(event.button === 1 || (event.button === 0 && event.shiftKey))) return;
        const scale = this.volume.priceScale();
        const width = Number(scale.width?.() || 0);
        const rect = this.container.getBoundingClientRect();
        const x = event.clientX - rect.left;
        if (width <= 0 || x < 0 || x > width) return;
        const range = scale.getVisibleRange?.();
        if (!range || !Number.isFinite(range.from) || !Number.isFinite(range.to)) return;
        volumePan = {
          pointerId: event.pointerId,
          startY: event.clientY,
          from: Number(range.from),
          to: Number(range.to),
          paneHeight: Math.max(1, rect.height),
        };
        try { scale.setAutoScale?.(false); } catch {}
        try { scale.applyOptions({ autoScale: false }); } catch {}
        try { this.container.setPointerCapture?.(event.pointerId); } catch {}
        this.container.style.cursor = "ns-resize";
        event.preventDefault();
        event.stopPropagation();
      }, true);
      this.container.addEventListener("pointermove", (event) => {
        if (!volumePan || event.pointerId !== volumePan.pointerId || !this.volume) return;
        const span = volumePan.to - volumePan.from;
        if (!(span > 0)) return;
        const delta = ((event.clientY - volumePan.startY) / volumePan.paneHeight) * span;
        try { this.volume.priceScale().setVisibleRange({ from: volumePan.from + delta, to: volumePan.to + delta }); } catch {}
        event.preventDefault();
        event.stopPropagation();
      }, true);
      this.container.addEventListener("pointerup", stopVolumePan, true);
      this.container.addEventListener("pointercancel", stopVolumePan, true);

      this.container.addEventListener("click", (event) => {
        const tool = this.activeDrawTool;
        if (tool !== "hline" && tool !== "vline") return;
        if (this.editorEl) return;
        const point = this._containerPoint(event);
        const anchor = this._anchorAtPoint(point);
        if (!anchor) return;
        this._finalizeDrawing(DRAW_TOOLS[tool], [anchor], {});
        this._cancelDrawing();
      }, true);

      this.toolbar.addEventListener("click", (event) => {
        const button = event.target.closest?.("button[data-tool]");
        const tool = button?.dataset.tool;
        if (!(tool in DRAW_TOOLS)) return;
        event.stopImmediatePropagation();
        this._armDrawTool(tool);
      }, true);

      this._syncDrawToolUi();
      window.__futureViewChartTools = this;
    }
  };
})();

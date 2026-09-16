(() => {
  const Ctor = window.FutureViewChartTools;
  if (!Ctor) return;
  const p = Ctor.prototype;
  const DRAW_TOOLS = { trend: "trend-line", ray: "ray", hline: "horizontal-line", vline: "vertical-line", rect: "rectangle", fib: "fib-retracement", text: "text-annotation" };
  const originalPreviewMove = p._handlePreviewMove;
  const originalClear = p._clearDrawings;

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
    if (tool === "hline" || tool === "vline") return; // handled directly by container click below
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

      // One-anchor tools are placed directly from the DOM click before Lightweight
      // Charts' subscribeClick callback runs. This avoids intermittent lost clicks/state
      // desynchronization observed with H-Line/V-Line while still using candle coordinates.
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

      // Ensure draw buttons have one authoritative state transition even if the base
      // toolbar listener also sees the click later in bubbling order.
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

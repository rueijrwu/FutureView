(() => {
  const Base = window.FutureViewChartTools;
  if (!Base) return;

  const DRAW_TOOLS = {
    trend: "trend-line",
    ray: "ray",
    hline: "horizontal-line",
    vline: "vertical-line",
    rect: "rectangle",
    fib: "fib-retracement",
    text: "text-annotation",
  };
  const originalPreviewMove = Base.prototype._handlePreviewMove;
  const originalClear = Base.prototype._clearDrawings;

  window.FutureViewChartTools = class FutureViewChartToolsInteractionFixes extends Base {
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

      // Own drawing activation in one capture-phase handler. The base toolbar handler
      // never sees these clicks, so a tool can only be armed/cancelled once.
      this.toolbar.addEventListener("click", (event) => {
        const button = event.target.closest?.("button[data-tool]");
        const tool = button?.dataset.tool;
        if (!(tool in DRAW_TOOLS)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        this._armDrawTool(tool);
      }, true);

      this._bindVolumePan();
      this._syncDrawToolUi();
      window.__futureViewChartTools = this;
    }

    _syncDrawToolUi() {
      this.toolbar.querySelectorAll("button[data-tool]").forEach((button) => {
        const tool = button.dataset.tool;
        if (!(tool in DRAW_TOOLS)) return;
        const armed = this.activeDrawTool === tool;
        button.classList.toggle("armed", armed);
        button.setAttribute("aria-pressed", String(armed));
      });
    }

    _armDrawTool(tool) {
      const wasArmed = this.activeDrawTool === tool;
      this._cancelDrawing();
      if (wasArmed) return;
      this.activeDrawTool = tool;
      this.pendingAnchors = [];
      this.interactionHandler = null;
      this.chart.applyOptions({ handleScroll: false, handleScale: false });
      this._syncDrawToolUi();
    }

    _cancelDrawing() {
      this.activeDrawTool = null;
      this.pendingAnchors = [];
      this.interactionHandler = null;
      this.chart.applyOptions({ handleScroll: true, handleScale: true });
      this._clearPreview();
      this._closeEditor();
      this.container.style.cursor = "";
      this._syncDrawToolUi();
    }

    _handleDrawClick(param) {
      if (this.editorEl || !this.activeDrawTool || !param?.point) return;
      const tool = this.activeDrawTool;
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

      this.pendingAnchors.push(anchor);
      if (this.pendingAnchors.length >= def.requiredAnchors) {
        this._finalizeDrawing(registryType, this.pendingAnchors.slice(0, def.requiredAnchors), {});
        this._cancelDrawing();
      }
    }

    _handlePreviewMove(event) {
      if (this.activeDrawTool && this.activeDrawTool !== "text") {
        if (this.pendingAnchors.length) {
          const preview = this._anchorAtPoint(this._containerPoint(event));
          if (preview) this._renderPreview(DRAW_TOOLS[this.activeDrawTool], this.pendingAnchors, preview);
        }
        return;
      }
      return originalPreviewMove.call(this, event);
    }

    _clearDrawings() {
      this._cancelDrawing();
      originalClear.call(this);
      this.previewId = null;
    }

    _bindVolumePan() {
      let pan = null;
      const stop = (event) => {
        if (!pan) return;
        if (event?.pointerId != null && pan.pointerId !== event.pointerId) return;
        try { this.container.releasePointerCapture?.(pan.pointerId); } catch {}
        pan = null;
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
        pan = {
          pointerId: event.pointerId,
          startY: event.clientY,
          from: Number(range.from),
          to: Number(range.to),
          paneHeight: Math.max(1, rect.height),
        };
        try { scale.applyOptions({ autoScale: false }); } catch {}
        try { this.container.setPointerCapture?.(event.pointerId); } catch {}
        this.container.style.cursor = "ns-resize";
        event.preventDefault();
        event.stopPropagation();
      }, true);

      this.container.addEventListener("pointermove", (event) => {
        if (!pan || event.pointerId !== pan.pointerId || !this.volume) return;
        const span = pan.to - pan.from;
        if (!(span > 0)) return;
        const delta = ((event.clientY - pan.startY) / pan.paneHeight) * span;
        try { this.volume.priceScale().setVisibleRange({ from: pan.from + delta, to: pan.to + delta }); } catch {}
        event.preventDefault();
        event.stopPropagation();
      }, true);
      this.container.addEventListener("pointerup", stop, true);
      this.container.addEventListener("pointercancel", stop, true);
    }
  };

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    queueMicrotask(() => window.__futureViewChartTools?._cancelDrawing?.());
  }, true);

  document.addEventListener("click", (event) => {
    if (!event.target.closest?.("#start-btn, #random-btn")) return;
    window.__futureViewChartTools?._clearDrawings?.();
  }, true);
})();

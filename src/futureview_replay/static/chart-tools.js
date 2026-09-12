(() => {
  const KC = window.klinecharts;

  // Single source of truth for chart colors is the CSS custom properties on :root
  // (see style.css). Nothing here should hardcode a hex value as a *default*; the
  // color pickers wired up below let the user override any of these at runtime.
  function readTheme() {
    const style = getComputedStyle(document.documentElement);
    const v = (name, fallback) => (style.getPropertyValue(name) || fallback).trim();
    return {
      bg: v("--chart-bg", "#090e15"),
      grid: v("--chart-grid", "#17202d"),
      text: v("--chart-text", "#aab5c5"),
      up: v("--chart-up", "#26a69a"),
      down: v("--chart-down", "#ef5350"),
      neutral: v("--chart-neutral", "#888888"),
      sma5: v("--chart-sma5", "#4da3ff"),
      sma10: v("--chart-sma10", "#34d399"),
      sma20: v("--chart-sma20", "#f0b90b"),
      sma60: v("--chart-sma60", "#ff8a3d"),
      vwap: v("--chart-vwap", "#bb86fc"),
      overlay: v("--chart-overlay", "#f0b90b"),
      overlayPoint: v("--chart-overlay-point", "#f0b90b"),
    };
  }
  const THEME = readTheme();
  window.FutureViewTheme = THEME;

  // Mutable, module-level so the indicator figures' styles() closures (registered once,
  // globally, below) always read the latest user-picked color rather than a frozen THEME
  // snapshot - this is what makes the per-indicator color pickers work.
  const colors = { sma5: THEME.sma5, sma10: THEME.sma10, sma20: THEME.sma20, sma60: THEME.sma60, vwap: THEME.vwap };

  const sessionFormatter = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  });

  function sessionKey(seconds) {
    const parts = Object.fromEntries(
      sessionFormatter.formatToParts(new Date(seconds * 1000))
        .filter((part) => part.type !== "literal")
        .map((part) => [part.type, part.value]),
    );
    const date = new Date(Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day)));
    if (Number(parts.hour) >= 18) date.setUTCDate(date.getUTCDate() + 1);
    return date.toISOString().slice(0, 10);
  }

  function sma(period, key) {
    return (dataList) => {
      let sum = 0;
      return dataList.map((bar, index) => {
        sum += bar.close;
        if (index >= period) sum -= dataList[index - period].close;
        if (index < period - 1) return {};
        return { [key]: sum / period };
      });
    };
  }

  function vwap(dataList) {
    let session = null;
    let cumulativePriceVolume = 0;
    let cumulativeVolume = 0;
    return dataList.map((bar) => {
      const key = sessionKey(bar.timestamp / 1000);
      if (key !== session) {
        session = key;
        cumulativePriceVolume = 0;
        cumulativeVolume = 0;
      }
      const typical = (bar.high + bar.low + bar.close) / 3;
      cumulativePriceVolume += typical * (bar.volume || 0);
      cumulativeVolume += bar.volume || 0;
      if (cumulativeVolume <= 0) return {};
      return { vwap: cumulativePriceVolume / cumulativeVolume };
    });
  }

  // key -> {period, label} for the SMA family; VWAP is handled separately (no period).
  const SMA_INDICATORS = {
    sma5: { period: 5, label: "SMA5" },
    sma10: { period: 10, label: "SMA10" },
    sma20: { period: 20, label: "SMA20" },
    sma60: { period: 60, label: "SMA60" },
  };
  const INDICATOR_LABELS = { ...Object.fromEntries(Object.entries(SMA_INDICATORS).map(([k, v]) => [k, v.label])), vwap: "VWAP" };

  function indicatorFigure(key) {
    // styles() runs at every draw, so reading colors[key] here (not a captured constant)
    // is what makes chart.overrideIndicator's recolor take effect immediately.
    return { key, title: `${INDICATOR_LABELS[key]} `, type: "line", styles: () => ({ style: "solid", size: 2, color: colors[key], dashedValue: [] }) };
  }

  let registered = false;
  function registerAll() {
    if (registered) return;
    registered = true;
    Object.entries(SMA_INDICATORS).forEach(([key, { period }]) => {
      KC.registerIndicator({ name: `FV_${key.toUpperCase()}`, shortName: INDICATOR_LABELS[key], figures: [indicatorFigure(key)], calc: sma(period, key) });
    });
    KC.registerIndicator({ name: "FV_VWAP", shortName: "VWAP", figures: [indicatorFigure("vwap")], calc: vwap });

    // klinecharts ships no rectangle or freeform-text overlay - "rect"/"circle"/"text" are
    // figure *primitives*, not overlay names, so createOverlay({name:"rect"}) silently no-ops.
    // Registering these two custom overlays is what makes Rect and Text actually draw.
    KC.registerOverlay({
      name: "fvRect",
      totalStep: 3,
      needDefaultPointFigure: true,
      needDefaultXAxisFigure: true,
      needDefaultYAxisFigure: true,
      createPointFigures: ({ coordinates }) => {
        if (coordinates.length < 2) return [];
        const [p1, p2] = coordinates;
        return [{ type: "rect", attrs: { x: Math.min(p1.x, p2.x), y: Math.min(p1.y, p2.y), width: Math.abs(p2.x - p1.x), height: Math.abs(p2.y - p1.y) } }];
      },
    });
    KC.registerOverlay({
      name: "fvText",
      totalStep: 2,
      needDefaultPointFigure: false,
      needDefaultXAxisFigure: false,
      needDefaultYAxisFigure: false,
      createPointFigures: ({ overlay, coordinates }) => {
        const text = typeof overlay.extendData === "string" ? overlay.extendData : "";
        if (!text) return [];
        return [{ type: "text", attrs: { x: coordinates[0].x, y: coordinates[0].y, text }, styles: { color: THEME.text, backgroundColor: overlay.styles?.text?.backgroundColor ?? THEME.overlay } }];
      },
    });
  }

  const DRAW_TOOLS = {
    trend: "segment",
    ray: "rayLine",
    hline: "horizontalStraightLine",
    vline: "verticalStraightLine",
    rect: "fvRect",
    fib: "fibonacciLine",
    text: "fvText",
  };

  class FutureViewChartTools {
    constructor({ chart, toolbar, legend, formatTime }) {
      registerAll();
      this.chart = chart;
      this.toolbar = toolbar;
      this.legend = legend;
      this.formatTime = formatTime;
      this.activeIndicators = { sma5: false, sma10: false, sma20: false, sma60: false, vwap: false };
      this.overlayIds = [];
      this.overlayMode = KC.OverlayMode.Normal;
      this.drawColor = THEME.overlay;
      this.logScale = false;
      this._bind();
      this._initColorInputs();
      this._observeResize();
      this._showLegend(null);
    }

    // klinecharts only watches the canvas for pixel-ratio changes, so container
    // reflow (window resize, the mobile breakpoint) needs an explicit resize().
    _observeResize() {
      const container = this.chart.getDom();
      if (!container || typeof ResizeObserver === "undefined") return;
      this.resizeObserver = new ResizeObserver(() => this.chart.resize());
      this.resizeObserver.observe(container);
    }

    _bind() {
      this.toolbar.addEventListener("click", (event) => {
        const button = event.target.closest("button[data-tool]");
        if (!button) return;
        const tool = button.dataset.tool;
        if (tool in this.activeIndicators) this._toggleIndicator(tool, button);
        else if (tool === "text") this._drawText();
        else if (tool in DRAW_TOOLS) this._draw(tool);
        else if (tool === "magnet") this._toggleMagnet(button);
        else if (tool === "undo") this._undoOverlay();
        else if (tool === "clear") this._clearOverlays();
        else if (tool === "zoom-in") this.chart.zoomAtCoordinate(1.4);
        else if (tool === "zoom-out") this.chart.zoomAtCoordinate(1 / 1.4);
        else if (tool === "fit") this._fit();
        else if (tool === "latest") this.chart.scrollToRealTime();
        else if (tool === "log") this._toggleLog(button);
      });
      this.toolbar.addEventListener("input", (event) => {
        const indicatorInput = event.target.closest("input[type=color][data-indicator-color]");
        if (indicatorInput) return this._setIndicatorColor(indicatorInput.dataset.indicatorColor, indicatorInput.value);
        if (event.target.id === "draw-color") this.drawColor = event.target.value;
      });
      this.chart.subscribeAction(KC.ActionType.OnCrosshairChange, (crosshair) => this._showLegend(crosshair));
    }

    _initColorInputs() {
      this.toolbar.querySelectorAll("input[type=color][data-indicator-color]").forEach((input) => {
        input.value = colors[input.dataset.indicatorColor] || THEME.overlay;
      });
      const drawColorInput = this.toolbar.querySelector("#draw-color");
      if (drawColorInput) drawColorInput.value = this.drawColor;
    }

    _toggleIndicator(name, button) {
      const visible = !this.activeIndicators[name];
      this.activeIndicators[name] = visible;
      button.classList.toggle("active", visible);
      button.setAttribute("aria-pressed", String(visible));
      const indicatorName = `FV_${name.toUpperCase()}`;
      // isStack:true is required - klinecharts wipes every other indicator on a pane when isStack is false.
      if (visible) this.chart.createIndicator(indicatorName, true, { id: "candle_pane" });
      else this.chart.removeIndicator("candle_pane", indicatorName);
    }

    _setIndicatorColor(key, color) {
      colors[key] = color;
      // Forces a redraw with the new color; the figures' styles() closures already read
      // the updated `colors` object, so re-supplying the same figure definition is enough.
      this.chart.overrideIndicator({ name: `FV_${key.toUpperCase()}`, figures: [indicatorFigure(key)] }, "candle_pane");
    }

    _overlayStyles() {
      return {
        line: { color: this.drawColor },
        point: { color: this.drawColor, borderColor: this.drawColor },
        rect: { color: `${this.drawColor}33`, borderColor: this.drawColor },
        text: { color: THEME.text, backgroundColor: this.drawColor },
      };
    }

    _draw(tool) {
      const id = this.chart.createOverlay({ name: DRAW_TOOLS[tool], mode: this.overlayMode, styles: this._overlayStyles() });
      if (id) this.overlayIds.push(id);
    }

    _drawText() {
      const text = window.prompt("Annotation text:");
      if (!text) return;
      const id = this.chart.createOverlay({ name: "fvText", mode: this.overlayMode, extendData: text, styles: this._overlayStyles() });
      if (id) this.overlayIds.push(id);
    }

    _toggleMagnet(button) {
      const magnet = this.overlayMode !== KC.OverlayMode.WeakMagnet;
      this.overlayMode = magnet ? KC.OverlayMode.WeakMagnet : KC.OverlayMode.Normal;
      button.classList.toggle("active", magnet);
      button.setAttribute("aria-pressed", String(magnet));
    }

    _undoOverlay() {
      const id = this.overlayIds.pop();
      if (id) this.chart.removeOverlay(id);
    }

    _clearOverlays() {
      this.chart.removeOverlay();
      this.overlayIds = [];
    }

    _toggleLog(button) {
      this.logScale = !this.logScale;
      button.classList.toggle("active", this.logScale);
      button.setAttribute("aria-pressed", String(this.logScale));
      this.chart.setPaneOptions({ id: "candle_pane", axisOptions: { name: this.logScale ? "log" : "normal" } });
      button.textContent = this.logScale ? "Log" : "Linear";
    }

    _fit() {
      const dataList = this.chart.getDataList();
      if (!dataList.length) return;
      const size = this.chart.getSize("candle_pane");
      const width = (size && size.width) || 800;
      const space = Math.max(3, Math.min(30, width / dataList.length));
      this.chart.setBarSpace(space);
      this.chart.scrollToDataIndex(dataList.length - 1);
    }

    _showLegend(crosshair) {
      let bar = crosshair && crosshair.kLineData;
      if (!bar) {
        const dataList = this.chart.getDataList();
        bar = dataList.at(-1) || null;
      }
      if (!bar) {
        this.legend.textContent = "O —  H —  L —  C —  V —";
        return;
      }
      const time = Math.round(bar.timestamp / 1000);
      this.legend.textContent = `${this.formatTime(time)}  O ${Number(bar.open).toFixed(2)}  H ${Number(bar.high).toFixed(2)}  L ${Number(bar.low).toFixed(2)}  C ${Number(bar.close).toFixed(2)}  V ${Number(bar.volume || 0).toLocaleString()}`;
    }

    reset() {
      this._showLegend(null);
    }

    append() {
      this._showLegend(null);
    }

    appendMany() {
      this._showLegend(null);
    }
  }

  window.FutureViewChartTools = FutureViewChartTools;
})();

(() => {
  const KC = window.klinecharts;

  // Single source of truth for chart colors is the CSS custom properties on :root
  // (see style.css). Nothing here should hardcode a hex value.
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
      sma20: v("--chart-sma20", "#4da3ff"),
      sma50: v("--chart-sma50", "#f0b90b"),
      vwap: v("--chart-vwap", "#bb86fc"),
      overlay: v("--chart-overlay", "#f0b90b"),
      overlayPoint: v("--chart-overlay-point", "#f0b90b"),
    };
  }
  // Assumes 6-digit hex (fills get an alpha suffix appended below) - keep --chart-* values hex.
  const THEME = readTheme();
  window.FutureViewTheme = THEME;
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

  let indicatorsRegistered = false;
  function registerIndicators() {
    if (indicatorsRegistered) return;
    indicatorsRegistered = true;
    KC.registerIndicator({
      name: "FV_SMA20",
      shortName: "SMA20",
      figures: [{ key: "sma20", title: "SMA20 ", type: "line", styles: () => ({ style: "solid", size: 2, color: THEME.sma20, dashedValue: [] }) }],
      calc: sma(20, "sma20"),
    });
    KC.registerIndicator({
      name: "FV_SMA50",
      shortName: "SMA50",
      figures: [{ key: "sma50", title: "SMA50 ", type: "line", styles: () => ({ style: "solid", size: 2, color: THEME.sma50, dashedValue: [] }) }],
      calc: sma(50, "sma50"),
    });
    KC.registerIndicator({
      name: "FV_VWAP",
      shortName: "VWAP",
      figures: [{ key: "vwap", title: "VWAP ", type: "line", styles: () => ({ style: "solid", size: 2, color: THEME.vwap, dashedValue: [] }) }],
      calc: vwap,
    });
  }

  const DRAW_TOOLS = {
    trend: "segment",
    ray: "rayLine",
    hline: "horizontalStraightLine",
    vline: "verticalStraightLine",
    rect: "rect",
    circle: "circle",
    fib: "fibonacciLine",
    channel: "parallelStraightLine",
    text: "text",
  };

  class FutureViewChartTools {
    constructor({ chart, toolbar, legend, formatTime }) {
      registerIndicators();
      this.chart = chart;
      this.toolbar = toolbar;
      this.legend = legend;
      this.formatTime = formatTime;
      this.activeIndicators = { sma20: false, sma50: false, vwap: false };
      this.overlayIds = [];
      this.overlayMode = KC.OverlayMode.Normal;
      this.logScale = false;
      this._bind();
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
      this.chart.subscribeAction(KC.ActionType.OnCrosshairChange, (crosshair) => this._showLegend(crosshair));
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

    _draw(tool) {
      const id = this.chart.createOverlay({
        name: DRAW_TOOLS[tool],
        mode: this.overlayMode,
        styles: {
          line: { color: THEME.overlay },
          point: { color: THEME.overlayPoint, borderColor: THEME.overlay },
          rect: { color: `${THEME.overlay}33`, borderColor: THEME.overlay },
          circle: { color: `${THEME.overlay}33`, borderColor: THEME.overlay },
          text: { color: THEME.text, backgroundColor: THEME.overlay },
        },
      });
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

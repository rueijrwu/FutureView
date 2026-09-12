(() => {
  const TV = window.LightweightCharts;
  const LCD = window.LightweightChartsDrawing;
  const sessionFormatter = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  });

  // Single source of truth for chart colors is the CSS custom properties on :root
  // (see style.css). Nothing here should hardcode a hex value as a *default*; the
  // color pickers wired up below let the user override any of these at runtime.
  function readTheme() {
    const style = getComputedStyle(document.documentElement);
    const v = (name, fallback) => (style.getPropertyValue(name) || fallback).trim();
    return {
      sma5: v("--chart-sma5", "#4da3ff"),
      sma10: v("--chart-sma10", "#34d399"),
      sma20: v("--chart-sma20", "#f0b90b"),
      sma60: v("--chart-sma60", "#ff8a3d"),
      vwap: v("--chart-vwap", "#bb86fc"),
      overlay: v("--chart-overlay", "#f0b90b"),
    };
  }
  const THEME = readTheme();

  function normalize(raw) {
    return {
      time: Number(raw.t ?? raw.time),
      open: Number(raw.o ?? raw.open),
      high: Number(raw.h ?? raw.high),
      low: Number(raw.l ?? raw.low),
      close: Number(raw.c ?? raw.close),
      volume: Number(raw.v ?? raw.volume),
    };
  }

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

  // period-based SMAs the toolbar exposes, plus VWAP (session-anchored, no period)
  const SMA_PERIODS = { sma5: 5, sma10: 10, sma20: 20, sma60: 60 };

  // Draw-tool button -> lightweight-charts-drawing registry type name.
  const DRAW_TOOLS = {
    trend: "trend-line",
    ray: "ray",
    hline: "horizontal-line",
    vline: "vertical-line",
    rect: "rectangle",
    fib: "fib-retracement",
    text: "text-annotation",
  };

  class FutureViewChartTools {
    constructor({ chart, candles, volume, toolbar, legend, container, formatTime }) {
      this.chart = chart;
      this.candles = candles;
      this.volume = volume;
      this.toolbar = toolbar;
      this.legend = legend;
      this.formatTime = formatTime;
      this.bars = [];
      this.logScale = false;
      this.magnet = false;
      this.vwapSession = null;
      this.vwapPriceVolume = 0;
      this.vwapVolume = 0;
      this.indicatorColors = { sma5: THEME.sma5, sma10: THEME.sma10, sma20: THEME.sma20, sma60: THEME.sma60, vwap: THEME.vwap };
      this.indicators = {};
      Object.keys(this.indicatorColors).forEach((key) => {
        this.indicators[key] = chart.addSeries(TV.LineSeries, this._lineOptions(this.indicatorColors[key], 2));
      });
      Object.values(this.indicators).forEach((series) => series.applyOptions({ visible: false }));

      // Drawing tools: lightweight-charts ships no click-to-draw glue for its own
      // primitives, so DrawingManager only wires selection/drag-editing on attach();
      // the "click toolbar button, click chart, tool appears" flow below is ours.
      this.drawManager = new LCD.DrawingManager();
      this.drawManager.attach(chart, candles, container);
      this.registry = LCD.getToolRegistry();
      this.drawColor = THEME.overlay;
      this.activeDrawTool = null;
      this.pendingAnchors = [];
      this.drawingIds = [];
      this.pendingText = null;

      this._bind();
      this._showLegend(null);
    }

    _lineOptions(color, lineWidth) {
      return {
        color,
        lineWidth,
        crosshairMarkerVisible: false,
        lastValueVisible: true,
        priceLineVisible: false,
      };
    }

    _bind() {
      this.toolbar.addEventListener("click", (event) => {
        const button = event.target.closest("button[data-tool]");
        if (!button) return;
        const tool = button.dataset.tool;
        if (tool in this.indicators) this._toggleIndicator(tool, button);
        else if (tool === "crosshair") this._toggleCrosshair(button);
        else if (tool in DRAW_TOOLS) this._armDrawTool(tool, button);
        else if (tool === "undo") this._undoDrawing();
        else if (tool === "clear") this._clearDrawings();
        else if (tool === "zoom-in") this._zoom(0.72);
        else if (tool === "zoom-out") this._zoom(1.38);
        else if (tool === "fit") this.chart.timeScale().fitContent();
        else if (tool === "latest") this.chart.timeScale().scrollToRealTime();
        else if (tool === "log") this._toggleLog(button);
      });
      this.toolbar.addEventListener("input", (event) => {
        const indicatorInput = event.target.closest("input[type=color][data-indicator-color]");
        if (indicatorInput) return this._setIndicatorColor(indicatorInput.dataset.indicatorColor, indicatorInput.value);
        if (event.target.id === "draw-color") this.drawColor = event.target.value;
      });
      this.toolbar.querySelectorAll("input[type=color][data-indicator-color]").forEach((input) => {
        input.value = this.indicatorColors[input.dataset.indicatorColor];
      });
      const drawColorInput = this.toolbar.querySelector("#draw-color");
      if (drawColorInput) drawColorInput.value = this.drawColor;

      this.chart.subscribeClick((param) => this._handleDrawClick(param));
      this.chart.subscribeCrosshairMove((param) => this._showLegend(param));
    }

    _toggleIndicator(name, button) {
      const visible = !button.classList.contains("active");
      button.classList.toggle("active", visible);
      button.setAttribute("aria-pressed", String(visible));
      this.indicators[name].applyOptions({ visible });
    }

    _setIndicatorColor(key, color) {
      this.indicatorColors[key] = color;
      this.indicators[key].applyOptions({ color });
    }

    _toggleCrosshair(button) {
      this.magnet = !this.magnet;
      button.classList.toggle("active", this.magnet);
      button.setAttribute("aria-pressed", String(this.magnet));
      this.chart.applyOptions({
        crosshair: { mode: this.magnet ? TV.CrosshairMode.Magnet : TV.CrosshairMode.Normal },
      });
    }

    _armDrawTool(tool, button) {
      const wasArmed = this.activeDrawTool === tool;
      this.toolbar.querySelectorAll("button[data-tool].armed").forEach((b) => b.classList.remove("armed"));
      this.pendingAnchors = [];
      if (wasArmed) {
        this.activeDrawTool = null;
        return;
      }
      if (tool === "text") {
        const text = window.prompt("Annotation text:");
        if (!text) return;
        this.pendingText = text;
      }
      this.activeDrawTool = tool;
      button.classList.add("armed");
    }

    _handleDrawClick(param) {
      if (!this.activeDrawTool || !param.time || !param.point) return;
      const price = this.candles.coordinateToPrice(param.point.y);
      if (price == null || !Number.isFinite(price)) return;
      this.pendingAnchors.push({ time: param.time, price });

      const registryType = DRAW_TOOLS[this.activeDrawTool];
      const def = this.registry.get(registryType);
      if (this.pendingAnchors.length < def.requiredAnchors) return;

      const id = `fv_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
      const style = { lineColor: this.drawColor, lineWidth: 2, fillColor: `${this.drawColor}33` };
      const options = this.pendingText ? { text: this.pendingText } : {};
      const drawing = this.registry.createDrawing(registryType, id, this.pendingAnchors, style, options);
      this.drawManager.addDrawing(drawing);
      this.drawingIds.push(id);

      this.pendingAnchors = [];
      this.pendingText = null;
      this.activeDrawTool = null;
      this.toolbar.querySelectorAll("button[data-tool].armed").forEach((b) => b.classList.remove("armed"));
    }

    _undoDrawing() {
      const id = this.drawingIds.pop();
      if (id) this.drawManager.removeDrawing(id);
    }

    _clearDrawings() {
      this.drawManager.clearAll();
      this.drawingIds = [];
    }

    _toggleLog(button) {
      this.logScale = !this.logScale;
      button.classList.toggle("active", this.logScale);
      button.setAttribute("aria-pressed", String(this.logScale));
      this.candles.priceScale().applyOptions({
        mode: this.logScale ? TV.PriceScaleMode.Logarithmic : TV.PriceScaleMode.Normal,
      });
      button.textContent = this.logScale ? "Log" : "Linear";
    }

    _zoom(factor) {
      const range = this.chart.timeScale().getVisibleLogicalRange();
      if (!range) return this.chart.timeScale().fitContent();
      const center = (range.from + range.to) / 2;
      const half = Math.max(5, ((range.to - range.from) * factor) / 2);
      this.chart.timeScale().setVisibleLogicalRange({ from: center - half, to: center + half });
    }

    _showLegend(param) {
      let bar = null;
      let volume = null;
      if (param?.time != null && param.seriesData) {
        bar = param.seriesData.get(this.candles) ?? null;
        volume = param.seriesData.get(this.volume)?.value ?? null;
      }
      if (!bar && this.bars.length) {
        bar = this.bars.at(-1);
        volume = bar.volume;
      }
      if (!bar) {
        this.legend.textContent = "O —  H —  L —  C —  V —";
        return;
      }
      const time = Number(param?.time ?? bar.time);
      this.legend.textContent = `${this.formatTime(time)}  O ${Number(bar.open).toFixed(2)}  H ${Number(bar.high).toFixed(2)}  L ${Number(bar.low).toFixed(2)}  C ${Number(bar.close).toFixed(2)}  V ${Number(volume ?? 0).toLocaleString()}`;
    }

    _indicatorData() {
      const series = { sma5: [], sma10: [], sma20: [], sma60: [] };
      const sums = { sma5: 0, sma10: 0, sma20: 0, sma60: 0 };
      const vwap = [];
      let currentSession = null;
      let cumulativePriceVolume = 0;
      let cumulativeVolume = 0;
      this.bars.forEach((bar, index) => {
        Object.entries(SMA_PERIODS).forEach(([key, period]) => {
          sums[key] += bar.close;
          if (index >= period) sums[key] -= this.bars[index - period].close;
          if (index >= period - 1) series[key].push({ time: bar.time, value: sums[key] / period });
        });
        const key = sessionKey(bar.time);
        if (key !== currentSession) {
          currentSession = key;
          cumulativePriceVolume = 0;
          cumulativeVolume = 0;
        }
        const typical = (bar.high + bar.low + bar.close) / 3;
        cumulativePriceVolume += typical * bar.volume;
        cumulativeVolume += bar.volume;
        if (cumulativeVolume > 0) vwap.push({ time: bar.time, value: cumulativePriceVolume / cumulativeVolume });
      });
      this.vwapSession = currentSession;
      this.vwapPriceVolume = cumulativePriceVolume;
      this.vwapVolume = cumulativeVolume;
      return { ...series, vwap };
    }

    _refreshIndicators() {
      const data = this._indicatorData();
      Object.entries(data).forEach(([name, values]) => this.indicators[name].setData(values));
    }

    reset(rawBars) {
      this.bars = rawBars.map(normalize);
      this._refreshIndicators();
      this._showLegend(null);
    }

    append(rawBar) {
      const replaced = this._appendNormalized(normalize(rawBar));
      if (replaced) this._refreshIndicators();
      else this._updateIndicatorsForLastBar();
      this._showLegend(null);
    }

    appendMany(rawBars) {
      let rebuild = false;
      rawBars.map(normalize).forEach((bar) => {
        const replaced = this._appendNormalized(bar);
        if (replaced) rebuild = true;
        else if (!rebuild) this._updateIndicatorsForLastBar();
      });
      if (rebuild) this._refreshIndicators();
      this._showLegend(null);
    }

    _appendNormalized(bar) {
      const last = this.bars.at(-1);
      if (last && bar.time < last.time) return true;
      if (last && bar.time === last.time) {
        this.bars[this.bars.length - 1] = bar;
        return true;
      }
      this.bars.push(bar);
      return false;
    }

    _updateIndicatorsForLastBar() {
      const bar = this.bars.at(-1);
      if (!bar) return;
      Object.entries(SMA_PERIODS).forEach(([key, period]) => {
        if (this.bars.length < period) return;
        const values = this.bars.slice(-period);
        this.indicators[key].update({ time: bar.time, value: values.reduce((sum, item) => sum + item.close, 0) / period });
      });
      const key = sessionKey(bar.time);
      if (key !== this.vwapSession) {
        this.vwapSession = key;
        this.vwapPriceVolume = 0;
        this.vwapVolume = 0;
      }
      this.vwapPriceVolume += ((bar.high + bar.low + bar.close) / 3) * bar.volume;
      this.vwapVolume += bar.volume;
      if (this.vwapVolume > 0) {
        this.indicators.vwap.update({ time: bar.time, value: this.vwapPriceVolume / this.vwapVolume });
      }
    }
  }

  window.FutureViewChartTools = FutureViewChartTools;
})();

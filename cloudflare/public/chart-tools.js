(() => {
  const TV = window.LightweightCharts;
  const sessionFormatter = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    hourCycle: "h23",
  });

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

  class FutureViewChartTools {
    constructor({ chart, candles, volume, toolbar, legend, formatTime }) {
      this.chart = chart;
      this.candles = candles;
      this.volume = volume;
      this.toolbar = toolbar;
      this.legend = legend;
      this.formatTime = formatTime;
      this.bars = [];
      this.priceLines = [];
      this.hLineArmed = false;
      this.logScale = false;
      this.magnet = false;
      this.vwapSession = null;
      this.vwapPriceVolume = 0;
      this.vwapVolume = 0;
      this.indicators = {
        sma20: chart.addSeries(TV.LineSeries, this._lineOptions("#4da3ff", 2)),
        sma50: chart.addSeries(TV.LineSeries, this._lineOptions("#f0b90b", 2)),
        vwap: chart.addSeries(TV.LineSeries, this._lineOptions("#bb86fc", 2)),
      };
      Object.values(this.indicators).forEach((series) => series.applyOptions({ visible: false }));
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
        else if (tool === "hline") this._armHorizontalLine(button);
        else if (tool === "undo") this._undoLine();
        else if (tool === "clear") this._clearLines();
        else if (tool === "zoom-in") this._zoom(0.72);
        else if (tool === "zoom-out") this._zoom(1.38);
        else if (tool === "fit") this.chart.timeScale().fitContent();
        else if (tool === "latest") this.chart.timeScale().scrollToRealTime();
        else if (tool === "log") this._toggleLog(button);
      });
      this.chart.subscribeClick((param) => this._placeHorizontalLine(param));
      this.chart.subscribeCrosshairMove((param) => this._showLegend(param));
    }

    _toggleIndicator(name, button) {
      const visible = !button.classList.contains("active");
      button.classList.toggle("active", visible);
      button.setAttribute("aria-pressed", String(visible));
      this.indicators[name].applyOptions({ visible });
    }

    _toggleCrosshair(button) {
      this.magnet = !this.magnet;
      button.classList.toggle("active", this.magnet);
      button.setAttribute("aria-pressed", String(this.magnet));
      this.chart.applyOptions({
        crosshair: { mode: this.magnet ? TV.CrosshairMode.Magnet : TV.CrosshairMode.Normal },
      });
    }

    _armHorizontalLine(button) {
      this.hLineArmed = !this.hLineArmed;
      button.classList.toggle("armed", this.hLineArmed);
      button.setAttribute("aria-pressed", String(this.hLineArmed));
    }

    _placeHorizontalLine(param) {
      if (!this.hLineArmed || !param.point) return;
      const price = this.candles.coordinateToPrice(param.point.y);
      if (price == null || !Number.isFinite(price)) return;
      this.priceLines.push(this.candles.createPriceLine({
        price,
        color: "#f0b90b",
        lineWidth: 1,
        lineStyle: TV.LineStyle.Dashed,
        axisLabelVisible: true,
        title: "H-Line",
      }));
      this.hLineArmed = false;
      const button = this.toolbar.querySelector('[data-tool="hline"]');
      button.classList.remove("armed");
      button.setAttribute("aria-pressed", "false");
    }

    _undoLine() {
      const line = this.priceLines.pop();
      if (line) this.candles.removePriceLine(line);
    }

    _clearLines() {
      this.priceLines.forEach((line) => this.candles.removePriceLine(line));
      this.priceLines = [];
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
      const sma20 = [];
      const sma50 = [];
      const vwap = [];
      let sum20 = 0;
      let sum50 = 0;
      let currentSession = null;
      let cumulativePriceVolume = 0;
      let cumulativeVolume = 0;
      this.bars.forEach((bar, index) => {
        sum20 += bar.close;
        sum50 += bar.close;
        if (index >= 20) sum20 -= this.bars[index - 20].close;
        if (index >= 50) sum50 -= this.bars[index - 50].close;
        if (index >= 19) sma20.push({ time: bar.time, value: sum20 / 20 });
        if (index >= 49) sma50.push({ time: bar.time, value: sum50 / 50 });
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
      return { sma20, sma50, vwap };
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
      if (this.bars.length >= 20) {
        const values = this.bars.slice(-20);
        this.indicators.sma20.update({ time: bar.time, value: values.reduce((sum, item) => sum + item.close, 0) / 20 });
      }
      if (this.bars.length >= 50) {
        const values = this.bars.slice(-50);
        this.indicators.sma50.update({ time: bar.time, value: values.reduce((sum, item) => sum + item.close, 0) / 50 });
      }
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

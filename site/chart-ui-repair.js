(() => {
  const Base = window.FutureViewChartTools;
  if (!Base) return;

  const TIMEFRAMES = new Set(["1", "5", "30", "240", "1D"]);
  const RAW_TAIL_LIMIT = 1500;
  const etFormatter = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
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
      etFormatter.formatToParts(new Date(Number(seconds) * 1000))
        .filter((part) => part.type !== "literal")
        .map((part) => [part.type, Number(part.value)]),
    );
  }

  function wallToEpochSeconds(parts) {
    const wanted = Date.UTC(
      Number(parts.year),
      Number(parts.month) - 1,
      Number(parts.day),
      Number(parts.hour ?? 0),
      Number(parts.minute ?? 0),
      Number(parts.second ?? 0),
    );
    let guess = wanted;
    for (let i = 0; i < 4; i += 1) {
      const shown = etParts(guess / 1000);
      const shownWall = Date.UTC(shown.year, shown.month - 1, shown.day, shown.hour, shown.minute, shown.second || 0);
      const delta = wanted - shownWall;
      guess += delta;
      if (!delta) break;
    }
    return Math.floor(guess / 1000);
  }

  function sessionStart(seconds) {
    const parts = etParts(seconds);
    const local = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
    if (parts.hour < 18) local.setUTCDate(local.getUTCDate() - 1);
    return wallToEpochSeconds({
      year: local.getUTCFullYear(),
      month: local.getUTCMonth() + 1,
      day: local.getUTCDate(),
      hour: 18,
      minute: 0,
      second: 0,
    });
  }

  function dailyTradingStamp(seconds) {
    const parts = etParts(seconds);
    const day = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
    if (parts.hour >= 18) day.setUTCDate(day.getUTCDate() + 1);
    return wallToEpochSeconds({
      year: day.getUTCFullYear(),
      month: day.getUTCMonth() + 1,
      day: day.getUTCDate(),
      hour: 0,
      minute: 0,
      second: 0,
    });
  }

  function normalizeDailyTime(seconds) {
    const date = new Date(Number(seconds) * 1000);
    return wallToEpochSeconds({
      year: date.getUTCFullYear(),
      month: date.getUTCMonth() + 1,
      day: date.getUTCDate(),
      hour: 0,
      minute: 0,
      second: 0,
    });
  }

  function bucketTime(seconds, timeframe) {
    if (timeframe === "1") return Number(seconds);
    if (timeframe === "1D") return dailyTradingStamp(seconds);
    const start = sessionStart(seconds);
    const minutes = Number(timeframe);
    return start + Math.floor(Math.max(0, Number(seconds) - start) / (minutes * 60)) * minutes * 60;
  }

  function normalizeDisplay(raw, timeframe = null) {
    let time = Number(raw.t ?? raw.time);
    if (String(timeframe) === "1D") time = normalizeDailyTime(time);
    return {
      time,
      open: Number(raw.o ?? raw.open),
      high: Number(raw.h ?? raw.high),
      low: Number(raw.l ?? raw.low),
      close: Number(raw.c ?? raw.close),
      volume: Number(raw.v ?? raw.volume),
    };
  }

  function aggregateAll(rawBars, timeframe) {
    const out = [];
    let current = null;
    for (const raw of rawBars || []) {
      const bar = normalizeRaw(raw);
      const time = bucketTime(bar.t, timeframe);
      if (!current || current.time !== time) {
        current = { time, open: bar.o, high: bar.h, low: bar.l, close: bar.c, volume: bar.v };
        out.push(current);
      } else {
        current.high = Math.max(current.high, bar.h);
        current.low = Math.min(current.low, bar.l);
        current.close = bar.c;
        current.volume += bar.v;
      }
    }
    return out;
  }

  function candle(bar) {
    return { time: bar.time, open: bar.open, high: bar.high, low: bar.low, close: bar.close };
  }

  function volume(bar) {
    return {
      time: bar.time,
      value: bar.volume,
      color: bar.close >= bar.open ? "rgba(38,166,154,.46)" : "rgba(239,83,80,.46)",
    };
  }

  function cloneBar(bar) {
    return bar ? { ...bar } : null;
  }

  function sameRange(a, b) {
    if (!a || !b) return false;
    const af = Number(a.from), at = Number(a.to), bf = Number(b.from), bt = Number(b.to);
    return [af, at, bf, bt].every(Number.isFinite) && Math.abs(af - bf) < 1e-9 && Math.abs(at - bt) < 1e-9;
  }

  window.FutureViewChartTools = class FutureViewChartToolsReplayController extends Base {
    constructor(options) {
      super(options);
      this._fvTimeframe = "5";
      this._fvHistorySeconds = 5 * 86400;
      this._fvRawBars = [];
      this._fvActiveAggregate = null;
      this._fvReplayCursor = null;
      this._fvAutoFitPending = false;
      this._fvUserInteractionUntil = 0;
      this._fvBoundaryFrom = null;
      this._fvBoundaryTo = null;
      this._fvBoundaryHistory = null;
      this._fvBoundaryStep = null;
      this._fvBoundaryCursor = null;

      this._fvNativeCandleUpdate = this.candles.update.bind(this.candles);
      this._fvNativeCandleSetData = this.candles.setData.bind(this.candles);
      this._fvNativeVolumeUpdate = this.volume?.update?.bind(this.volume) ?? null;
      this._fvNativeVolumeSetData = this.volume?.setData?.bind(this.volume) ?? null;
      this.candles.update = () => {};
      this.candles.setData = () => {};
      if (this.volume) {
        this.volume.update = () => {};
        this.volume.setData = () => {};
      }

      this._fvRangeBoundarySeries = this.chart.addSeries(LightweightCharts.LineSeries, {
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
      });
      try {
        this.chart.applyOptions({
          timeScale: {
            minBarSpacing: 0.01,
            enableConflation: true,
            ignoreWhitespaceIndices: false,
          },
        });
      } catch {}

      this._fvInstallViewportGuard();

      const overlay = document.querySelector(".chart-timeframe-overlay");
      overlay?.addEventListener("click", (event) => {
        const button = event.target.closest?.("button[data-timeframe]");
        if (!button) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        this._fvSetTimeframe(button.dataset.timeframe);
      }, true);

      this._fvSyncTimeframeUi();
      window.__futureViewChartTools = this;
    }

    _fvInstallViewportGuard() {
      const ts = this.chart.timeScale();
      this._fvNativeSetVisibleRange = ts.setVisibleRange.bind(ts);
      this._fvNativeSetVisibleLogicalRange = ts.setVisibleLogicalRange?.bind(ts) ?? null;
      const blocked = () => this._fvUserInteractionUntil === Infinity || performance.now() < this._fvUserInteractionUntil;

      ts.setVisibleRange = (range) => {
        if (blocked()) return;
        if (sameRange(ts.getVisibleRange?.(), range)) return;
        return this._fvNativeSetVisibleRange(range);
      };
      if (this._fvNativeSetVisibleLogicalRange) {
        ts.setVisibleLogicalRange = (range) => {
          if (blocked()) return;
          if (sameRange(ts.getVisibleLogicalRange?.(), range)) return;
          return this._fvNativeSetVisibleLogicalRange(range);
        };
      }

      const begin = () => { this._fvUserInteractionUntil = Infinity; };
      const end = () => { this._fvUserInteractionUntil = performance.now() + 180; };
      this.container.addEventListener("pointerdown", begin, true);
      this.container.addEventListener("pointerup", end, true);
      this.container.addEventListener("pointercancel", end, true);
      this.container.addEventListener("wheel", () => { this._fvUserInteractionUntil = performance.now() + 180; }, { capture: true, passive: true });
    }

    _fvSyncTimeframeUi() {
      document.querySelectorAll("button[data-timeframe]").forEach((button) => {
        const active = button.dataset.timeframe === this._fvTimeframe;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", String(active));
      });
    }

    _fvSetReplayCursor(seconds) {
      const value = Number(seconds);
      if (!Number.isFinite(value)) return;
      this._fvReplayCursor = value;
      this._fvRefreshRangeBoundaries();
    }

    _fvCursor() {
      return Number(this._fvReplayCursor ?? this._fvRawBars.at(-1)?.t ?? this.bars?.at(-1)?.time);
    }

    _fvDisplayTimeForCanonical(seconds) {
      return bucketTime(Number(seconds), this._fvTimeframe);
    }

    _fvStepSeconds() {
      if (this._fvTimeframe === "1D") return 86400;
      return Math.max(60, Number(this._fvTimeframe || "5") * 60);
    }

    _fvRefreshRangeBoundaries(force = false) {
      const cursor = this._fvCursor();
      if (!Number.isFinite(cursor) || !this._fvRangeBoundarySeries) return;
      const step = Math.max(60, Number(this._fvStepSeconds() || 60));
      const history = Math.max(step, Number(this._fvHistorySeconds) || 5 * 86400);
      const previousCursor = Number(this._fvBoundaryCursor);
      const domainChanged = Number(this._fvBoundaryHistory) !== history || Number(this._fvBoundaryStep) !== step;
      const largeJump = Number.isFinite(previousCursor) && Math.abs(cursor - previousCursor) > history / 2;
      const reset = force || domainChanged || largeJump || !Number.isFinite(Number(this._fvBoundaryFrom)) || !Number.isFinite(Number(this._fvBoundaryTo));

      if (reset) {
        this._fvBoundaryFrom = cursor - history;
        this._fvBoundaryTo = cursor + Math.max(86400, history / 4, step * 32);
        this._fvBoundaryHistory = history;
        this._fvBoundaryStep = step;
        this._fvBoundaryCursor = cursor;
        this._fvRangeBoundarySeries.setData([
          { time: this._fvBoundaryFrom },
          { time: this._fvBoundaryTo },
        ]);
        return;
      }

      const guard = Math.max(3600, step * 8);
      if (cursor + guard >= this._fvBoundaryTo) {
        this._fvBoundaryTo = cursor + Math.max(86400, history / 4, step * 32);
        this._fvRangeBoundarySeries.setData([
          { time: this._fvBoundaryFrom },
          { time: this._fvBoundaryTo },
        ]);
      }
      this._fvBoundaryCursor = cursor;
    }

    _fvSetTimeDomain(seconds) {
      const value = Number(seconds);
      if (!Number.isFinite(value) || value <= 0) return;
      this._fvHistorySeconds = value;
      this._fvRefreshRangeBoundaries();
    }

    _fvSetHistoryRange(seconds) {
      this._fvSetTimeDomain(seconds);
      const cursor = this._fvCursor();
      if (!Number.isFinite(cursor)) return;
      try { this._fvNativeSetVisibleRange({ from: cursor - Number(seconds), to: cursor }); } catch {}
    }

    _fvTrimRawTail() {
      if (this._fvRawBars.length > RAW_TAIL_LIMIT) {
        this._fvRawBars.splice(0, this._fvRawBars.length - RAW_TAIL_LIMIT);
      }
    }

    _fvRebuildActiveAggregate() {
      const raw = this._fvRawBars;
      if (!raw.length) {
        this._fvActiveAggregate = null;
        return null;
      }
      const time = bucketTime(raw.at(-1).t, this._fvTimeframe);
      let index = raw.length - 1;
      while (index > 0 && bucketTime(raw[index - 1].t, this._fvTimeframe) === time) index -= 1;
      const first = raw[index];
      const aggregate = { time, open: first.o, high: first.h, low: first.l, close: first.c, volume: 0 };
      for (; index < raw.length; index += 1) {
        const bar = raw[index];
        aggregate.high = Math.max(aggregate.high, bar.h);
        aggregate.low = Math.min(aggregate.low, bar.l);
        aggregate.close = bar.c;
        aggregate.volume += bar.v;
      }
      this._fvActiveAggregate = aggregate;
      return cloneBar(aggregate);
    }

    _fvProcessRaw(rawBar) {
      const bar = normalizeRaw(rawBar);
      if (![bar.t, bar.o, bar.h, bar.l, bar.c, bar.v].every(Number.isFinite)) return null;
      const last = this._fvRawBars.at(-1);
      if (last && bar.t < last.t) return null;
      if (last && bar.t === last.t) {
        this._fvRawBars[this._fvRawBars.length - 1] = bar;
        this._fvReplayCursor = bar.t;
        return this._fvRebuildActiveAggregate();
      }

      this._fvRawBars.push(bar);
      this._fvReplayCursor = bar.t;
      this._fvTrimRawTail();
      const time = bucketTime(bar.t, this._fvTimeframe);
      if (!this._fvActiveAggregate || this._fvActiveAggregate.time !== time) {
        this._fvActiveAggregate = {
          time,
          open: bar.o,
          high: bar.h,
          low: bar.l,
          close: bar.c,
          volume: bar.v,
        };
      } else {
        const current = this._fvActiveAggregate;
        current.high = Math.max(current.high, bar.h);
        current.low = Math.min(current.low, bar.l);
        current.close = bar.c;
        current.volume += bar.v;
      }
      return cloneBar(this._fvActiveAggregate);
    }

    _fvUpdateIndicatorsForLastBar() {
      const bar = this.bars.at(-1);
      if (!bar) return;
      const periods = { sma5: 5, sma10: 10, sma20: 20, sma60: 60 };
      for (const [key, period] of Object.entries(periods)) {
        if (this.bars.length < period) continue;
        let sum = 0;
        for (let i = this.bars.length - period; i < this.bars.length; i += 1) sum += Number(this.bars[i].close);
        this.indicators[key]?.update({ time: bar.time, value: sum / period });
      }

      const session = sessionStart(bar.time);
      let priceVolume = 0;
      let totalVolume = 0;
      for (let i = this.bars.length - 1; i >= 0; i -= 1) {
        const item = this.bars[i];
        if (sessionStart(item.time) !== session) break;
        const itemVolume = Number(item.volume) || 0;
        priceVolume += ((Number(item.high) + Number(item.low) + Number(item.close)) / 3) * itemVolume;
        totalVolume += itemVolume;
      }
      if (totalVolume > 0) this.indicators.vwap?.update({ time: bar.time, value: priceVolume / totalVolume });
    }

    _fvEmitDisplayBar(displayBar) {
      if (!displayBar) return;
      if (this._fvTimeframe === "1D") displayBar = { ...displayBar, time: normalizeDailyTime(displayBar.time) };
      this._fvNativeCandleUpdate(candle(displayBar));
      this._fvNativeVolumeUpdate?.(volume(displayBar));
      this._appendNormalized(displayBar);
      this._fvUpdateIndicatorsForLastBar();
    }

    _fvSetDisplayData(displayBars) {
      if (this._fvTimeframe === "1D") {
        displayBars = (displayBars || []).map((bar) => ({ ...bar, time: normalizeDailyTime(bar.time) }));
      }
      this._fvNativeCandleSetData(displayBars.map(candle));
      this._fvNativeVolumeSetData?.(displayBars.map(volume));
      this.bars = displayBars.map((bar) => ({ ...bar }));
      this._refreshIndicators();
      this._showLegend(null);
    }

    _fvSetTimeframe(timeframe) {
      const value = String(timeframe);
      if (!TIMEFRAMES.has(value) || value === this._fvTimeframe) return;
      this._cancelDrawing?.();
      const visible = this.chart.timeScale().getVisibleRange?.() || null;
      this._fvTimeframe = value;
      this._fvSyncTimeframeUi();
      this._fvRebuildActiveAggregate();
      this._fvSetDisplayData(aggregateAll(this._fvRawBars, value));
      this._fvRefreshRangeBoundaries();
      if (visible) {
        try { this._fvNativeSetVisibleRange(visible); } catch {}
      }
    }

    _fvLoadCachedWindow(resolution, rawBars, activeRaw = null) {
      if (!rawBars?.length || String(resolution) !== this._fvTimeframe) return false;
      this._cancelDrawing?.();
      const visible = this.chart.timeScale().getVisibleRange?.() || null;
      const displayBars = rawBars.map((bar) => normalizeDisplay(bar, resolution)).filter((bar) => Number.isFinite(bar.time));
      const active = activeRaw
        ? normalizeDisplay(activeRaw, resolution)
        : this._fvRebuildActiveAggregate();
      if (active && Number.isFinite(active.time)) {
        const last = displayBars.at(-1);
        if (!last || active.time > last.time) displayBars.push(active);
        else if (active.time === last.time) displayBars[displayBars.length - 1] = active;
      }
      this._fvSetDisplayData(displayBars);
      this._fvRefreshRangeBoundaries();

      if (this._fvAutoFitPending) {
        this._fvAutoFitPending = false;
        requestAnimationFrame(() => this.fit());
      } else if (visible) {
        try { this._fvNativeSetVisibleRange(visible); } catch {}
      }
      return true;
    }

    reset(rawBars) {
      this._cancelDrawing?.();
      this._fvRawBars = (rawBars || []).map(normalizeRaw).filter((bar) => Number.isFinite(bar.t));
      this._fvTrimRawTail();
      this._fvReplayCursor = this._fvRawBars.at(-1)?.t ?? null;
      this._fvRebuildActiveAggregate();
      this._fvSetDisplayData(aggregateAll(this._fvRawBars, this._fvTimeframe));
      this._fvRefreshRangeBoundaries(true);
      this._fvAutoFitPending = true;
    }

    append(rawBar) {
      const resolution = rawBar?.display_resolution != null ? String(rawBar.display_resolution) : null;
      if (resolution && resolution !== "1") {
        if (resolution !== String(this._fvTimeframe)) return;
        const displayBar = normalizeDisplay(rawBar, resolution);
        if (![displayBar.time, displayBar.open, displayBar.high, displayBar.low, displayBar.close, displayBar.volume].every(Number.isFinite)) return;
        this._fvEmitDisplayBar(displayBar);
        this._fvRefreshRangeBoundaries();
        this._showLegend(null);
        return;
      }

      const displayBar = this._fvProcessRaw(rawBar);
      if (!displayBar) return;
      this._fvEmitDisplayBar(displayBar);
      this._fvRefreshRangeBoundaries();
      this._showLegend(null);
    }

    appendMany(rawBars) {
      const items = rawBars || [];
      const direct = items.length && items.every((bar) => bar?.display_resolution != null && String(bar.display_resolution) !== "1");
      if (direct) {
        for (const rawBar of items) {
          const resolution = String(rawBar.display_resolution);
          if (resolution !== String(this._fvTimeframe)) continue;
          const displayBar = normalizeDisplay(rawBar, resolution);
          if (![displayBar.time, displayBar.open, displayBar.high, displayBar.low, displayBar.close, displayBar.volume].every(Number.isFinite)) continue;
          this._fvEmitDisplayBar(displayBar);
        }
        this._fvRefreshRangeBoundaries();
        this._showLegend(null);
        return;
      }

      const pending = [];
      for (const rawBar of items) {
        const displayBar = this._fvProcessRaw(rawBar);
        if (!displayBar) continue;
        const last = pending.at(-1);
        if (last?.time === displayBar.time) pending[pending.length - 1] = displayBar;
        else pending.push(displayBar);
      }
      for (const displayBar of pending) this._fvEmitDisplayBar(displayBar);
      if (pending.length) {
        this._fvRefreshRangeBoundaries();
        this._showLegend(null);
      }
    }

    fit() {
      const bars = this.bars || [];
      if (!bars.length) return;
      const first = Number(bars[0].time);
      const last = Number(bars.at(-1).time);
      if (Number.isFinite(first) && Number.isFinite(last)) {
        const step = this._fvStepSeconds();
        const span = Math.max(step, last - first);
        const pad = Math.max(step, span * 0.02);
        try { this._fvNativeSetVisibleRange({ from: first - pad, to: last + pad }); } catch {}
      }

      const priceScale = this.candles.priceScale();
      const volumeScale = this.volume?.priceScale?.();
      try { priceScale.applyOptions({ autoScale: true }); } catch {}
      if (volumeScale) { try { volumeScale.applyOptions({ autoScale: true }); } catch {} }
      requestAnimationFrame(() => requestAnimationFrame(() => {
        try { priceScale.applyOptions({ autoScale: false }); } catch {}
        if (volumeScale) { try { volumeScale.applyOptions({ autoScale: false }); } catch {}
      }));
    }
  };
})();

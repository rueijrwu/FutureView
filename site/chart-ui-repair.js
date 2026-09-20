(() => {
  const Base = window.FutureViewChartTools;
  if (!Base) return;

  const TIMEFRAMES = new Set(["1", "5", "30", "240", "1D"]);
  const RAW_TAIL_LIMIT = 1500;
  // Same four periods the base class uses, hoisted for the same reason: these loops
  // run once per bar and Object.entries allocated a fresh array of pairs each time.
  const SMA_ENTRIES = Object.entries({ sma5: 5, sma10: 10, sma20: 20, sma60: 60 });
  const SMA_NAMES = SMA_ENTRIES.map(([name]) => name);
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

  function normalizeDisplay(raw) {
    return {
      time: Number(raw.t ?? raw.time),
      open: Number(raw.o ?? raw.open),
      high: Number(raw.h ?? raw.high),
      low: Number(raw.l ?? raw.low),
      close: Number(raw.c ?? raw.close),
      volume: Number(raw.v ?? raw.volume),
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
    const parts = etParts(seconds);
    const local = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
    if (parts.hour < 18) local.setUTCDate(local.getUTCDate() - 1);
    return wallToEpochSeconds({
      year: local.getUTCFullYear(),
      month: local.getUTCMonth() + 1,
      day: local.getUTCDate(),
      hour: 18,
      minute: 0,
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
    });
  }

  function bucketTime(seconds, timeframe) {
    if (timeframe === "1") return Number(seconds);
    if (timeframe === "1D") return dailyTradingStamp(seconds);
    const start = sessionStart(seconds);
    const minutes = Number(timeframe);
    return start + Math.floor(Math.max(0, Number(seconds) - start) / (minutes * 60)) * minutes * 60;
  }

  function aggregateAll(rawBars, timeframe) {
    const out = [];
    let current = null;
    const interval = timeframe === "1" || timeframe === "1D" ? null : Number(timeframe) * 60;
    let lastRawTime = null;

    for (const raw of rawBars || []) {
      const bar = normalizeRaw(raw);
      let time;
      if (timeframe === "1") {
        time = bar.t;
      } else if (
        current &&
        interval &&
        Number.isFinite(lastRawTime) &&
        bar.t >= current.time &&
        bar.t - lastRawTime <= 6 * 60 * 60
      ) {
        const steps = Math.floor((bar.t - current.time) / interval);
        time = current.time + Math.max(0, steps) * interval;
      } else {
        time = bucketTime(bar.t, timeframe);
      }

      if (!current || current.time !== time) {
        current = { time, open: bar.o, high: bar.h, low: bar.l, close: bar.c, volume: bar.v };
        out.push(current);
      } else {
        current.high = Math.max(current.high, bar.h);
        current.low = Math.min(current.low, bar.l);
        current.close = bar.c;
        current.volume += bar.v;
      }
      lastRawTime = bar.t;
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

  function lowerBoundRawTime(bars, target) {
    let lo = 0;
    let hi = bars.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (Number(bars[mid].t) >= Number(target)) hi = mid;
      else lo = mid + 1;
    }
    return lo;
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
      this._fvUserInteractionUntil = 0;
      this._fvViewportLocked = false;
      this._fvLockedSnapshot = null;
      this._fvDesiredRange = null;
      this._fvVwapState = null;
      this._fvSmaState = null;
      this._fvIndicatorVisible = Object.fromEntries(
        [...SMA_NAMES, "vwap"].map((name) => [
          name,
          !!this.toolbar?.querySelector?.(`button[data-tool="${name}"].active`),
        ]),
      );

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

      // Only the requested range endpoints need synthetic timestamps. A dense minute-by-
      // minute whitespace spine caused large memory use and polluted fitContent().
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

      this.toolbar?.addEventListener("click", (event) => {
        const button = event.target.closest?.('button[data-tool="lock"]');
        if (!button) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        this._fvToggleLock();
      }, true);
      this._fvSyncLockUi();

      window.__futureViewChartTools = this;
    }

    // Switching bar scale churns the data twice: first a local re-aggregation
    // of the raw tail (RAW_TAIL_LIMIT minutes, so only a couple of bars at 1D),
    // then the worker's authoritative window. The intermediate state is too
    // data-starved to place a viewport against, and reading the range back off
    // it - which is what "preserve what is visible" used to do - bakes the
    // resulting lurch in permanently. So the window the user wants is carried
    // across both steps and re-applied, instead of being re-read in between.
    _fvWantRange(range) {
      const from = Number(range?.from);
      const to = Number(range?.to);
      this._fvDesiredRange = Number.isFinite(from) && Number.isFinite(to) && to > from
        ? { from, to }
        : null;
    }

    // The chart's logical axis is the candles plus the two whitespace points
    // _fvRefreshRangeBoundaries puts either side of them, so an index into
    // this.bars is not an index into the axis. This describes the difference:
    // how many boundary points sit before the candles, how many after, and
    // where they are, so a time can be converted exactly.
    _fvLogicalFrame() {
      const bars = this.bars || [];
      const count = bars.length;
      if (!count) return null;
      const first = Number(bars[0].time);
      const last = Number(bars[count - 1].time);
      if (!Number.isFinite(first) || !Number.isFinite(last)) return null;
      const step = this._fvStepSeconds();
      const cursor = this._fvCursor();
      let head = null;
      let tail = null;
      if (Number.isFinite(cursor)) {
        const seconds = Math.max(step, Number(this._fvHistorySeconds) || 5 * 86400);
        const boundaryFrom = cursor - seconds;
        const boundaryTo = cursor + step * 2;
        if (boundaryFrom < first) head = boundaryFrom;
        if (boundaryTo > last) tail = boundaryTo;
      }
      const lead = head == null ? 0 : 1;
      return {
        bars,
        count,
        first,
        last,
        step,
        head,
        tail,
        lead,
        lastIndex: count - 1 + lead + (tail == null ? 0 : 1),
      };
    }

    // Where a timestamp falls on that axis, as a fractional index.
    _fvLogicalIndexAt(time, frame = this._fvLogicalFrame()) {
      if (!frame) return null;
      const { bars, count, first, last, step, head, tail, lead } = frame;
      if (time <= first) {
        if (head == null) return (time - first) / step;
        const span = first - head || step;
        return Math.max(0, lead * (1 - (first - time) / span));
      }
      if (time >= last) {
        const base = count - 1 + lead;
        if (tail == null) return base + (time - last) / step;
        const span = tail - last || step;
        return base + Math.min(1, (time - last) / span);
      }
      let lo = 0;
      let hi = count - 1;
      while (hi - lo > 1) {
        const mid = (lo + hi) >> 1;
        if (Number(bars[mid].time) <= time) lo = mid; else hi = mid;
      }
      const span = Number(bars[hi].time) - Number(bars[lo].time) || step;
      return lo + lead + (time - Number(bars[lo].time)) / span;
    }

    // Put the chart back on a time window. This goes through the logical
    // (bar-index) axis on purpose: a *time* range that reaches past the last
    // bar, or that is narrower than one bar, is silently replaced by a range
    // of the library's own choosing - which is the jump that made switching
    // bar scale look like an auto-fit. The equivalent logical range holds.
    _fvApplyTimeRange(range) {
      const bars = this.bars || [];
      if (!bars.length) return false;
      const from = Number(range?.from);
      const to = Number(range?.to);
      if (!Number.isFinite(from) || !Number.isFinite(to) || to <= from) return false;

      const frame = this._fvLogicalFrame();
      if (!frame) return false;
      let lo = this._fvLogicalIndexAt(from, frame);
      let hi = this._fvLogicalIndexAt(to, frame);
      if (lo == null || hi == null) return false;
      // One bar is the narrowest window the chart will draw, so a request for
      // less (two hours of daily candles) is widened around its own centre,
      // keeping the user where they were and changing only the width.
      if (hi - lo < 1) {
        const centre = (lo + hi) / 2;
        lo = centre - 0.5;
        hi = centre + 0.5;
      }
      // Keep the window on the candles, holding its width and its right edge -
      // the edge the user was reading. Asking for more history than arrived,
      // or for anything past the last bar, is otherwise answered by the chart
      // with a range of its own choosing, so it is clamped here instead, where
      // the intent is known. The boundary whitespace is deliberately excluded:
      // drifting into it shows the user empty space instead of the market.
      const dataLo = frame.lead;
      const dataHi = frame.count - 1 + frame.lead;
      const width = hi - lo;
      if (width >= dataHi - dataLo) {
        lo = dataLo;
        hi = dataHi;
      } else if (hi > dataHi) {
        hi = dataHi;
        lo = dataHi - width;
      } else if (lo < dataLo) {
        lo = dataLo;
        hi = dataLo + width;
      }

      const apply = () => {
        if (this._fvNativeSetVisibleLogicalRange) {
          try { this._fvNativeSetVisibleLogicalRange({ from: lo, to: hi }); return; } catch {}
        }
        try { this._fvNativeSetVisibleRange({ from, to }); } catch {}
      };
      apply();
      // setData settles the axis over the following frame and can overwrite a
      // range applied in the same tick, so assert it once more - unless the
      // user has taken hold of the chart in the meantime.
      requestAnimationFrame(() => {
        if (this._fvUserInteractionUntil === Infinity) return;
        if (performance.now() < this._fvUserInteractionUntil) return;
        apply();
      });
      return true;
    }

    // What the viewport should be after a data change: the lock if one is held,
    // otherwise a window carried over from a scale switch, otherwise whatever
    // was on screen before the change.
    _fvRestoreViewport(previous) {
      if (this._fvViewportLocked && this._fvLockedSnapshot) {
        this._fvApplyViewportSnapshot(this._fvLockedSnapshot);
        return;
      }
      if (this._fvDesiredRange) {
        this._fvApplyTimeRange(this._fvDesiredRange);
        return;
      }
      if (previous) { try { this._fvNativeSetVisibleRange(previous); } catch {} }
    }

    // Snapshot both axes so a later switch can put them back exactly, rather
    // than reading "whatever is visible right now" (which can drift between
    // the lock engaging and the switch actually happening).
    _fvCaptureViewportSnapshot() {
      const time = this.chart.timeScale().getVisibleRange?.() || null;
      if (!time) return null;
      const price = this.candles.priceScale().getVisibleRange?.() || null;
      return { time, price };
    }

    _fvApplyViewportSnapshot(snapshot) {
      if (!snapshot) return;
      if (snapshot.time) this._fvApplyTimeRange(snapshot.time);
      if (snapshot.price) {
        try {
          this.candles.priceScale().applyOptions({ autoScale: false });
          this.candles.priceScale().setVisibleRange(snapshot.price);
        } catch {}
      }
    }

    _fvToggleLock() {
      this._fvViewportLocked = !this._fvViewportLocked;
      this._fvLockedSnapshot = this._fvViewportLocked ? this._fvCaptureViewportSnapshot() : null;
      this._fvSyncLockUi();
    }

    _fvSyncLockUi() {
      const button = this.toolbar?.querySelector?.('button[data-tool="lock"]');
      if (!button) return;
      button.classList.toggle("active", this._fvViewportLocked);
      button.setAttribute("aria-pressed", String(this._fvViewportLocked));
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

      // A deliberate pan or zoom is the user choosing a window by hand, so it
      // supersedes one carried from a scale switch and becomes what Lock holds.
      const begin = () => {
        this._fvUserInteractionUntil = Infinity;
        this._fvDesiredRange = null;
      };
      const end = () => {
        this._fvUserInteractionUntil = performance.now() + 180;
        if (this._fvViewportLocked) {
          setTimeout(() => { this._fvLockedSnapshot = this._fvCaptureViewportSnapshot(); }, 200);
        }
      };
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

    _fvCursor() {
      return Number(this._fvRawBars.at(-1)?.t ?? this.bars?.at(-1)?.time);
    }

    _fvStepSeconds() {
      if (this._fvTimeframe === "1D") return 86400;
      return Math.max(60, Number(this._fvTimeframe || "5") * 60);
    }

    _fvRefreshRangeBoundaries() {
      const cursor = this._fvCursor();
      if (!Number.isFinite(cursor)) return;
      const seconds = Math.max(this._fvStepSeconds(), Number(this._fvHistorySeconds) || 5 * 86400);
      const from = cursor - seconds;
      const to = cursor + this._fvStepSeconds() * 2;
      this._fvRangeBoundarySeries.setData([{ time: from }, { time: to }]);
    }

    _fvSetTimeDomain(seconds) {
      const value = Number(seconds);
      if (!Number.isFinite(value) || value <= 0) return;
      this._fvHistorySeconds = value;
      this._fvRefreshRangeBoundaries();
    }

    _fvSetHistoryRange(seconds) {
      this._fvSetTimeDomain(seconds);
      if (this._fvViewportLocked) { this._fvApplyViewportSnapshot(this._fvLockedSnapshot); return; }
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
      const activeStart = this._fvTimeframe === "1D" ? time - 6 * 60 * 60 : time;
      let index = lowerBoundRawTime(raw, activeStart);
      if (index >= raw.length) index = raw.length - 1;
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
        return this._fvRebuildActiveAggregate();
      }

      this._fvRawBars.push(bar);
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

    _fvSyncSmaState() {
      const bar = this.bars.at(-1);
      if (!bar) {
        this._fvSmaState = null;
        return null;
      }
      const sums = {};
      for (const [key, period] of SMA_ENTRIES) {
        let sum = 0;
        const start = Math.max(0, this.bars.length - period);
        for (let index = start; index < this.bars.length; index += 1) {
          sum += Number(this.bars[index].close);
        }
        sums[key] = sum;
      }
      this._fvSmaState = {
        lastTime: Number(bar.time),
        lastClose: Number(bar.close),
        sums,
      };
      return this._fvSmaState;
    }

    _fvRebuildVwapState() {
      const bar = this.bars.at(-1);
      if (!bar) {
        this._fvVwapState = null;
        return null;
      }
      const start = sessionStart(bar.time);
      let priceVolume = 0;
      let totalVolume = 0;
      for (let i = this.bars.length - 1; i >= 0; i -= 1) {
        const item = this.bars[i];
        if (Number(item.time) < start) break;
        const itemVolume = Number(item.volume) || 0;
        priceVolume += ((Number(item.high) + Number(item.low) + Number(item.close)) / 3) * itemVolume;
        totalVolume += itemVolume;
      }
      const lastVolume = Number(bar.volume) || 0;
      const lastPriceVolume = ((Number(bar.high) + Number(bar.low) + Number(bar.close)) / 3) * lastVolume;
      this._fvVwapState = {
        start,
        end: start + 23 * 60 * 60,
        priceVolume,
        volume: totalVolume,
        lastTime: Number(bar.time),
        lastPriceVolume,
        lastVolume,
      };
      this.vwapPriceVolume = priceVolume;
      this.vwapVolume = totalVolume;
      return this._fvVwapState;
    }

    _fvSyncVwapStateFromBase() {
      const bar = this.bars.at(-1);
      if (!bar) {
        this._fvVwapState = null;
        return;
      }
      const priceVolume = Number(this.vwapPriceVolume);
      const totalVolume = Number(this.vwapVolume);
      if (!Number.isFinite(priceVolume) || !Number.isFinite(totalVolume)) {
        this._fvRebuildVwapState();
        return;
      }
      const start = sessionStart(bar.time);
      const lastVolume = Number(bar.volume) || 0;
      this._fvVwapState = {
        start,
        end: start + 23 * 60 * 60,
        priceVolume,
        volume: totalVolume,
        lastTime: Number(bar.time),
        lastPriceVolume: ((Number(bar.high) + Number(bar.low) + Number(bar.close)) / 3) * lastVolume,
        lastVolume,
      };
    }

    _fvUpdateIndicatorsForLastBar() {
      const bar = this.bars.at(-1);
      if (!bar) return;
      const timestamp = Number(bar.time);
      const close = Number(bar.close);

      let smaState = this._fvSmaState;
      let seeded = false;
      if (!smaState || !Number.isFinite(smaState.lastTime) || timestamp < smaState.lastTime) {
        smaState = this._fvSyncSmaState();
        seeded = true;
      }
      if (smaState) {
        if (!seeded) {
          if (smaState.lastTime === timestamp) {
            const delta = close - Number(smaState.lastClose);
            for (const [key] of SMA_ENTRIES) smaState.sums[key] += delta;
          } else {
            const length = this.bars.length;
            for (const [key, period] of SMA_ENTRIES) {
              smaState.sums[key] += close;
              if (length > period) {
                smaState.sums[key] -= Number(this.bars[length - period - 1].close);
              }
            }
          }
          smaState.lastTime = timestamp;
          smaState.lastClose = close;
        }

        for (const [key, period] of SMA_ENTRIES) {
          if (this.bars.length < period) continue;
          if (this._fvIndicatorActive(key)) {
            this.indicators[key]?.update({ time: bar.time, value: smaState.sums[key] / period });
          }
        }
      }

      let state = this._fvVwapState;
      if (!state) state = this._fvRebuildVwapState();
      if (!state) return;

      if (timestamp < state.start || timestamp >= state.end) {
        const start = sessionStart(timestamp);
        state = {
          start,
          end: start + 23 * 60 * 60,
          priceVolume: 0,
          volume: 0,
          lastTime: null,
          lastPriceVolume: 0,
          lastVolume: 0,
        };
        this._fvVwapState = state;
      } else if (state.lastTime != null && timestamp < state.lastTime) {
        state = this._fvRebuildVwapState();
        if (!state) return;
      }

      const itemVolume = Number(bar.volume) || 0;
      const itemPriceVolume = ((Number(bar.high) + Number(bar.low) + Number(bar.close)) / 3) * itemVolume;
      if (state.lastTime === timestamp) {
        state.priceVolume -= state.lastPriceVolume;
        state.volume -= state.lastVolume;
      }
      state.priceVolume += itemPriceVolume;
      state.volume += itemVolume;
      state.lastTime = timestamp;
      state.lastPriceVolume = itemPriceVolume;
      state.lastVolume = itemVolume;
      this.vwapPriceVolume = state.priceVolume;
      this.vwapVolume = state.volume;

      if (state.volume > 0 && this._fvIndicatorActive("vwap")) {
        this.indicators.vwap?.update({ time: bar.time, value: state.priceVolume / state.volume });
      }
    }

    _fvEmitDisplayBar(displayBar) {
      this._fvNativeCandleUpdate(candle(displayBar));
      this._fvNativeVolumeUpdate?.(volume(displayBar));
      this._appendNormalized(displayBar);
      this._fvUpdateIndicatorsForLastBar();
    }

    _fvIndicatorActive(name) {
      if (this._fvIndicatorVisible && Object.hasOwn(this._fvIndicatorVisible, name)) {
        return !!this._fvIndicatorVisible[name];
      }
      if (!this.toolbar?.querySelector) return true;
      return !!this.toolbar.querySelector(`button[data-tool="${name}"].active`);
    }

    _fvAnyIndicatorActive() {
      return [...SMA_NAMES, "vwap"].some((name) => this._fvIndicatorActive(name));
    }

    _toggleIndicator(name, button) {
      const activating = !button?.classList?.contains?.("active");
      super._toggleIndicator(name, button);
      (this._fvIndicatorVisible ??= {})[name] = activating;
      if (!activating || !this.bars?.length) return;
      const data = this._indicatorData();
      this.indicators[name]?.setData(data[name] || []);
      this._fvSyncVwapStateFromBase();
      this._fvSyncSmaState();
    }

    _fvSetDisplayData(displayBars) {
      this._fvNativeCandleSetData(displayBars.map(candle));
      this._fvNativeVolumeSetData?.(displayBars.map(volume));
      this.bars = displayBars.map((bar) => ({ ...bar }));
      if (this._fvAnyIndicatorActive()) {
        this._refreshIndicators();
        this._fvSyncVwapStateFromBase();
      } else {
        this._fvRebuildVwapState();
      }
      this._fvSyncSmaState();
      this._showLegend(null);
    }

    _fvSetTimeframe(timeframe) {
      const value = String(timeframe);
      if (!TIMEFRAMES.has(value) || value === this._fvTimeframe) return;
      this._cancelDrawing?.();
      // Only Start/Random and the explicit Fit control may move the viewport.
      // Take the window the user is on now and carry it through both halves of
      // the switch: this local re-aggregation, and the worker's window that
      // follows it. Reading the range back after the re-aggregation instead
      // would read a range the starved intermediate data already displaced.
      if (!this._fvViewportLocked) {
        this._fvWantRange(this.chart.timeScale().getVisibleRange?.());
      }
      this._fvTimeframe = value;
      this._fvSyncTimeframeUi();
      this._fvRebuildActiveAggregate();
      this._fvSetDisplayData(aggregateAll(this._fvRawBars, value));
      this._fvRefreshRangeBoundaries();
      // Placed against the re-aggregated raw tail first, then again when the
      // worker's window for this scale lands - both from the same carried
      // window, so the two steps agree instead of fighting.
      this._fvRestoreViewport(null);
    }

    // Only Start/Random (reset(), followed by one explicit fit() in app.js) and
    // the Fit control ever move the viewport. A cached window - whatever
    // triggered it (bar-scale switch, history-range change, a late refresh
    // while stepping) - always preserves whatever range the user is looking at.
    _fvLoadCachedWindow(resolution, rawBars) {
      if (!rawBars?.length || String(resolution) !== this._fvTimeframe) return false;
      this._cancelDrawing?.();
      const visible = this._fvViewportLocked || this._fvDesiredRange
        ? null
        : (this.chart.timeScale().getVisibleRange?.() || null);
      const displayBars = rawBars.map(normalizeDisplay).filter((bar) => Number.isFinite(bar.time));
      const partial = this._fvRebuildActiveAggregate();
      if (partial) {
        const last = displayBars.at(-1);
        if (!last || partial.time > last.time) displayBars.push(partial);
        else if (partial.time === last.time) displayBars[displayBars.length - 1] = partial;
      }
      this._fvSetDisplayData(displayBars);
      this._fvRefreshRangeBoundaries();

      // This is the authoritative half of a scale switch, so the carried window
      // has had its chance: honour it here, then go back to plain preservation.
      this._fvRestoreViewport(visible);
      this._fvDesiredRange = null;
      return true;
    }

    reset(rawBars) {
      this._cancelDrawing?.();
      // Start/Random is a fresh session and fits explicitly in app.js, so no
      // window carried from a previous scale switch may survive it.
      this._fvDesiredRange = null;
      this._fvRawBars = (rawBars || []).map(normalizeRaw).filter((bar) => Number.isFinite(bar.t));
      this._fvTrimRawTail();
      this._fvRebuildActiveAggregate();
      this._fvSetDisplayData(aggregateAll(this._fvRawBars, this._fvTimeframe));
      this._fvRefreshRangeBoundaries();
    }

    append(rawBar) {
      const displayBar = this._fvProcessRaw(rawBar);
      if (!displayBar) return;
      this._fvEmitDisplayBar(displayBar);
      this._fvRefreshRangeBoundaries();
      this._showLegend(null);
    }

    appendMany(rawBars) {
      const pending = [];
      for (const rawBar of rawBars || []) {
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
      this._fvDesiredRange = null;
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
        if (volumeScale) { try { volumeScale.applyOptions({ autoScale: false }); } catch {} }
        // Fit is one of the two actions allowed to move a locked viewport;
        // re-capture so the newly-fit view becomes what Lock now holds.
        if (this._fvViewportLocked) this._fvLockedSnapshot = this._fvCaptureViewportSnapshot();
      }));
    }
  };
})();

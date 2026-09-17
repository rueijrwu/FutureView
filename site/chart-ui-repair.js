(() => {
  const Base = window.FutureViewChartTools;
  if (!Base) return;

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

  function bucketTime(seconds, timeframe) {
    if (timeframe === "1") return seconds;
    const start = sessionStart(seconds);
    if (timeframe === "1D") return start;
    const minutes = Number(timeframe);
    return start + Math.floor(Math.max(0, seconds - start) / (minutes * 60)) * minutes * 60;
  }

  function aggregateTail(raw, timeframe) {
    if (!raw.length) return null;
    const last = raw.at(-1);
    const t = bucketTime(last.t, timeframe);
    let i = raw.length - 1;
    while (i > 0 && bucketTime(raw[i - 1].t, timeframe) === t) i -= 1;
    const first = raw[i];
    let high = -Infinity, low = Infinity, volume = 0;
    for (; i < raw.length; i += 1) {
      const bar = raw[i];
      high = Math.max(high, bar.h);
      low = Math.min(low, bar.l);
      volume += bar.v;
    }
    return { time: t, open: first.o, high, low, close: last.c, volume };
  }

  function aggregateSuffix(raw, timeframe, startIndex) {
    if (!raw.length || startIndex == null) return [];
    startIndex = Math.max(0, Math.min(raw.length - 1, startIndex));
    const firstBucket = bucketTime(raw[startIndex].t, timeframe);
    while (startIndex > 0 && bucketTime(raw[startIndex - 1].t, timeframe) === firstBucket) startIndex -= 1;

    const out = [];
    let current = null;
    for (let i = startIndex; i < raw.length; i += 1) {
      const bar = raw[i];
      const t = bucketTime(bar.t, timeframe);
      if (!current || current.time !== t) {
        current = { time: t, open: bar.o, high: bar.h, low: bar.l, close: bar.c, volume: bar.v };
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

  window.FutureViewChartTools = class FutureViewChartToolsUiRepair extends Base {
    _fvSyncTimeframeUi() {
      document.querySelectorAll("button[data-timeframe]").forEach((button) => {
        const active = button.dataset.timeframe === this._fvTimeframe;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", String(active));
      });
    }

    constructor(options) {
      super(options);

      // app.js still writes raw 1m candles before calling chartTools.append().
      // Suppress those direct writes; this adapter emits only the selected timeframe.
      this._fvNativeCandleUpdate = this.candles.update.bind(this.candles);
      this._fvNativeVolumeUpdate = this.volume?.update?.bind(this.volume) ?? null;
      this.candles.update = () => {};
      if (this.volume) this.volume.update = () => {};

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

    _fvEmitDisplayBar(displayBar) {
      this._fvNativeCandleUpdate(candle(displayBar));
      this._fvNativeVolumeUpdate?.(volume(displayBar));
      this._appendNormalized(displayBar);
      // All live changes only affect the current last display bar or append new bars,
      // so an incremental indicator update is sufficient; avoid full-history rebuilds.
      this._updateIndicatorsForLastBar();
    }

    _fvApplyRaw(rawBar) {
      const bar = normalizeRaw(rawBar);
      const raw = this._fvRawBars || (this._fvRawBars = []);
      const last = raw.at(-1);
      if (last && bar.t === last.t) raw[raw.length - 1] = bar;
      else if (!last || bar.t > last.t) raw.push(bar);
      else return;

      const displayBar = aggregateTail(raw, this._fvTimeframe || "5");
      if (!displayBar) return;
      this._fvEmitDisplayBar(displayBar);
      this._showLegend(null);
    }

    append(rawBar) {
      this._fvApplyRaw(rawBar);
    }

    appendMany(rawBars) {
      const raw = this._fvRawBars || (this._fvRawBars = []);
      let changedFrom = null;

      for (const item of rawBars || []) {
        const bar = normalizeRaw(item);
        const last = raw.at(-1);
        if (last && bar.t === last.t) {
          raw[raw.length - 1] = bar;
          if (changedFrom == null) changedFrom = raw.length - 1;
        } else if (!last || bar.t > last.t) {
          raw.push(bar);
          if (changedFrom == null) changedFrom = raw.length - 1;
        }
      }

      if (changedFrom == null) return;
      const displayBars = aggregateSuffix(raw, this._fvTimeframe || "5", changedFrom);
      for (const displayBar of displayBars) this._fvEmitDisplayBar(displayBar);
      this._showLegend(null);
    }
  };
})();

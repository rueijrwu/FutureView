(() => {
  const HISTORY_RANGES = {
    "1D": { warmup: 1380, seconds: 86400 },
    "5D": { warmup: 6900, seconds: 5 * 86400 },
    "1M": { warmup: 30360, seconds: 30 * 86400 },
    "3M": { warmup: 91080, seconds: 90 * 86400 },
  };
  const STORAGE_KEY = "futureview_history_range";
  let selectedRange = HISTORY_RANGES[localStorage.getItem(STORAGE_KEY)] ? localStorage.getItem(STORAGE_KEY) : "5D";
  let replaySocket = null;

  const NativeWebSocket = window.WebSocket;
  window.WebSocket = class FutureViewTrackedWebSocket extends NativeWebSocket {
    constructor(...args) {
      super(...args);
      replaySocket = this;
      window.__futureViewReplaySocket = this;
      this.addEventListener("open", () => {
        const timeframe = window.__futureViewChartTools?._fvTimeframe || document.querySelector("button[data-timeframe].active")?.dataset.timeframe || "5";
        try { this.send(JSON.stringify({ type: "set_timeframe", timeframe, history_range: selectedRange })); } catch {}
      });
      this.addEventListener("message", (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload?.type === "session_snapshot" && payload.speed != null) syncSpeedUi(payload.speed);
          if (payload?.snapshot?.speed != null) syncSpeedUi(payload.snapshot.speed);
          if (payload?.type === "display_window" && payload.future_data_included === false) {
            window.__futureViewChartTools?._fvLoadCachedWindow?.(payload.resolution, payload.bars || []);
            if (payload.history_range && HISTORY_RANGES[payload.history_range]) selectedRange = payload.history_range;
            const seconds = HISTORY_RANGES[selectedRange]?.seconds;
            if (seconds) window.__futureViewChartTools?._fvSetTimeDomain?.(seconds);
          }
        } catch {}
      });
    }
  };

  function syncUi() {
    const warmup = document.getElementById("warmup");
    if (warmup) warmup.value = String(HISTORY_RANGES[selectedRange].warmup);
    document.querySelectorAll("button[data-history-range]").forEach((button) => {
      const active = button.dataset.historyRange === selectedRange;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function speedFromButton(button) {
    return button?.dataset.speed === "max" ? "max" : Number(button?.dataset.speed || 1);
  }

  function selectedSpeed() {
    return speedFromButton(document.querySelector("#speeds button.active[data-speed]"));
  }

  function syncSpeedUi(value) {
    const target = String(value).toLowerCase();
    document.querySelectorAll("#speeds button[data-speed]").forEach((button) => {
      button.classList.toggle("active", String(button.dataset.speed).toLowerCase() === target);
    });
  }

  function setRange(range, applyToChart = true) {
    if (!HISTORY_RANGES[range]) return;
    selectedRange = range;
    localStorage.setItem(STORAGE_KEY, range);
    syncUi();
    if (replaySocket?.readyState === NativeWebSocket.OPEN) {
      replaySocket.send(JSON.stringify({ type: "set_history_range", history_range: range }));
    }
    if (applyToChart) window.__futureViewChartTools?._fvSetHistoryRange?.(range);
  }

  document.addEventListener("click", (event) => {
    const timeframeButton = event.target.closest?.("button[data-timeframe]");
    if (timeframeButton && replaySocket?.readyState === NativeWebSocket.OPEN) {
      replaySocket.send(JSON.stringify({
        type: "set_timeframe",
        timeframe: timeframeButton.dataset.timeframe,
        history_range: selectedRange,
      }));
    }

    const historyButton = event.target.closest?.("button[data-history-range]");
    if (historyButton) {
      event.preventDefault();
      setRange(historyButton.dataset.historyRange, true);
      return;
    }

    const nextButton = event.target.closest?.("#next");
    if (!nextButton) return;
    const timeframe = window.__futureViewChartTools?._fvTimeframe || "1";
    if (!replaySocket || replaySocket.readyState !== NativeWebSocket.OPEN) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    replaySocket.send(JSON.stringify({ type: "step_frame", timeframe }));
  }, true);

  document.addEventListener("DOMContentLoaded", () => {
    syncUi();
    const seconds = HISTORY_RANGES[selectedRange]?.seconds;
    if (seconds) window.__futureViewChartTools?._fvSetTimeDomain?.(seconds);

    const speeds = document.getElementById("speeds");
    const play = document.getElementById("play");
    if (!speeds || !play) return;

    const originalSpeedsHandler = speeds.onclick;
    const originalPlayHandler = play.onclick;

    speeds.onclick = (event) => {
      const button = event.target.closest?.("button[data-speed]");
      if (!button) return;
      const value = speedFromButton(button);
      syncSpeedUi(value);

      const playing = document.getElementById("state-status")?.textContent === "PLAYING";
      if (playing && replaySocket?.readyState === NativeWebSocket.OPEN) {
        replaySocket.send(JSON.stringify({ type: "set_speed", speed: value }));
        return;
      }
      originalSpeedsHandler?.call(speeds, event);
    };

    play.onclick = (event) => {
      if (replaySocket?.readyState === NativeWebSocket.OPEN) {
        replaySocket.send(JSON.stringify({ type: "play", speed: selectedSpeed() }));
        return;
      }
      originalPlayHandler?.call(play, event);
    };
  });

  const Ctor = window.FutureViewChartTools;
  if (!Ctor) return;
  window.FutureViewChartTools = class FutureViewChartToolsWithHistoryRange extends Ctor {
    constructor(options) {
      super(options);
      this._fvHistoryRange = selectedRange;
      this._fvRefitAfterCacheUntil = 0;
      const seconds = HISTORY_RANGES[selectedRange]?.seconds;
      if (seconds) this._fvSetTimeDomain?.(seconds);
      syncUi();
    }

    _fvSetHistoryRange(range) {
      if (!HISTORY_RANGES[range]) return;
      this._fvHistoryRange = range;
      const seconds = HISTORY_RANGES[range].seconds;
      this._fvSetTimeDomain?.(seconds);

      const raw = this._fvRawBars || [];
      const to = Number(raw.at(-1)?.t ?? this.bars?.at(-1)?.time);
      if (!Number.isFinite(to)) return;
      const from = to - seconds;
      try { this.chart.timeScale().setVisibleRange({ from, to }); } catch {}
    }

    // Fit only real market bars. The calendar-time whitespace series exists solely to
    // make the date axis continuous and must not participate in auto-fit.
    fit() {
      const bars = this.bars || [];
      if (!bars.length) return;

      const first = Number(bars[0]?.time);
      const last = Number(bars.at(-1)?.time);
      if (Number.isFinite(first) && Number.isFinite(last)) {
        const step = Number(this._fvTimeStepSeconds?.() || 60);
        const span = Math.max(step, last - first);
        const pad = Math.max(step, span * 0.02);
        try { this.chart.timeScale().setVisibleRange({ from: first - pad, to: last + pad }); } catch {}
      }

      const priceScale = this.candles.priceScale();
      const volumeScale = this.volume ? this.volume.priceScale() : null;
      try { priceScale.applyOptions({ autoScale: true }); } catch {}
      if (volumeScale) { try { volumeScale.applyOptions({ autoScale: true }); } catch {} }

      requestAnimationFrame(() => requestAnimationFrame(() => {
        try { priceScale.applyOptions({ autoScale: false }); } catch {}
        if (volumeScale) { try { volumeScale.applyOptions({ autoScale: false }); } catch {} }
      }));
    }

    _fvLoadCachedWindow(resolution, bars) {
      super._fvLoadCachedWindow(resolution, bars);
      if (performance.now() <= this._fvRefitAfterCacheUntil) {
        this._fvRefitAfterCacheUntil = 0;
        requestAnimationFrame(() => this.fit());
      }
    }

    reset(rawBars) {
      // Start/Random fit immediately in app.js, but a causal cached-history replacement
      // can arrive just afterward. Re-fit that replacement once so Y scale cannot remain
      // frozen to the temporary warmup series.
      this._fvRefitAfterCacheUntil = performance.now() + 5000;
      super.reset(rawBars);
      const seconds = HISTORY_RANGES[this._fvHistoryRange || selectedRange]?.seconds;
      if (seconds) this._fvSetTimeDomain?.(seconds);
    }
  };
})();

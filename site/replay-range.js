(() => {
  const HISTORY_RANGES = {
    "1D": { warmup1m: 1380, seconds: 86400 },
    "5D": { warmup1m: 6900, seconds: 5 * 86400 },
    "1M": { warmup1m: 30360, seconds: 30 * 86400 },
    "3M": { warmup1m: 91080, seconds: 90 * 86400 },
  };
  const DEFAULT_RAW_WARMUP = 1500;
  const STORAGE_KEY = "futureview_history_range";
  let selectedRange = HISTORY_RANGES[localStorage.getItem(STORAGE_KEY)] ? localStorage.getItem(STORAGE_KEY) : "5D";
  let replaySocket = null;
  let applyRangeOnNextWindow = false;

  const NativeWebSocket = window.WebSocket;

  function timeframe() {
    return String(
      window.__futureViewChartTools?._fvTimeframe ||
      document.querySelector("button[data-timeframe].active")?.dataset.timeframe ||
      "5"
    );
  }

  function warmupCount(tf = timeframe()) {
    return tf === "1" ? HISTORY_RANGES[selectedRange].warmup1m : DEFAULT_RAW_WARMUP;
  }

  function syncRangeUi(tf = timeframe()) {
    const warmup = document.getElementById("warmup");
    if (warmup) warmup.value = String(warmupCount(tf));
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

  function send(payload) {
    if (!replaySocket || replaySocket.readyState !== NativeWebSocket.OPEN) return false;
    replaySocket.send(JSON.stringify(payload));
    return true;
  }

  window.WebSocket = class FutureViewTrackedWebSocket extends NativeWebSocket {
    constructor(...args) {
      super(...args);
      replaySocket = this;
      window.__futureViewReplaySocket = this;

      this.addEventListener("open", () => {
        applyRangeOnNextWindow = false;
        try {
          this.send(JSON.stringify({
            type: "set_timeframe",
            timeframe: timeframe(),
            history_range: selectedRange,
          }));
        } catch {}
      });

      this.addEventListener("message", (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload?.type === "session_snapshot" && payload.speed != null) syncSpeedUi(payload.speed);
          if (payload?.snapshot?.speed != null) syncSpeedUi(payload.snapshot.speed);

          if (payload?.type === "display_window" && payload.future_data_included === false) {
            // Ignore stale responses from a timeframe/range request that was superseded.
            if (String(payload.resolution) !== timeframe()) return;
            if (payload.history_range && payload.history_range !== selectedRange) return;
            const accepted = window.__futureViewChartTools?._fvLoadCachedWindow?.(
              payload.resolution,
              payload.bars || [],
            );
            if (accepted && applyRangeOnNextWindow) {
              applyRangeOnNextWindow = false;
              window.__futureViewChartTools?._fvSetHistoryRange?.(HISTORY_RANGES[selectedRange].seconds);
            }
          }
        } catch {}
      });
    }
  };

  function setRange(range) {
    if (!HISTORY_RANGES[range]) return;
    selectedRange = range;
    localStorage.setItem(STORAGE_KEY, range);
    syncRangeUi();
    window.__futureViewChartTools?._fvSetTimeDomain?.(HISTORY_RANGES[range].seconds);

    if (send({ type: "set_history_range", history_range: range })) {
      applyRangeOnNextWindow = true;
    } else {
      window.__futureViewChartTools?._fvSetHistoryRange?.(HISTORY_RANGES[range].seconds);
    }
  }

  // Capture only controls whose semantics differ from the legacy app.js path.
  document.addEventListener("click", (event) => {
    const timeframeButton = event.target.closest?.("button[data-timeframe]");
    if (timeframeButton) {
      applyRangeOnNextWindow = false;
      send({
        type: "set_timeframe",
        timeframe: timeframeButton.dataset.timeframe,
        history_range: selectedRange,
      });
      queueMicrotask(() => syncRangeUi(timeframeButton.dataset.timeframe));
      return;
    }

    const historyButton = event.target.closest?.("button[data-history-range]");
    if (historyButton) {
      event.preventDefault();
      event.stopImmediatePropagation();
      setRange(historyButton.dataset.historyRange);
      return;
    }

    const nextButton = event.target.closest?.("#next");
    if (nextButton && replaySocket?.readyState === NativeWebSocket.OPEN) {
      event.preventDefault();
      event.stopImmediatePropagation();
      nextButton.disabled = true;
      send({ type: "step_frame", timeframe: timeframe() });
      return;
    }

    // app.js historically changes speed by issuing another `play` command. While
    // already playing, intercept only that case and use the dedicated set_speed command.
    const speedButton = event.target.closest?.("#speeds button[data-speed]");
    if (speedButton && document.getElementById("state-status")?.textContent === "PLAYING") {
      event.preventDefault();
      event.stopImmediatePropagation();
      const value = speedFromButton(speedButton);
      syncSpeedUi(value);
      send({ type: "set_speed", speed: value });
    }
  }, true);

  // Keep Play aligned with the speed highlighted from authoritative snapshots. This is
  // needed after Restart, which resets Worker speed to 1x while app.js's closure may
  // still hold the previous value.
  document.addEventListener("click", (event) => {
    const play = event.target.closest?.("#play");
    if (!play || !replaySocket || replaySocket.readyState !== NativeWebSocket.OPEN) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    play.disabled = true;
    send({ type: "play", speed: selectedSpeed() });
  }, true);

  document.addEventListener("DOMContentLoaded", () => {
    syncRangeUi();
    window.__futureViewChartTools?._fvSetTimeDomain?.(HISTORY_RANGES[selectedRange].seconds);
  });
})();

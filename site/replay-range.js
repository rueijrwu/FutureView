(() => {
  const HISTORY_RANGES = {
    "1D": { seconds: 86400 },
    "5D": { seconds: 5 * 86400 },
    "1M": { seconds: 30 * 86400 },
    "3M": { seconds: 90 * 86400 },
  };
  const DEFAULT_RAW_WARMUP = 1500;
  const STORAGE_KEY = "futureview_history_range";
  let selectedRange = HISTORY_RANGES[localStorage.getItem(STORAGE_KEY)] ? localStorage.getItem(STORAGE_KEY) : "5D";
  let replaySocket = null;
  let applyRangeOnNextWindow = false;
  const displayWindowAssembler = window.FutureViewDisplayWindowAssembler
    ? new window.FutureViewDisplayWindowAssembler()
    : null;

  const NativeWebSocket = window.WebSocket;

  // Keep the synthetic calendar anchors stable while replay advances. app.js preserves
  // the viewport by logical index around each batch; sliding these anchors on every bar
  // changes the logical-index→timestamp mapping and makes Next/Play visibly jump.
  // Reset only when the time domain materially changes; otherwise extend the future
  // anchor without moving the past anchor, so existing logical indices stay stable.
  const ChartCtor = window.FutureViewChartTools;
  if (ChartCtor?.prototype?._fvRefreshRangeBoundaries) {
    ChartCtor.prototype._fvRefreshRangeBoundaries = function (force = false) {
      const cursor = Number(this._fvCursor?.());
      if (!Number.isFinite(cursor) || !this._fvRangeBoundarySeries) return;
      const step = Math.max(60, Number(this._fvStepSeconds?.() || 60));
      const history = Math.max(step, Number(this._fvHistorySeconds) || 5 * 86400);
      const previousCursor = Number(this._fvBoundaryCursor);
      const domainChanged = Number(this._fvBoundaryHistory) !== history || Number(this._fvBoundaryStep) !== step;
      const largeJump = Number.isFinite(previousCursor) && Math.abs(cursor - previousCursor) > history / 2;
      const reset = force || domainChanged || largeJump || !Number.isFinite(Number(this._fvBoundaryFrom)) || !Number.isFinite(Number(this._fvBoundaryTo));

      const rightPad = Math.max(step * 2, Math.min(3600, step * 8));

      if (reset) {
        this._fvBoundaryFrom = cursor - history;
        this._fvBoundaryTo = cursor + rightPad;
        this._fvBoundaryHistory = history;
        this._fvBoundaryStep = step;
        this._fvBoundaryCursor = cursor;
        this._fvRangeBoundarySeries.setData([
          { time: this._fvBoundaryFrom },
          { time: this._fvBoundaryTo },
        ]);
        return;
      }

      if (cursor + step >= this._fvBoundaryTo) {
        this._fvBoundaryTo = cursor + rightPad;
        this._fvRangeBoundarySeries.setData([
          { time: this._fvBoundaryFrom },
          { time: this._fvBoundaryTo },
        ]);
      }
      this._fvBoundaryCursor = cursor;
    };
  }

  // Historical 1D cache bars were originally stamped at 00:00 UTC. The chart formats
  // every timestamp in America/New_York, which made those bars appear at 19:00/20:00 on
  // the prior date. Normalize every daily bar to midnight ET for its encoded trading day.
  // This is also idempotent for the corrected cache format, whose UTC epoch represents
  // 00:00 ET directly.
  const ET_WALL_FORMATTER = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });

  function etWallParts(seconds) {
    return Object.fromEntries(
      ET_WALL_FORMATTER.formatToParts(new Date(Number(seconds) * 1000))
        .filter((part) => part.type !== "literal")
        .map((part) => [part.type, Number(part.value)]),
    );
  }

  function etWallToEpoch(parts) {
    const wanted = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour || 0, parts.minute || 0, 0);
    let guess = wanted;
    for (let i = 0; i < 4; i += 1) {
      const shown = etWallParts(guess / 1000);
      const shownWall = Date.UTC(shown.year, shown.month - 1, shown.day, shown.hour, shown.minute, 0);
      const delta = wanted - shownWall;
      guess += delta;
      if (!delta) break;
    }
    return Math.floor(guess / 1000);
  }

  function normalizeDailyTime(seconds) {
    const date = new Date(Number(seconds) * 1000);
    return etWallToEpoch({
      year: date.getUTCFullYear(),
      month: date.getUTCMonth() + 1,
      day: date.getUTCDate(),
      hour: 0,
      minute: 0,
    });
  }

  function normalizeDisplayBar(raw, timeframe) {
    const time = Number(raw?.t ?? raw?.time);
    return {
      time: timeframe === "1D" ? normalizeDailyTime(time) : time,
      open: Number(raw?.o ?? raw?.open),
      high: Number(raw?.h ?? raw?.high),
      low: Number(raw?.l ?? raw?.low),
      close: Number(raw?.c ?? raw?.close),
      volume: Number(raw?.v ?? raw?.volume),
    };
  }

  if (ChartCtor) {
    window.FutureViewChartTools = class FutureViewChartToolsEasternDaily extends ChartCtor {
      _fvSetDisplayData(displayBars) {
        if (this._fvTimeframe === "1D") {
          displayBars = (displayBars || []).map((bar) => ({ ...bar, time: normalizeDailyTime(bar.time) }));
        }
        return super._fvSetDisplayData(displayBars);
      }

      _fvEmitDisplayBar(displayBar) {
        if (this._fvTimeframe === "1D" && displayBar) {
          displayBar = { ...displayBar, time: normalizeDailyTime(displayBar.time) };
        }
        return super._fvEmitDisplayBar(displayBar);
      }

      append(rawBar) {
        const resolution = rawBar?.display_resolution != null ? String(rawBar.display_resolution) : null;
        if (resolution && resolution !== "1") {
          if (resolution !== String(this._fvTimeframe)) return;
          const bar = normalizeDisplayBar(rawBar, resolution);
          if (![bar.time, bar.open, bar.high, bar.low, bar.close, bar.volume].every(Number.isFinite)) return;
          this._fvEmitDisplayBar(bar);
          this._fvRefreshRangeBoundaries?.();
          this._showLegend?.(null);
          return;
        }
        return super.append(rawBar);
      }

      appendMany(rawBars) {
        const items = rawBars || [];
        const direct = items.length && items.every((bar) => bar?.display_resolution != null && String(bar.display_resolution) !== "1");
        if (!direct) return super.appendMany(items);
        for (const rawBar of items) {
          const resolution = String(rawBar.display_resolution);
          if (resolution !== String(this._fvTimeframe)) continue;
          const bar = normalizeDisplayBar(rawBar, resolution);
          if (![bar.time, bar.open, bar.high, bar.low, bar.close, bar.volume].every(Number.isFinite)) continue;
          this._fvEmitDisplayBar(bar);
        }
        this._fvRefreshRangeBoundaries?.();
        this._showLegend?.(null);
      }
    };
  }

  function timeframe() {
    return String(
      window.__futureViewChartTools?._fvTimeframe ||
      document.querySelector("button[data-timeframe].active")?.dataset.timeframe ||
      "5"
    );
  }

  function syncRangeUi() {
    const warmup = document.getElementById("warmup");
    if (warmup) warmup.value = String(DEFAULT_RAW_WARMUP);
    document.querySelectorAll("button[data-history-range]").forEach((button) => {
      const active = button.dataset.historyRange === selectedRange;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  const SPEED_STEPS = [1, 5, 10, 25, 50, 100, "max"];

  function speedFromSlider(slider) {
    const step = SPEED_STEPS[Number(slider?.value)];
    return step == null ? 1 : step;
  }

  function selectedSpeed() {
    return speedFromSlider(document.getElementById("speed-slider"));
  }

  function speedLabel(value) {
    return value === "max" ? "Max" : `${value}x`;
  }

  function syncSpeedUi(value) {
    const target = String(value).toLowerCase();
    const index = SPEED_STEPS.findIndex((step) => String(step).toLowerCase() === target);
    const slider = document.getElementById("speed-slider");
    if (slider && index >= 0) slider.value = String(index);
    const output = document.getElementById("speed-value");
    if (output) output.textContent = speedLabel(index >= 0 ? SPEED_STEPS[index] : value);
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
        displayWindowAssembler?.reset();
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

          if (payload?.type === "display_window") {
            // display_window is a cache/data-plane extension, not a replay command ACK.
            // Consume it here so legacy app.js cannot clear pendingCommand/wsSynced by
            // treating an unknown message as an authoritative session snapshot.
            event.stopImmediatePropagation();
            if (payload.future_data_included !== false) return;
            if (String(payload.resolution) !== timeframe()) return;
            if (payload.history_range && payload.history_range !== selectedRange) return;
            const assembled = displayWindowAssembler?.accept(payload) ?? {
              complete: true,
              bars: payload.bars || [],
            };
            if (!assembled.complete) return;
            const accepted = window.__futureViewChartTools?._fvLoadCachedWindow?.(
              payload.resolution,
              assembled.bars || [],
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
    displayWindowAssembler?.reset();

    const seconds = HISTORY_RANGES[range].seconds;
    // Change the visible calendar range immediately. Long ranges such as 3M may
    // require multiple cache messages, so the axis must not wait for history I/O.
    window.__futureViewChartTools?._fvSetHistoryRange?.(seconds);

    if (send({ type: "set_history_range", history_range: range })) {
      applyRangeOnNextWindow = true;
    } else {
      applyRangeOnNextWindow = false;
    }
  }

  document.addEventListener("click", (event) => {
    const timeframeButton = event.target.closest?.("button[data-timeframe]");
    if (timeframeButton) {
      const requested = String(timeframeButton.dataset.timeframe);
      applyRangeOnNextWindow = false;
      displayWindowAssembler?.reset();
      // Only Start/Random and the explicit Fit control may move the viewport -
      // a bar-scale change keeps whatever range the user is already looking at.
      send({
        type: "set_timeframe",
        timeframe: requested,
        history_range: selectedRange,
      });
      queueMicrotask(syncRangeUi);
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
  }, true);

  document.addEventListener("input", (event) => {
    const slider = event.target.closest?.("#speed-slider");
    if (!slider) return;
    const output = document.getElementById("speed-value");
    if (output) output.textContent = speedLabel(speedFromSlider(slider));
  });

  // Commit the speed change once the drag/keypress settles, rather than on
  // every intermediate "input" tick, so dragging the slider doesn't flood
  // the worker with set_speed messages.
  document.addEventListener("change", (event) => {
    const slider = event.target.closest?.("#speed-slider");
    if (!slider || document.getElementById("state-status")?.textContent !== "PLAYING") return;
    const value = speedFromSlider(slider);
    syncSpeedUi(value);
    send({ type: "set_speed", speed: value });
  });

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

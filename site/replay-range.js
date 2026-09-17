(() => {
  const HISTORY_RANGES = {
    "1D": { warmup: 1380, seconds: 86400 },
    "5D": { warmup: 6900, seconds: 5 * 86400 },
    "1M": { warmup: 30360, seconds: 30 * 86400 },
    "3M": { warmup: 91080, seconds: 90 * 86400 },
  };
  const STORAGE_KEY = "futureview_history_range";
  let selectedRange = HISTORY_RANGES[localStorage.getItem(STORAGE_KEY)] ? localStorage.getItem(STORAGE_KEY) : "5D";

  function syncUi() {
    const warmup = document.getElementById("warmup");
    if (warmup) warmup.value = String(HISTORY_RANGES[selectedRange].warmup);
    document.querySelectorAll("button[data-history-range]").forEach((button) => {
      const active = button.dataset.historyRange === selectedRange;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function setRange(range, applyToChart = true) {
    if (!HISTORY_RANGES[range]) return;
    selectedRange = range;
    localStorage.setItem(STORAGE_KEY, range);
    syncUi();
    if (applyToChart) window.__futureViewChartTools?._fvSetHistoryRange?.(range);
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest?.("button[data-history-range]");
    if (!button) return;
    event.preventDefault();
    setRange(button.dataset.historyRange, true);
  }, true);

  document.addEventListener("DOMContentLoaded", syncUi);

  // Keep app.js unchanged: it already reads #warmup when starting a replay.
  // The hidden input is populated from the TradingView-style duration buttons.
  const Ctor = window.FutureViewChartTools;
  if (!Ctor) return;
  window.FutureViewChartTools = class FutureViewChartToolsWithHistoryRange extends Ctor {
    constructor(options) {
      super(options);
      this._fvHistoryRange = selectedRange;
      syncUi();
    }

    _fvSetHistoryRange(range) {
      if (!HISTORY_RANGES[range]) return;
      this._fvHistoryRange = range;
      const raw = this._fvRawBars || [];
      if (!raw.length) return;
      const to = Number(raw.at(-1).t);
      const desiredFrom = to - HISTORY_RANGES[range].seconds;
      const from = Math.max(Number(raw[0].t), desiredFrom);
      try { this.chart.timeScale().setVisibleRange({ from, to }); } catch {}
    }

    reset(rawBars) {
      super.reset(rawBars);
      requestAnimationFrame(() => this._fvSetHistoryRange(this._fvHistoryRange || selectedRange));
    }
  };
})();

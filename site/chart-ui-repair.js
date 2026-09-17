(() => {
  const Base = window.FutureViewChartTools;
  if (!Base) return;

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
  };
})();

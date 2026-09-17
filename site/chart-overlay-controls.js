(() => {
  function syncTimeframeUi(value) {
    document.querySelectorAll("button[data-timeframe]").forEach((button) => {
      const active = button.dataset.timeframe === value;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest?.("button[data-timeframe]");
    if (!button) return;
    const instance = window.__futureViewChartTools;
    if (!instance?._fvSetTimeframe) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    instance._fvSetTimeframe(button.dataset.timeframe);
    syncTimeframeUi(instance._fvTimeframe || button.dataset.timeframe);
  }, true);

  document.addEventListener("DOMContentLoaded", () => syncTimeframeUi("5"));
})();

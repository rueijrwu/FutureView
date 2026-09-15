(() => {
  const TV = window.LightweightCharts;
  if (!TV?.createChart) return;

  const createChart = TV.createChart.bind(TV);
  TV.createChart = (container, options = {}) => createChart(container, {
    ...options,
    timeScale: {
      ...(options.timeScale || {}),
      // Replay data should never force the viewport to follow the newest bar.
      // The user can explicitly jump with the Latest/Fit controls.
      shiftVisibleRangeOnNewBar: false,
    },
  });
})();

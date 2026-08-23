const fmt = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });

function deltaClass(value) {
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "";
}

function renderRanking(rows) {
  const body = document.querySelector("#ranking-body");
  body.innerHTML = "";

  if (!rows.length) {
    body.innerHTML = '<tr><td colspan="9" class="empty">No ranking snapshot yet. The dashboard is deployed and ready for data.</td></tr>';
    return;
  }

  for (const row of rows) {
    const tr = document.createElement("tr");
    const rank5d = row.rank_change_5d ?? 0;
    const rank20d = row.rank_change_20d ?? 0;
    tr.innerHTML = `
      <td>${row.rank ?? "—"}</td>
      <td class="symbol">${row.symbol ?? "—"}</td>
      <td>${fmt.format(row.stock_score ?? 0)}</td>
      <td>${fmt.format(row.rs20 ?? 0)}</td>
      <td>${fmt.format(row.rs60 ?? 0)}</td>
      <td class="${deltaClass(rank5d)}">${rank5d > 0 ? "+" : ""}${rank5d}</td>
      <td class="${deltaClass(rank20d)}">${rank20d > 0 ? "+" : ""}${rank20d}</td>
      <td>${fmt.format(row.extension_atr ?? 0)}</td>
      <td class="breakout ${row.breakout20 ? "positive" : ""}">${row.breakout20 ? "YES" : "—"}</td>
    `;
    body.appendChild(tr);
  }
}

async function loadDashboard() {
  try {
    const response = await fetch("./data/latest.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();

    const rankings = payload.rankings ?? [];
    document.querySelector("#universe-count").textContent = payload.universe_count ?? "—";
    document.querySelector("#top-count").textContent = rankings.length;
    document.querySelector("#market-regime").textContent = payload.market_regime ?? "—";
    document.querySelector("#cash-posture").textContent = payload.cash_posture ?? "—";
    document.querySelector("#as-of").textContent = payload.as_of ? `As of ${payload.as_of}` : "No market data loaded yet";
    document.querySelector("#status-text").textContent = rankings.length ? "Latest ranking loaded" : "Waiting for first ranking snapshot";

    renderRanking(rankings);
  } catch (error) {
    console.error("Unable to load FutureView dashboard data", error);
    document.querySelector("#status-text").textContent = "Dashboard data unavailable";
  }
}

loadDashboard();

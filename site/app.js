const fmt = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });

function deltaClass(value) {
  if (value === null || value === undefined) return "";
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "";
}

function formatRankChange(value) {
  if (value === null || value === undefined) return "NEW";
  return `${value > 0 ? "+" : ""}${value}`;
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
    const rank5d = row.rank_change_5d;
    const rank20d = row.rank_change_20d;
    tr.innerHTML = `
      <td>${row.rank ?? "—"}</td>
      <td class="symbol">${row.symbol ?? "—"}</td>
      <td>${fmt.format(row.stock_score ?? 0)}</td>
      <td>${fmt.format(row.rs20 ?? 0)}</td>
      <td>${fmt.format(row.rs60 ?? 0)}</td>
      <td class="${deltaClass(rank5d)}">${formatRankChange(rank5d)}</td>
      <td class="${deltaClass(rank20d)}">${formatRankChange(rank20d)}</td>
      <td>${fmt.format(row.extension_atr ?? 0)}</td>
      <td class="breakout ${row.breakout20 ? "positive" : ""}">${row.breakout20 ? "YES" : "—"}</td>
    `;
    body.appendChild(tr);
  }
}

async function fetchDashboardPayload() {
  const sources = ["/api/rankings/latest", "./data/latest.json"];

  for (const source of sources) {
    try {
      const response = await fetch(source, { cache: "no-store" });
      if (response.ok) return response.json();
    } catch (error) {
      console.warn(`Dashboard source unavailable: ${source}`, error);
    }
  }

  throw new Error("No dashboard data source is available");
}

async function loadDashboard() {
  try {
    const payload = await fetchDashboardPayload();
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

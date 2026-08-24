const scopeLabels = {
  overall_trade_win_rate: "Overall trade win rate",
  initial_entry_trade_outcomes: "Initial-entry outcomes",
  sector_top3_filter: "Top-3 sector filter",
  add_1: "Add #1",
  add_2: "Add #2",
  option_acceleration: "Option acceleration",
  mae_mfe: "MAE / MFE",
};

function pct(value, digits = 1) {
  return value === null || value === undefined ? "—" : `${(Number(value) * 100).toFixed(digits)}%`;
}

function num(value, digits = 2) {
  return value === null || value === undefined ? "—" : Number(value).toFixed(digits);
}

function money(value) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(Number(value));
}

function text(selector, value) {
  const element = document.querySelector(selector);
  if (element) element.textContent = value;
}

function renderTable(bodySelector, rows, columns) {
  const body = document.querySelector(bodySelector);
  body.innerHTML = "";
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="${columns.length}" class="empty">No data recorded for this breakdown.</td></tr>`;
    return;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = columns.map((column) => `<td>${column(row)}</td>`).join("");
    body.appendChild(tr);
  }
}

function renderAudit(audit) {
  const overall = audit.overall;
  const portfolio = audit.portfolio;
  const expectancy = overall.win_rate !== null
    && overall.average_win_return !== null
    && overall.average_loss_return !== null
    ? overall.win_rate * overall.average_win_return
      + (1 - overall.win_rate) * overall.average_loss_return
    : null;

  text("#audit-status", `${audit.strategy_version ?? "Unknown strategy"} · ${audit.status}`);
  text("#audit-range", `${audit.start_date ?? "—"} → ${audit.end_date ?? "—"}`);
  text("#win-rate", pct(overall.win_rate));
  text("#win-count", `${overall.wins} wins / ${overall.trade_count} trades`);
  text("#payoff-ratio", num(overall.payoff_ratio));
  text("#profit-factor", num(overall.profit_factor));
  text("#expectancy", pct(expectancy));
  text("#avg-win", pct(overall.average_win_return));
  text("#avg-loss", pct(overall.average_loss_return));
  text("#median-return", pct(overall.median_return));
  text("#avg-hold", overall.average_hold_sessions === null ? "—" : `${overall.average_hold_sessions.toFixed(1)}d`);
  text("#total-return", pct(portfolio.total_return));
  text("#max-drawdown", pct(portfolio.max_drawdown));
  text("#initial-capital", money(portfolio.initial_capital));
  text("#final-equity", money(portfolio.final_equity));
  text("#session-count", portfolio.session_count ?? "—");
  text("#median-hold", overall.median_hold_sessions === null ? "—" : `${overall.median_hold_sessions.toFixed(0)}d`);

  const denominator = overall.trade_count || 1;
  document.querySelector("#win-segment").style.width = `${overall.wins / denominator * 100}%`;
  document.querySelector("#flat-segment").style.width = `${overall.breakeven / denominator * 100}%`;
  document.querySelector("#loss-segment").style.width = `${overall.losses / denominator * 100}%`;
  text("#trade-legend", `Wins ${overall.wins} · Flat ${overall.breakeven} · Losses ${overall.losses}`);

  renderTable("#exit-reason-body", audit.breakdowns.by_exit_reason, [
    (row) => row.key,
    (row) => row.trade_count,
    (row) => pct(row.win_rate),
    (row) => pct(row.median_return),
    (row) => num(row.payoff_ratio),
  ]);

  if (audit.breakdowns.by_entry_rank.length) {
    document.querySelector("#rank-panel").hidden = false;
    renderTable("#rank-body", audit.breakdowns.by_entry_rank, [
      (row) => row.key,
      (row) => row.trade_count,
      (row) => pct(row.win_rate),
      (row) => pct(row.average_return),
      (row) => num(row.profit_factor),
    ]);
  }

  const scope = document.querySelector("#scope-grid");
  scope.innerHTML = "";
  for (const [key, validated] of Object.entries(audit.validation_scope ?? {})) {
    const item = document.createElement("div");
    item.className = `scope-item ${validated ? "validated" : "pending"}`;
    item.innerHTML = `<span>${validated ? "Validated" : "Not instrumented"}</span><strong>${scopeLabels[key] ?? key}</strong>`;
    scope.appendChild(item);
  }

  const notes = document.querySelector("#audit-notes");
  notes.innerHTML = (audit.notes ?? []).map((note) => `<p>${note}</p>`).join("");

  document.querySelector("#audit-status-dot").style.background = "#4fd0a0";
}

async function loadAudit() {
  try {
    const response = await fetch("/api/backtests/audit", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.error ?? "Backtest audit unavailable");
    renderAudit(payload);
  } catch (error) {
    console.error("Unable to load backtest audit", error);
    text("#audit-status", "Backtest audit unavailable");
    text("#audit-range", error.message);
    document.querySelector("#audit-status-dot").style.background = "#ff8c8c";
    document.querySelector("#exit-reason-body").innerHTML = '<tr><td colspan="5" class="empty">Backtest data is unavailable.</td></tr>';
  }
}

loadAudit();

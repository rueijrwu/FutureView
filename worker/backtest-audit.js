function finiteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function average(values) {
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function median(values) {
  if (!values.length) return null;
  const ordered = [...values].sort((a, b) => a - b);
  const middle = Math.floor(ordered.length / 2);
  if (ordered.length % 2) return ordered[middle];
  return (ordered[middle - 1] + ordered[middle]) / 2;
}

function summarizeTrades(trades) {
  const normalized = (trades ?? []).map((trade) => ({
    ...trade,
    pnl: finiteNumber(trade.pnl),
    return: finiteNumber(trade.return),
    hold_sessions: finiteNumber(trade.hold_sessions),
  }));
  const wins = normalized.filter((trade) => trade.pnl !== null && trade.pnl > 0);
  const losses = normalized.filter((trade) => trade.pnl !== null && trade.pnl < 0);
  const breakeven = normalized.filter((trade) => trade.pnl === 0);
  const winReturns = wins.map((trade) => trade.return).filter((value) => value !== null);
  const lossReturns = losses.map((trade) => trade.return).filter((value) => value !== null);
  const returns = normalized.map((trade) => trade.return).filter((value) => value !== null);
  const holds = normalized.map((trade) => trade.hold_sessions).filter((value) => value !== null);
  const grossProfit = wins.reduce((sum, trade) => sum + (trade.pnl ?? 0), 0);
  const grossLoss = Math.abs(losses.reduce((sum, trade) => sum + (trade.pnl ?? 0), 0));
  const avgWin = average(winReturns);
  const avgLoss = average(lossReturns);

  return {
    trade_count: normalized.length,
    wins: wins.length,
    losses: losses.length,
    breakeven: breakeven.length,
    win_rate: normalized.length ? wins.length / normalized.length : null,
    average_return: average(returns),
    median_return: median(returns),
    average_win_return: avgWin,
    average_loss_return: avgLoss,
    payoff_ratio: avgWin !== null && avgLoss !== null && avgLoss !== 0
      ? avgWin / Math.abs(avgLoss)
      : null,
    profit_factor: grossLoss > 0 ? grossProfit / grossLoss : null,
    average_hold_sessions: average(holds),
    median_hold_sessions: median(holds),
    gross_profit: grossProfit,
    gross_loss: grossLoss,
  };
}

function groupBy(trades, keyFn) {
  const groups = new Map();
  for (const trade of trades ?? []) {
    const key = keyFn(trade);
    if (!key) continue;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(trade);
  }
  return [...groups.entries()].map(([key, rows]) => ({
    key,
    ...summarizeTrades(rows),
  }));
}

export function buildBacktestAudit(result) {
  const trades = Array.isArray(result?.trades) ? result.trades : [];
  const overall = summarizeTrades(trades);
  const byExitReason = groupBy(trades, (trade) => String(trade.reason ?? "unknown"))
    .sort((a, b) => b.trade_count - a.trade_count);
  const byEntryRank = groupBy(trades, (trade) => {
    const rank = finiteNumber(trade.entry_rank);
    if (rank === null) return null;
    if (rank <= 3) return "1-3";
    if (rank <= 6) return "4-6";
    if (rank <= 10) return "7-10";
    return "11+";
  });

  return {
    id: result?.id ?? null,
    strategy_version: result?.strategy_version ?? null,
    start_date: result?.start_date ?? null,
    end_date: result?.end_date ?? null,
    status: result?.status ?? "unknown",
    updated_at: result?.updated_at ?? null,
    overall,
    portfolio: {
      initial_capital: finiteNumber(result?.summary?.initial_capital),
      final_equity: finiteNumber(result?.summary?.final_equity),
      total_return: finiteNumber(result?.summary?.total_return),
      max_drawdown: finiteNumber(result?.summary?.max_drawdown),
      session_count: finiteNumber(result?.summary?.session_count),
    },
    breakdowns: {
      by_exit_reason: byExitReason,
      by_entry_rank: byEntryRank,
    },
    validation_scope: {
      overall_trade_win_rate: true,
      initial_entry_trade_outcomes: true,
      sector_top3_filter: false,
      add_1: false,
      add_2: false,
      option_acceleration: false,
      mae_mfe: false,
    },
    notes: [
      "This audit reflects the currently implemented canonical backtest engine only.",
      "Sector Top-3 selection, staged add-ons, option acceleration, and MAE/MFE are not yet recorded by the current trade ledger and therefore are not presented as validated.",
    ],
  };
}

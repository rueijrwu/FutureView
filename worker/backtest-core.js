import { BACKTEST_CONFIG_V1 } from "./strategy-config.js";

function finitePositive(value) {
  return value !== null
    && value !== undefined
    && Number.isFinite(Number(value))
    && Number(value) > 0;
}

function positionsArray(state) {
  return Object.values(state.positions ?? {});
}

function markPrice(position, feature, field) {
  if (feature && finitePositive(feature[field])) return Number(feature[field]);
  return Number(position.lastClose ?? position.entryPrice);
}

function portfolioValue(state, features, field = "close") {
  let value = Number(state.cash);
  for (const position of positionsArray(state)) {
    const feature = features.get(position.symbol);
    value += Number(position.qty) * markPrice(position, feature, field);
  }
  return value;
}

export function createBacktestState(config = BACKTEST_CONFIG_V1) {
  return {
    initialCapital: Number(config.initialCapital),
    cash: Number(config.initialCapital),
    positions: {},
    pendingEntries: [],
    pendingExits: [],
    trades: [],
    equityCurve: [],
    sessionCount: 0,
  };
}

export function advanceBacktest(
  inputState,
  { date, rankings, features },
  config = BACKTEST_CONFIG_V1,
) {
  const state = structuredClone(inputState);
  const featureMap = features instanceof Map
    ? features
    : new Map((features ?? []).map((row) => [String(row.symbol), row]));

  const pendingExitSymbols = new Set(state.pendingExits.map((item) => item.symbol));
  for (const order of state.pendingExits) {
    const position = state.positions[order.symbol];
    const feature = featureMap.get(order.symbol);
    if (!position || !feature || !finitePositive(feature.open)) continue;
    const exitPrice = Number(feature.open);
    const proceeds = Number(position.qty) * exitPrice;
    state.cash += proceeds;
    const pnl = (exitPrice - Number(position.entryPrice)) * Number(position.qty);
    state.trades.push({
      symbol: order.symbol,
      entry_date: position.entryDate,
      exit_date: date,
      entry_price: Number(position.entryPrice),
      exit_price: exitPrice,
      quantity: Number(position.qty),
      hold_sessions: Number(position.holdSessions),
      reason: order.reason,
      pnl,
      return: exitPrice / Number(position.entryPrice) - 1,
    });
    delete state.positions[order.symbol];
  }
  state.pendingExits = [];

  const openingEquity = portfolioValue(state, featureMap, "open");
  for (const order of state.pendingEntries) {
    if (Object.keys(state.positions).length >= Number(config.maxPositions)) break;
    if (state.positions[order.symbol]) continue;
    const feature = featureMap.get(order.symbol);
    if (!feature || !finitePositive(feature.open)) continue;
    const allocation = Math.min(
      Number(state.cash),
      openingEquity / Number(config.maxPositions),
    );
    if (allocation <= 0) break;
    const entryPrice = Number(feature.open);
    const qty = allocation / entryPrice;
    state.cash -= allocation;
    state.positions[order.symbol] = {
      symbol: order.symbol,
      qty,
      entryPrice,
      entryDate: date,
      holdSessions: 0,
      lastClose: entryPrice,
      lastDate: date,
      entryRank: order.rank,
    };
  }
  state.pendingEntries = [];

  for (const position of positionsArray(state)) {
    const feature = featureMap.get(position.symbol);
    if (feature && finitePositive(feature.close)) {
      position.lastClose = Number(feature.close);
      position.lastDate = date;
    }
    position.holdSessions = Number(position.holdSessions) + 1;
  }

  const nextExits = [];
  for (const position of positionsArray(state)) {
    const feature = featureMap.get(position.symbol);
    const held = Number(position.holdSessions);
    if (held >= Number(config.maxHoldSessions)) {
      nextExits.push({ symbol: position.symbol, reason: "max_hold" });
      continue;
    }
    if (
      config.exitBelowSma10
      && held >= Number(config.minHoldSessions)
      && feature
      && finitePositive(feature.close)
      && finitePositive(feature.sma10)
      && Number(feature.close) < Number(feature.sma10)
    ) {
      nextExits.push({ symbol: position.symbol, reason: "below_sma10" });
    }
  }
  state.pendingExits = nextExits;

  const projectedExits = new Set(nextExits.map((item) => item.symbol));
  const projectedPositions = Object.keys(state.positions)
    .filter((symbol) => !projectedExits.has(symbol)).length;
  let availableSlots = Math.max(0, Number(config.maxPositions) - projectedPositions);

  const nextEntries = [];
  const ordered = [...(rankings ?? [])].sort((a, b) => Number(a.rank) - Number(b.rank));
  for (const row of ordered) {
    if (availableSlots <= 0) break;
    const symbol = String(row.symbol);
    if (Number(row.rank) > Number(config.entryRankMax)) continue;
    if (config.requireBreakout20 && !row.breakout20) continue;
    if (state.positions[symbol] && !projectedExits.has(symbol)) continue;
    if (pendingExitSymbols.has(symbol)) continue;
    nextEntries.push({ symbol, rank: Number(row.rank) });
    availableSlots -= 1;
  }
  state.pendingEntries = nextEntries;

  const equity = portfolioValue(state, featureMap, "close");
  state.equityCurve.push({
    date,
    equity,
    cash: Number(state.cash),
    positions: Object.keys(state.positions).length,
  });
  state.sessionCount += 1;
  return state;
}

function maxDrawdown(equityCurve) {
  let peak = -Infinity;
  let worst = 0;
  for (const point of equityCurve) {
    const value = Number(point.equity);
    peak = Math.max(peak, value);
    if (peak > 0) worst = Math.min(worst, value / peak - 1);
  }
  return worst;
}

export function finalizeBacktest(inputState, config = BACKTEST_CONFIG_V1) {
  const state = structuredClone(inputState);
  const finalPoint = state.equityCurve.at(-1) ?? {
    date: null,
    equity: Number(state.cash),
  };

  for (const position of positionsArray(state)) {
    const exitPrice = Number(position.lastClose ?? position.entryPrice);
    const proceeds = Number(position.qty) * exitPrice;
    state.cash += proceeds;
    const pnl = (exitPrice - Number(position.entryPrice)) * Number(position.qty);
    state.trades.push({
      symbol: position.symbol,
      entry_date: position.entryDate,
      exit_date: finalPoint.date,
      entry_price: Number(position.entryPrice),
      exit_price: exitPrice,
      quantity: Number(position.qty),
      hold_sessions: Number(position.holdSessions),
      reason: "backtest_end",
      pnl,
      return: exitPrice / Number(position.entryPrice) - 1,
    });
  }
  state.positions = {};
  state.pendingEntries = [];
  state.pendingExits = [];

  const finalEquity = Number(state.cash);
  const wins = state.trades.filter((trade) => Number(trade.pnl) > 0).length;
  return {
    ...state,
    finalEquity,
    summary: {
      initial_capital: Number(config.initialCapital),
      final_equity: finalEquity,
      total_return: finalEquity / Number(config.initialCapital) - 1,
      max_drawdown: maxDrawdown(state.equityCurve),
      trade_count: state.trades.length,
      win_rate: state.trades.length ? wins / state.trades.length : null,
      session_count: state.sessionCount,
    },
  };
}

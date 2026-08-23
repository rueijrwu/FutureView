const DEFAULT_CONFIG = Object.freeze({
  minPrice: 10.0,
  minAvgDollarVolume20: 50_000_000,
  maxExtensionAtr: 3.0,
  rs20Weight: 0.25,
  rs60Weight: 0.20,
  trendWeight: 0.20,
  breakoutWeight: 0.15,
  volumeWeight: 0.10,
  persistenceWeight: 0.10,
  persistenceLookback: 20,
  extensionPenaltyStartAtr: 1.5,
  extensionPenaltyMax: 0.12,
});

function finite(value) {
  return Number.isFinite(Number(value));
}

function averagePercentileRanks(rows, field) {
  const ordered = rows
    .map((row, index) => ({ index, value: Number(row[field]) }))
    .sort((a, b) => a.value - b.value);
  const ranks = new Array(rows.length);
  let start = 0;
  while (start < ordered.length) {
    let end = start + 1;
    while (end < ordered.length && ordered[end].value === ordered[start].value) end += 1;
    const averageRank = ((start + 1) + end) / 2;
    const percentile = averageRank / rows.length;
    for (let i = start; i < end; i += 1) ranks[ordered[i].index] = percentile;
    start = end;
  }
  return ranks;
}

function ordinalDescending(rows, field) {
  return [...rows]
    .sort((a, b) => {
      const delta = Number(b[field]) - Number(a[field]);
      if (delta !== 0) return delta;
      return Number(a.__inputOrder) - Number(b.__inputOrder);
    })
    .map((row, index) => ({ ...row, __ordinalRank: index + 1 }));
}

function priorRankingState(priorStates, symbol, priorSessionCount) {
  const existing = priorStates?.get?.(symbol) ?? priorStates?.[symbol];
  if (existing) return existing;
  return {
    symbol,
    base_top50_flags: Array(Math.min(priorSessionCount, 19)).fill(0),
    rank_history: Array(Math.min(priorSessionCount, 20)).fill(null),
  };
}

function persistenceScore(state, isBaseTop50, lookback) {
  const flags = [...(state.base_top50_flags ?? []), isBaseTop50 ? 1 : 0].slice(-lookback);
  if (!flags.length) return 0;
  return flags.reduce((sum, value) => sum + Number(value), 0) / flags.length;
}

function rankChanges(state, currentRank) {
  const history = state.rank_history ?? [];
  const prior5 = history.length >= 5 ? history.at(-5) : null;
  const prior20 = history.length >= 20 ? history.at(-20) : null;
  return {
    rank_change_5d: prior5 == null ? null : Number(prior5) - currentRank,
    rank_change_20d: prior20 == null ? null : Number(prior20) - currentRank,
  };
}

function advanceState(state, symbol, tradingDate, isBaseTop50, currentRank) {
  return {
    symbol,
    as_of: tradingDate,
    base_top50_flags: [
      ...(state.base_top50_flags ?? []),
      isBaseTop50 ? 1 : 0,
    ].slice(-19),
    rank_history: [
      ...(state.rank_history ?? []),
      currentRank == null ? null : Number(currentRank),
    ].slice(-20),
  };
}

function passesHardFilters(row, config) {
  return (
    finite(row.close)
    && finite(row.sma50)
    && finite(row.sma200)
    && finite(row.sma50_slope10)
    && finite(row.avg_dollar_volume20)
    && finite(row.extension_atr)
    && finite(row.rs20)
    && finite(row.rs60)
    && Number(row.close) >= config.minPrice
    && Number(row.avg_dollar_volume20) >= config.minAvgDollarVolume20
    && Number(row.extension_atr) <= config.maxExtensionAtr
    && Number(row.close) > Number(row.sma50)
    && Number(row.sma50) > Number(row.sma200)
    && Number(row.sma50_slope10) > 0
    && Number(row.rs20) > 0
    && Number(row.rs60) > 0
  );
}

function extensionPenalty(extensionAtr, config) {
  const width = Math.max(3.0 - config.extensionPenaltyStartAtr, 1e-9);
  const scaled = Math.min(
    1,
    Math.max(0, (Number(extensionAtr) - config.extensionPenaltyStartAtr) / width),
  );
  return config.extensionPenaltyMax * scaled ** 2;
}

export function rankCrossSection({
  features,
  tradingDate,
  eligibleSymbols,
  priorStates = new Map(),
  priorSessionCount = 0,
  benchmarkSymbol = "SPY",
  config = DEFAULT_CONFIG,
}) {
  const benchmark = features.find((row) => String(row.symbol) === benchmarkSymbol);
  if (!benchmark || !finite(benchmark.return20) || !finite(benchmark.return60)) {
    throw new Error(`benchmark ${benchmarkSymbol} is missing valid return20/return60`);
  }

  const eligible = eligibleSymbols instanceof Set ? eligibleSymbols : new Set(eligibleSymbols ?? []);
  const benchmarkReturn20 = Number(benchmark.return20);
  const benchmarkReturn60 = Number(benchmark.return60);

  const candidates = features
    .filter((row) => eligible.has(String(row.symbol)))
    .map((row, index) => ({
      ...row,
      __inputOrder: index,
      rs20: Number(row.return20) - benchmarkReturn20,
      rs60: Number(row.return60) - benchmarkReturn60,
    }))
    .filter((row) => passesHardFilters(row, config));

  if (!candidates.length) {
    return { rankings: [], states: new Map(), candidateCount: 0 };
  }

  const rs20Ranks = averagePercentileRanks(candidates, "rs20");
  const rs60Ranks = averagePercentileRanks(candidates, "rs60");
  const volumeRanks = averagePercentileRanks(candidates, "volume_ratio20");

  const scored = candidates.map((row, index) => {
    const trendScore = (
      Number(Number(row.close) > Number(row.sma20))
      + Number(Number(row.sma20) > Number(row.sma50))
      + Number(Number(row.sma50) > Number(row.sma200))
      + Number(Number(row.sma50_slope10) > 0)
    ) / 4;
    const proximity = Math.min(
      1,
      Math.max(0, 1 + Number(row.distance_from_high20) / 0.05),
    );
    const breakoutScore = row.breakout20 ? 1 : proximity;
    const baseScore = (
      config.rs20Weight * rs20Ranks[index]
      + config.rs60Weight * rs60Ranks[index]
      + config.trendWeight * trendScore
      + config.breakoutWeight * breakoutScore
      + config.volumeWeight * volumeRanks[index]
    );
    return {
      ...row,
      rs20_rank: rs20Ranks[index],
      rs60_rank: rs60Ranks[index],
      volume_rank: volumeRanks[index],
      trend_score: trendScore,
      breakout_score: breakoutScore,
      base_score: baseScore,
    };
  });

  const withBaseRank = ordinalDescending(scored, "base_score").map((row) => ({
    ...row,
    base_rank: row.__ordinalRank,
  }));

  const withStockScore = withBaseRank.map((row) => {
    const state = priorRankingState(priorStates, String(row.symbol), priorSessionCount);
    const persistence = persistenceScore(
      state,
      Number(row.base_rank) <= 50,
      config.persistenceLookback,
    );
    const penalty = extensionPenalty(row.extension_atr, config);
    return {
      ...row,
      persistence_score: persistence,
      extension_penalty: penalty,
      stock_score: row.base_score + config.persistenceWeight * persistence - penalty,
    };
  });

  const ranked = ordinalDescending(withStockScore, "stock_score").map((row) => {
    const rank = row.__ordinalRank;
    const state = priorRankingState(priorStates, String(row.symbol), priorSessionCount);
    return {
      ...row,
      rank,
      ...rankChanges(state, rank),
    };
  });

  const currentBySymbol = new Map(ranked.map((row) => [String(row.symbol), row]));
  const stateSymbols = new Set([
    ...Array.from(priorStates instanceof Map ? priorStates.keys() : Object.keys(priorStates ?? {})),
    ...ranked.map((row) => String(row.symbol)),
  ]);
  const states = new Map();
  for (const symbol of stateSymbols) {
    const state = priorRankingState(priorStates, symbol, priorSessionCount);
    const row = currentBySymbol.get(symbol);
    states.set(
      symbol,
      advanceState(
        state,
        symbol,
        tradingDate,
        row ? Number(row.base_rank) <= 50 : false,
        row ? Number(row.rank) : null,
      ),
    );
  }

  const cleanRankings = ranked
    .map(({ __inputOrder, __ordinalRank, ...row }) => row)
    .sort((a, b) => Number(a.rank) - Number(b.rank));
  return {
    rankings: cleanRankings,
    states,
    candidateCount: cleanRankings.length,
  };
}

export { DEFAULT_CONFIG as RANKING_CONFIG_V2 };

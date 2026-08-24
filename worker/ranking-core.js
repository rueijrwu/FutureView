import { RANKING_CONFIG_V2 } from "./strategy-config.js";

const RANKING_KEY_DECIMALS = 12;

function finite(value) {
  return value !== null
    && value !== undefined
    && value !== ""
    && Number.isFinite(Number(value));
}

function quantizeRankingKey(value) {
  return Number(Number(value).toFixed(RANKING_KEY_DECIMALS));
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
      const aKey = quantizeRankingKey(a[field]);
      const bKey = quantizeRankingKey(b[field]);
      if (bKey !== aKey) return bKey - aKey;
      const aSymbol = String(a.symbol);
      const bSymbol = String(b.symbol);
      if (aSymbol < bSymbol) return -1;
      if (aSymbol > bSymbol) return 1;
      return 0;
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
    && (!config.sectorAwareRelativeStrength || (
      finite(row.sector_rs20)
      && finite(row.sector_rs60)
      && row.sector_benchmark_symbol
    ))
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

function mappedBenchmark(sectorBenchmarkBySymbol, symbol) {
  if (!sectorBenchmarkBySymbol) return null;
  return sectorBenchmarkBySymbol?.get?.(symbol) ?? sectorBenchmarkBySymbol?.[symbol] ?? null;
}

export function rankCrossSection({
  features,
  tradingDate,
  eligibleSymbols,
  priorStates = new Map(),
  priorSessionCount = 0,
  benchmarkSymbol = "SPY",
  sectorBenchmarkBySymbol = null,
  config = RANKING_CONFIG_V2,
}) {
  const featureBySymbol = new Map(features.map((row) => [String(row.symbol), row]));
  const benchmark = featureBySymbol.get(benchmarkSymbol);
  if (!benchmark || !finite(benchmark.return20) || !finite(benchmark.return60)) {
    throw new Error(`benchmark ${benchmarkSymbol} is missing valid return20/return60`);
  }

  const eligible = eligibleSymbols instanceof Set ? eligibleSymbols : new Set(eligibleSymbols ?? []);
  const benchmarkReturn20 = Number(benchmark.return20);
  const benchmarkReturn60 = Number(benchmark.return60);

  const candidates = features
    .filter((row) => eligible.has(String(row.symbol)))
    .map((row, index) => {
      const symbol = String(row.symbol);
      const sectorBenchmarkSymbol = mappedBenchmark(sectorBenchmarkBySymbol, symbol);
      const sectorBenchmark = sectorBenchmarkSymbol
        ? featureBySymbol.get(String(sectorBenchmarkSymbol))
        : null;
      const rs20 = Number(row.return20) - benchmarkReturn20;
      const rs60 = Number(row.return60) - benchmarkReturn60;
      return {
        ...row,
        __inputOrder: index,
        // Compatibility fields remain the market-relative SPY values.
        rs20,
        rs60,
        market_rs20: rs20,
        market_rs60: rs60,
        sector_benchmark_symbol: sectorBenchmarkSymbol == null ? null : String(sectorBenchmarkSymbol),
        sector_rs20: sectorBenchmark && finite(sectorBenchmark.return20)
          ? Number(row.return20) - Number(sectorBenchmark.return20)
          : null,
        sector_rs60: sectorBenchmark && finite(sectorBenchmark.return60)
          ? Number(row.return60) - Number(sectorBenchmark.return60)
          : null,
      };
    })
    .filter((row) => passesHardFilters(row, config));

  if (!candidates.length) {
    return { rankings: [], states: new Map(), candidateCount: 0 };
  }

  const rs20Ranks = averagePercentileRanks(candidates, "rs20");
  const rs60Ranks = averagePercentileRanks(candidates, "rs60");
  const sectorRs20Ranks = config.sectorAwareRelativeStrength
    ? averagePercentileRanks(candidates, "sector_rs20")
    : null;
  const sectorRs60Ranks = config.sectorAwareRelativeStrength
    ? averagePercentileRanks(candidates, "sector_rs60")
    : null;
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
    const relativeStrengthScore = config.sectorAwareRelativeStrength
      ? (
        config.marketRs20Weight * rs20Ranks[index]
        + config.marketRs60Weight * rs60Ranks[index]
        + config.sectorRs20Weight * sectorRs20Ranks[index]
        + config.sectorRs60Weight * sectorRs60Ranks[index]
      )
      : (
        config.rs20Weight * rs20Ranks[index]
        + config.rs60Weight * rs60Ranks[index]
      );
    const baseScore = (
      relativeStrengthScore
      + config.trendWeight * trendScore
      + config.breakoutWeight * breakoutScore
      + config.volumeWeight * volumeRanks[index]
    );
    return {
      ...row,
      rs20_rank: rs20Ranks[index],
      rs60_rank: rs60Ranks[index],
      market_rs20_rank: rs20Ranks[index],
      market_rs60_rank: rs60Ranks[index],
      sector_rs20_rank: sectorRs20Ranks?.[index] ?? null,
      sector_rs60_rank: sectorRs60Ranks?.[index] ?? null,
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

export { RANKING_CONFIG_V2 };

export const STRATEGY_VERSION = "momentum-v2";

export const RANKING_CONFIG_V2 = Object.freeze({
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

// Research baseline. This is intentionally separate from live ranking rules so
// position-management assumptions can evolve without changing stock selection.
export const BACKTEST_CONFIG_V1 = Object.freeze({
  initialCapital: 100_000,
  maxPositions: 10,
  entryRankMax: 10,
  requireBreakout20: true,
  minHoldSessions: 15,
  maxHoldSessions: 60,
  exitBelowSma10: true,
});

export const STRATEGY_VERSION = "rightside-v3";

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

// Local-only research experiment. Production ranking keeps RANKING_CONFIG_V2
// unless this config is explicitly supplied by the caller.
// The total relative-strength weight remains 45%, but it is split between
// market-relative (SPY) and closest-sector-ETF-relative strength.
export const RANKING_CONFIG_SECTOR_RS_EXPERIMENT = Object.freeze({
  ...RANKING_CONFIG_V2,
  sectorAwareRelativeStrength: true,
  marketRs20Weight: 0.10,
  marketRs60Weight: 0.10,
  sectorRs20Weight: 0.15,
  sectorRs60Weight: 0.10,
});

// Research baseline for the right-side swing strategy. Sector selection and
// staged adds are intentionally separate follow-on layers; this config only
// contains rules supported by the current feature set.
export const BACKTEST_CONFIG_V2 = Object.freeze({
  initialCapital: 100_000,
  maxPositions: 9,
  entryRankMax: 50,
  requireBreakout20: true,
  requireCloseAboveSma5: true,
  requireCloseAboveSma10: true,
  requireCloseAboveSma20: true,
  requireSma5AboveSma10: true,
  requireSma10AboveSma20: true,
  minVolumeRatio20: 0.8,
  maxEntryExtensionAtr: 2.5,
  minHoldSessions: 15,
  maxHoldSessions: 60,
  exitBelowSma10: true,
});

// Compatibility alias for older imports while the v3 migration is completed.
export const BACKTEST_CONFIG_V1 = BACKTEST_CONFIG_V2;

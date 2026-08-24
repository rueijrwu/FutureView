import assert from "node:assert/strict";
import test from "node:test";

import { rankCrossSection } from "../worker/ranking-core.js";

function feature(symbol, overrides = {}) {
  return {
    symbol,
    return20: 0.2,
    return60: 0.3,
    close: 120,
    sma20: 110,
    sma50: 100,
    sma200: 90,
    sma50_slope10: 0.05,
    avg_dollar_volume20: 100_000_000,
    extension_atr: 1.0,
    volume_ratio20: 1.2,
    distance_from_high20: -0.01,
    breakout20: false,
    ...overrides,
  };
}

function benchmark() {
  return {
    symbol: "SPY",
    return20: 0.05,
    return60: 0.08,
  };
}

test("equal scores use deterministic symbol ordering", () => {
  const result = rankCrossSection({
    features: [benchmark(), feature("BBB"), feature("AAA")],
    tradingDate: "2026-08-20",
    eligibleSymbols: new Set(["AAA", "BBB"]),
  });

  assert.deepEqual(result.rankings.map((row) => row.symbol), ["AAA", "BBB"]);
  assert.deepEqual(result.rankings.map((row) => row.rank), [1, 2]);
});

test("missing numeric inputs never become zero-valued candidates", () => {
  const result = rankCrossSection({
    features: [
      benchmark(),
      feature("GOOD"),
      feature("NULL_CLOSE", { close: null }),
      feature("NULL_RS", { return20: null }),
    ],
    tradingDate: "2026-08-20",
    eligibleSymbols: new Set(["GOOD", "NULL_CLOSE", "NULL_RS"]),
  });

  assert.equal(result.candidateCount, 1);
  assert.equal(result.rankings[0].symbol, "GOOD");
});

test("ranking state advances persistence and rank history", () => {
  const priorStates = new Map([
    ["AAA", {
      symbol: "AAA",
      as_of: "2026-08-19",
      base_top50_flags: [1, 1, 0, 1],
      rank_history: [10, 8, 9, 7, 6],
    }],
  ]);
  const result = rankCrossSection({
    features: [benchmark(), feature("AAA")],
    tradingDate: "2026-08-20",
    eligibleSymbols: new Set(["AAA"]),
    priorStates,
    priorSessionCount: 5,
  });

  const state = result.states.get("AAA");
  assert.equal(state.as_of, "2026-08-20");
  assert.equal(state.base_top50_flags.at(-1), 1);
  assert.equal(state.rank_history.at(-1), 1);
  assert.equal(result.rankings[0].rank_change_5d, 9);
});

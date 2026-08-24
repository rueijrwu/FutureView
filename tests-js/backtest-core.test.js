import assert from "node:assert/strict";
import test from "node:test";

import {
  advanceBacktest,
  createBacktestState,
  finalizeBacktest,
  passesEntrySetup,
} from "../worker/backtest-core.js";
import { BACKTEST_CONFIG_V2 } from "../worker/strategy-config.js";

function feature(symbol, { open, close, sma10 = close } = {}) {
  return { symbol, open, close, sma10 };
}

function ranking(symbol, rank = 1, overrides = {}) {
  return {
    symbol,
    rank,
    breakout20: true,
    close: 110,
    sma5: 106,
    sma10: 103,
    sma20: 100,
    volume_ratio20: 1.0,
    extension_atr: 1.0,
    ...overrides,
  };
}

test("right-side entry gate requires MA stack, volume, breakout, and bounded extension", () => {
  assert.equal(passesEntrySetup(ranking("AAA"), BACKTEST_CONFIG_V2), true);
  assert.equal(passesEntrySetup(ranking("AAA", 1, { breakout20: false }), BACKTEST_CONFIG_V2), false);
  assert.equal(passesEntrySetup(ranking("AAA", 1, { sma5: 102, sma10: 103 }), BACKTEST_CONFIG_V2), false);
  assert.equal(passesEntrySetup(ranking("AAA", 1, { volume_ratio20: 0.79 }), BACKTEST_CONFIG_V2), false);
  assert.equal(passesEntrySetup(ranking("AAA", 1, { extension_atr: 2.51 }), BACKTEST_CONFIG_V2), false);
  assert.equal(passesEntrySetup(ranking("AAA", 51), BACKTEST_CONFIG_V2), false);
});

test("entry signals execute on the next session open", () => {
  let state = createBacktestState(BACKTEST_CONFIG_V2);
  state = advanceBacktest(state, {
    date: "2026-08-20",
    rankings: [ranking("AAA")],
    features: new Map([["AAA", feature("AAA", { open: 100, close: 110 })]]),
  });

  assert.equal(Object.keys(state.positions).length, 0);
  assert.equal(state.pendingEntries[0].symbol, "AAA");

  state = advanceBacktest(state, {
    date: "2026-08-21",
    rankings: [],
    features: new Map([["AAA", feature("AAA", { open: 120, close: 125 })]]),
  });

  assert.equal(state.positions.AAA.entryPrice, 120);
  assert.equal(state.positions.AAA.entryDate, "2026-08-21");
});

test("exit signals execute on the next session open", () => {
  const config = {
    ...BACKTEST_CONFIG_V2,
    minHoldSessions: 1,
    maxHoldSessions: 60,
  };
  let state = createBacktestState(config);

  state = advanceBacktest(state, {
    date: "2026-08-20",
    rankings: [ranking("AAA")],
    features: new Map([["AAA", feature("AAA", { open: 100, close: 105 })]]),
  }, config);
  state = advanceBacktest(state, {
    date: "2026-08-21",
    rankings: [],
    features: new Map([["AAA", feature("AAA", { open: 110, close: 90, sma10: 100 })]]),
  }, config);

  assert.equal(state.positions.AAA.entryPrice, 110);
  assert.equal(state.pendingExits[0].reason, "below_sma10");

  state = advanceBacktest(state, {
    date: "2026-08-24",
    rankings: [],
    features: new Map([["AAA", feature("AAA", { open: 80, close: 82, sma10: 95 })]]),
  }, config);

  assert.equal(state.positions.AAA, undefined);
  assert.equal(state.trades.length, 1);
  assert.equal(state.trades[0].exit_price, 80);
  assert.equal(state.trades[0].exit_date, "2026-08-24");
});

test("finalization liquidates remaining positions at last known close", () => {
  const config = { ...BACKTEST_CONFIG_V2, minHoldSessions: 100 };
  let state = createBacktestState(config);
  state = advanceBacktest(state, {
    date: "2026-08-20",
    rankings: [ranking("AAA")],
    features: new Map([["AAA", feature("AAA", { open: 100, close: 100 })]]),
  }, config);
  state = advanceBacktest(state, {
    date: "2026-08-21",
    rankings: [],
    features: new Map([["AAA", feature("AAA", { open: 100, close: 110 })]]),
  }, config);

  const result = finalizeBacktest(state, config);
  assert.equal(result.trades.length, 1);
  assert.equal(result.trades[0].reason, "backtest_end");
  assert.ok(result.summary.total_return > 0);
});

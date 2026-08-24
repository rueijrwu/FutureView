import test from "node:test";
import assert from "node:assert/strict";

import { buildBacktestAudit } from "../worker/backtest-audit.js";

test("buildBacktestAudit calculates win rate and payoff metrics", () => {
  const audit = buildBacktestAudit({
    id: "sample",
    strategy_version: "test",
    status: "complete",
    summary: {
      initial_capital: 100000,
      final_equity: 105000,
      total_return: 0.05,
      max_drawdown: -0.08,
      session_count: 60,
    },
    trades: [
      { pnl: 1000, return: 0.10, hold_sessions: 20, reason: "below_sma10", entry_rank: 2 },
      { pnl: -500, return: -0.05, hold_sessions: 10, reason: "below_sma10", entry_rank: 8 },
      { pnl: 2000, return: 0.20, hold_sessions: 30, reason: "max_hold", entry_rank: 4 },
    ],
  });

  assert.equal(audit.overall.trade_count, 3);
  assert.equal(audit.overall.wins, 2);
  assert.equal(audit.overall.losses, 1);
  assert.equal(audit.overall.win_rate, 2 / 3);
  assert.equal(audit.overall.average_win_return, 0.15);
  assert.equal(audit.overall.average_loss_return, -0.05);
  assert.equal(audit.overall.payoff_ratio, 3);
  assert.equal(audit.overall.profit_factor, 6);
  assert.equal(audit.overall.median_return, 0.10);
  assert.equal(audit.overall.break_even_win_rate, 0.25);
  assert.equal(audit.overall.win_rate_edge, (2 / 3) - 0.25);
  assert.equal(audit.overall.sample_label, "early");
  assert.ok(audit.overall.win_rate_ci95_low < audit.overall.win_rate);
  assert.ok(audit.overall.win_rate_ci95_high > audit.overall.win_rate);
  assert.deepEqual(audit.breakdowns.by_entry_rank.map((row) => row.key), ["1-3", "4-6", "7-10"]);
  assert.deepEqual(audit.breakdowns.by_hold_period.map((row) => row.key), ["1-15", "16-30"]);
  assert.equal(audit.breakdowns.by_exit_reason.length, 2);
  assert.equal(audit.validation_scope.entry_rank_buckets, true);
  assert.equal(audit.validation_scope.hold_period_buckets, true);
  assert.equal(audit.validation_scope.sector_top3_filter, false);
});

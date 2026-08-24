import React, { useEffect, useMemo, useState } from 'react';

type Summary = {
  trade_count: number;
  wins: number;
  losses: number;
  breakeven: number;
  win_rate: number | null;
  win_rate_ci95_low: number | null;
  win_rate_ci95_high: number | null;
  break_even_win_rate: number | null;
  win_rate_edge: number | null;
  sample_label: 'early' | 'developing' | 'stronger';
  average_return: number | null;
  median_return: number | null;
  average_win_return: number | null;
  average_loss_return: number | null;
  payoff_ratio: number | null;
  profit_factor: number | null;
  average_hold_sessions: number | null;
  median_hold_sessions: number | null;
  gross_profit: number;
  gross_loss: number;
};

type Breakdown = Summary & { key: string };

type Audit = {
  id: string | null;
  strategy_version: string | null;
  start_date: string | null;
  end_date: string | null;
  status: string;
  updated_at: string | null;
  overall: Summary;
  portfolio: {
    initial_capital: number | null;
    final_equity: number | null;
    total_return: number | null;
    max_drawdown: number | null;
    session_count: number | null;
  };
  breakdowns: {
    by_exit_reason: Breakdown[];
    by_entry_rank: Breakdown[];
    by_hold_period: Breakdown[];
  };
  validation_scope: Record<string, boolean>;
  notes: string[];
};

const pct = (value: number | null, digits = 2) => value === null ? 'n/a' : `${(value * 100).toFixed(digits)}%`;
const num = (value: number | null, digits = 2) => value === null ? 'n/a' : value.toFixed(digits);
const money = (value: number | null) => value === null ? 'n/a' : new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', maximumFractionDigits: 0,
}).format(value);
const sessions = (value: number | null) => value === null ? 'n/a' : String(value);

const scopeLabels: Record<string, string> = {
  overall_trade_win_rate: 'overall trade win rate',
  initial_entry_trade_outcomes: 'initial-entry outcomes',
  entry_rank_buckets: 'entry-rank buckets',
  hold_period_buckets: 'holding-period buckets',
  sector_top3_filter: 'top-3 sector filter',
  add_1: 'add #1',
  add_2: 'add #2',
  option_acceleration: 'option acceleration',
  mae_mfe: 'MAE / MFE',
};

function appendBreakdown(lines: string[], title: string, rows: Breakdown[], fields: (row: Breakdown) => string) {
  lines.push('', title);
  if (!rows.length) {
    lines.push('- none');
    return;
  }
  for (const row of rows) lines.push(`- ${row.key}: ${fields(row)}`);
}

function formatAudit(audit: Audit) {
  const { overall, portfolio } = audit;
  const expectancy = overall.average_win_return !== null && overall.average_loss_return !== null && overall.win_rate !== null
    ? overall.win_rate * overall.average_win_return + (1 - overall.win_rate) * overall.average_loss_return
    : null;

  const lines = [
    '[FutureView Backtest]',
    '',
    'Run',
    `- id: ${audit.id ?? 'n/a'}`,
    `- strategy: ${audit.strategy_version ?? 'n/a'}`,
    `- status: ${audit.status}`,
    `- period: ${audit.start_date ?? 'n/a'} -> ${audit.end_date ?? 'n/a'}`,
    `- sessions: ${sessions(portfolio.session_count)}`,
    `- updated_at: ${audit.updated_at ?? 'n/a'}`,
    '',
    'Portfolio',
    `- initial capital: ${money(portfolio.initial_capital)}`,
    `- final equity: ${money(portfolio.final_equity)}`,
    `- total return: ${pct(portfolio.total_return)}`,
    `- max drawdown: ${pct(portfolio.max_drawdown)}`,
    '',
    'Trades',
    `- total: ${overall.trade_count}`,
    `- wins: ${overall.wins}`,
    `- losses: ${overall.losses}`,
    `- breakeven: ${overall.breakeven}`,
    `- win rate: ${pct(overall.win_rate)}`,
    `- win rate 95% CI: ${pct(overall.win_rate_ci95_low)} -> ${pct(overall.win_rate_ci95_high)}`,
    `- break-even win rate: ${pct(overall.break_even_win_rate)}`,
    `- win-rate edge: ${pct(overall.win_rate_edge)}`,
    `- average return: ${pct(overall.average_return)}`,
    `- median return: ${pct(overall.median_return)}`,
    `- average win: ${pct(overall.average_win_return)}`,
    `- average loss: ${pct(overall.average_loss_return)}`,
    `- payoff ratio: ${num(overall.payoff_ratio)}`,
    `- profit factor: ${num(overall.profit_factor)}`,
    `- expectancy / trade: ${pct(expectancy)}`,
    `- gross profit: ${money(overall.gross_profit)}`,
    `- gross loss: ${money(overall.gross_loss)}`,
    `- average hold: ${overall.average_hold_sessions === null ? 'n/a' : `${overall.average_hold_sessions.toFixed(1)} sessions`}`,
    `- median hold: ${overall.median_hold_sessions === null ? 'n/a' : `${overall.median_hold_sessions.toFixed(1)} sessions`}`,
    `- evidence: ${overall.sample_label}`,
  ];

  appendBreakdown(
    lines,
    'Entry Rank',
    audit.breakdowns.by_entry_rank,
    (row) => `trades=${row.trade_count}, win_rate=${pct(row.win_rate)}, avg_return=${pct(row.average_return)}, profit_factor=${num(row.profit_factor)}`,
  );

  appendBreakdown(
    lines,
    'Holding Period',
    audit.breakdowns.by_hold_period,
    (row) => `trades=${row.trade_count}, win_rate=${pct(row.win_rate)}, median_return=${pct(row.median_return)}`,
  );

  appendBreakdown(
    lines,
    'Exit Reasons',
    audit.breakdowns.by_exit_reason,
    (row) => `trades=${row.trade_count}, win_rate=${pct(row.win_rate)}, median_return=${pct(row.median_return)}, payoff=${num(row.payoff_ratio)}`,
  );

  lines.push('', 'Validation Scope');
  for (const [key, validated] of Object.entries(audit.validation_scope)) {
    lines.push(`- ${scopeLabels[key] ?? key}: ${validated ? 'validated' : 'not instrumented'}`);
  }

  lines.push('', 'Notes');
  if (audit.notes.length) {
    for (const note of audit.notes) lines.push(`- ${note}`);
  } else {
    lines.push('- none');
  }

  return lines.join('\n');
}

const Backtest: React.FC = () => {
  const [audit, setAudit] = useState<Audit | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    fetch('/api/backtests/audit', { cache: 'no-store' })
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(body?.error ?? 'Backtest audit is unavailable');
        return body as Audit;
      })
      .then((body) => { if (active) setAudit(body); })
      .catch((reason: Error) => { if (active) setError(reason.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const output = useMemo(() => audit ? formatAudit(audit) : '', [audit]);

  if (loading) return <pre>[FutureView Backtest]{'\n'}status: loading</pre>;
  if (error || !audit) return <pre>[FutureView Backtest]{'\n'}status: error{'\n'}error: {error ?? 'audit unavailable'}</pre>;

  return <pre>{output}</pre>;
};

export default Backtest;

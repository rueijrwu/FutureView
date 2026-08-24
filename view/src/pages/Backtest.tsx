import React, { useEffect, useState } from 'react';
import './Backtest.css';

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

const pct = (value: number | null, digits = 1) => value === null ? '—' : `${(value * 100).toFixed(digits)}%`;
const num = (value: number | null, digits = 2) => value === null ? '—' : value.toFixed(digits);
const money = (value: number | null) => value === null ? '—' : new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', maximumFractionDigits: 0,
}).format(value);

const scopeLabels: Record<string, string> = {
  overall_trade_win_rate: 'Overall trade win rate',
  initial_entry_trade_outcomes: 'Initial-entry outcomes',
  entry_rank_buckets: 'Entry-rank buckets',
  hold_period_buckets: 'Holding-period buckets',
  sector_top3_filter: 'Top-3 sector filter',
  add_1: 'Add #1',
  add_2: 'Add #2',
  option_acceleration: 'Option acceleration',
  mae_mfe: 'MAE / MFE',
};

const sampleText: Record<Summary['sample_label'], string> = {
  early: 'Early sample (<30 trades)',
  developing: 'Developing sample (30–99 trades)',
  stronger: 'Stronger sample (100+ trades)',
};

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

  if (loading) return <main className="backtest-page"><div className="audit-state">Loading backtest audit…</div></main>;
  if (error || !audit) return <main className="backtest-page"><div className="audit-state audit-error">{error ?? 'Audit unavailable'}</div></main>;

  const { overall, portfolio } = audit;
  const expectancy = overall.average_win_return !== null && overall.average_loss_return !== null && overall.win_rate !== null
    ? overall.win_rate * overall.average_win_return + (1 - overall.win_rate) * overall.average_loss_return
    : null;
  const economicallyPositive = overall.win_rate_edge !== null && overall.win_rate_edge > 0;

  return (
    <main className="backtest-page">
      <header className="audit-header">
        <div>
          <p className="eyebrow">Strategy validation</p>
          <h1>Win-Rate Audit</h1>
          <p className="audit-subtitle">Historical validation from local D1/R2 snapshot through the canonical JS backtest result.</p>
        </div>
        <div className="audit-meta">
          <span>{audit.strategy_version ?? 'unknown strategy'} · {audit.status}</span>
          <strong>{audit.start_date ?? '—'} → {audit.end_date ?? '—'}</strong>
          {audit.updated_at && <small>Result: {new Date(audit.updated_at).toLocaleString()}</small>}
        </div>
      </header>

      <section className="primary-grid" aria-label="Primary backtest metrics">
        <article className="metric-card featured">
          <span>Observed win rate</span>
          <strong>{pct(overall.win_rate)}</strong>
          <small>{overall.wins} wins / {overall.trade_count} trades</small>
        </article>
        <article className="metric-card">
          <span>95% win-rate range</span>
          <strong className="range-value">{pct(overall.win_rate_ci95_low)}–{pct(overall.win_rate_ci95_high)}</strong>
          <small>Wilson confidence interval</small>
        </article>
        <article className="metric-card">
          <span>Break-even win rate</span>
          <strong>{pct(overall.break_even_win_rate)}</strong>
          <small>given observed avg win / loss</small>
        </article>
        <article className={`metric-card ${economicallyPositive ? 'positive-card' : ''}`}>
          <span>Win-rate edge</span>
          <strong>{pct(overall.win_rate_edge)}</strong>
          <small>observed minus break-even</small>
        </article>
        <article className="metric-card">
          <span>Payoff ratio</span>
          <strong>{num(overall.payoff_ratio)}</strong>
          <small>avg win ÷ |avg loss|</small>
        </article>
        <article className="metric-card">
          <span>Profit factor</span>
          <strong>{num(overall.profit_factor)}</strong>
          <small>gross profit ÷ gross loss</small>
        </article>
        <article className="metric-card">
          <span>Expectancy / trade</span>
          <strong>{pct(expectancy)}</strong>
          <small>win-rate weighted return</small>
        </article>
        <article className="metric-card">
          <span>Evidence level</span>
          <strong className="sample-value">{overall.sample_label}</strong>
          <small>{sampleText[overall.sample_label]}</small>
        </article>
      </section>

      <section className="secondary-grid">
        <article className="panel">
          <p className="eyebrow">Outcome quality</p>
          <h2>Trade distribution</h2>
          <div className="distribution-row">
            <div><span>Average win</span><strong>{pct(overall.average_win_return)}</strong></div>
            <div><span>Average loss</span><strong>{pct(overall.average_loss_return)}</strong></div>
            <div><span>Median return</span><strong>{pct(overall.median_return)}</strong></div>
            <div><span>Avg hold</span><strong>{overall.average_hold_sessions === null ? '—' : `${overall.average_hold_sessions.toFixed(1)}d`}</strong></div>
          </div>
          <div className="win-loss-bar" aria-label="Win loss distribution">
            <div className="win-segment" style={{ width: `${overall.trade_count ? (overall.wins / overall.trade_count) * 100 : 0}%` }} />
            <div className="flat-segment" style={{ width: `${overall.trade_count ? (overall.breakeven / overall.trade_count) * 100 : 0}%` }} />
            <div className="loss-segment" style={{ width: `${overall.trade_count ? (overall.losses / overall.trade_count) * 100 : 0}%` }} />
          </div>
          <div className="legend">
            <span><i className="legend-win" />Wins {overall.wins}</span>
            <span><i className="legend-flat" />Flat {overall.breakeven}</span>
            <span><i className="legend-loss" />Losses {overall.losses}</span>
          </div>
        </article>

        <article className="panel">
          <p className="eyebrow">Portfolio context</p>
          <h2>Backtest envelope</h2>
          <dl className="definition-grid">
            <div><dt>Total return</dt><dd>{pct(portfolio.total_return)}</dd></div>
            <div><dt>Max drawdown</dt><dd>{pct(portfolio.max_drawdown)}</dd></div>
            <div><dt>Initial capital</dt><dd>{money(portfolio.initial_capital)}</dd></div>
            <div><dt>Final equity</dt><dd>{money(portfolio.final_equity)}</dd></div>
            <div><dt>Sessions</dt><dd>{portfolio.session_count ?? '—'}</dd></div>
            <div><dt>Median hold</dt><dd>{overall.median_hold_sessions === null ? '—' : `${overall.median_hold_sessions.toFixed(0)}d`}</dd></div>
          </dl>
        </article>
      </section>

      <section className="panel conclusion-panel">
        <p className="eyebrow">Current read</p>
        <h2>{economicallyPositive ? 'Observed win rate is above the current break-even threshold.' : 'Observed win rate is not yet above the current break-even threshold.'}</h2>
        <p>
          Current sample: <strong>{overall.trade_count}</strong> trades. The measured win rate is <strong>{pct(overall.win_rate)}</strong>,
          with a 95% interval of <strong>{pct(overall.win_rate_ci95_low)}–{pct(overall.win_rate_ci95_high)}</strong>.
          The current payoff profile implies a break-even win rate of <strong>{pct(overall.break_even_win_rate)}</strong>.
        </p>
      </section>

      <section className="panel table-panel">
        <p className="eyebrow">Selection quality</p>
        <h2>Win rate by entry rank</h2>
        {audit.breakdowns.by_entry_rank.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Entry rank</th><th>Trades</th><th>Win rate</th><th>95% low</th><th>Avg return</th><th>Profit factor</th></tr></thead>
            <tbody>{audit.breakdowns.by_entry_rank.map((row) => (
              <tr key={row.key}><td>{row.key}</td><td>{row.trade_count}</td><td>{pct(row.win_rate)}</td><td>{pct(row.win_rate_ci95_low)}</td><td>{pct(row.average_return)}</td><td>{num(row.profit_factor)}</td></tr>
            ))}</tbody>
          </table></div>
        ) : <p className="empty-copy">Entry rank is not present in the existing backtest result. Re-run the backtest with the current trade ledger to populate this breakdown.</p>}
      </section>

      <section className="two-table-grid">
        <article className="panel table-panel">
          <p className="eyebrow">Timing</p>
          <h2>By holding period</h2>
          <div className="table-wrap"><table>
            <thead><tr><th>Sessions</th><th>Trades</th><th>Win rate</th><th>Median return</th></tr></thead>
            <tbody>{audit.breakdowns.by_hold_period.map((row) => (
              <tr key={row.key}><td>{row.key}</td><td>{row.trade_count}</td><td>{pct(row.win_rate)}</td><td>{pct(row.median_return)}</td></tr>
            ))}</tbody>
          </table></div>
        </article>

        <article className="panel table-panel">
          <p className="eyebrow">Exit diagnostics</p>
          <h2>By exit reason</h2>
          <div className="table-wrap"><table>
            <thead><tr><th>Exit reason</th><th>Trades</th><th>Win rate</th><th>Median return</th><th>Payoff</th></tr></thead>
            <tbody>{audit.breakdowns.by_exit_reason.map((row) => (
              <tr key={row.key}><td>{row.key}</td><td>{row.trade_count}</td><td>{pct(row.win_rate)}</td><td>{pct(row.median_return)}</td><td>{num(row.payoff_ratio)}</td></tr>
            ))}</tbody>
          </table></div>
        </article>
      </section>

      <section className="panel scope-panel">
        <p className="eyebrow">Validation scope</p>
        <h2>What this result actually proves</h2>
        <div className="scope-grid">
          {Object.entries(audit.validation_scope).map(([key, validated]) => (
            <div className={validated ? 'scope-item validated' : 'scope-item pending'} key={key}>
              <span>{validated ? 'Validated' : 'Not instrumented'}</span>
              <strong>{scopeLabels[key] ?? key}</strong>
            </div>
          ))}
        </div>
        <div className="audit-notes">{audit.notes.map((note) => <p key={note}>{note}</p>)}</div>
      </section>
    </main>
  );
};

export default Backtest;

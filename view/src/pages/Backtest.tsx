import React, { useEffect, useState } from 'react';
import './Backtest.css';

type Summary = {
  trade_count: number;
  wins: number;
  losses: number;
  breakeven: number;
  win_rate: number | null;
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
  };
  validation_scope: Record<string, boolean>;
  notes: string[];
};

const pct = (value: number | null, digits = 1) => value === null ? '—' : `${(value * 100).toFixed(digits)}%`;
const num = (value: number | null, digits = 2) => value === null ? '—' : value.toFixed(digits);
const money = (value: number | null) => value === null ? '—' : new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
}).format(value);

const scopeLabels: Record<string, string> = {
  overall_trade_win_rate: 'Overall trade win rate',
  initial_entry_trade_outcomes: 'Initial-entry outcomes',
  sector_top3_filter: 'Top-3 sector filter',
  add_1: 'Add #1',
  add_2: 'Add #2',
  option_acceleration: 'Option acceleration',
  mae_mfe: 'MAE / MFE',
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
      .then((body) => {
        if (active) setAudit(body);
      })
      .catch((reason: Error) => {
        if (active) setError(reason.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  if (loading) return <main className="backtest-page"><div className="audit-state">Loading backtest audit…</div></main>;
  if (error || !audit) return <main className="backtest-page"><div className="audit-state audit-error">{error ?? 'Audit unavailable'}</div></main>;

  const { overall, portfolio } = audit;
  const expectancy = overall.average_win_return !== null && overall.average_loss_return !== null && overall.win_rate !== null
    ? overall.win_rate * overall.average_win_return + (1 - overall.win_rate) * overall.average_loss_return
    : null;

  return (
    <main className="backtest-page">
      <header className="audit-header">
        <div>
          <p className="eyebrow">Strategy validation</p>
          <h1>Win-Rate Audit</h1>
          <p className="audit-subtitle">Canonical historical backtest from D1 metadata + R2 result storage.</p>
        </div>
        <div className="audit-meta">
          <span>{audit.strategy_version ?? 'unknown strategy'}</span>
          <strong>{audit.start_date ?? '—'} → {audit.end_date ?? '—'}</strong>
        </div>
      </header>

      <section className="primary-grid" aria-label="Primary backtest metrics">
        <article className="metric-card featured">
          <span>Win rate</span>
          <strong>{pct(overall.win_rate)}</strong>
          <small>{overall.wins} wins / {overall.trade_count} trades</small>
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
      </section>

      <section className="secondary-grid">
        <article className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Outcome quality</p>
              <h2>Trade distribution</h2>
            </div>
          </div>
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

      <section className="panel table-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Exit diagnostics</p>
            <h2>Win rate by exit reason</h2>
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Exit reason</th><th>Trades</th><th>Win rate</th><th>Median return</th><th>Payoff</th></tr></thead>
            <tbody>
              {audit.breakdowns.by_exit_reason.map((row) => (
                <tr key={row.key}>
                  <td>{row.key}</td><td>{row.trade_count}</td><td>{pct(row.win_rate)}</td><td>{pct(row.median_return)}</td><td>{num(row.payoff_ratio)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {audit.breakdowns.by_entry_rank.length > 0 && (
        <section className="panel table-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Selection quality</p>
              <h2>Win rate by entry rank</h2>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Entry rank</th><th>Trades</th><th>Win rate</th><th>Avg return</th><th>Profit factor</th></tr></thead>
              <tbody>
                {audit.breakdowns.by_entry_rank.map((row) => (
                  <tr key={row.key}>
                    <td>{row.key}</td><td>{row.trade_count}</td><td>{pct(row.win_rate)}</td><td>{pct(row.average_return)}</td><td>{num(row.profit_factor)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="panel scope-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Validation scope</p>
            <h2>What this result actually proves</h2>
          </div>
        </div>
        <div className="scope-grid">
          {Object.entries(audit.validation_scope).map(([key, validated]) => (
            <div className={validated ? 'scope-item validated' : 'scope-item pending'} key={key}>
              <span>{validated ? 'Validated' : 'Not instrumented'}</span>
              <strong>{scopeLabels[key] ?? key}</strong>
            </div>
          ))}
        </div>
        <div className="audit-notes">
          {audit.notes.map((note) => <p key={note}>{note}</p>)}
        </div>
      </section>
    </main>
  );
};

export default Backtest;

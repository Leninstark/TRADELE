import { CumulativePnlChart, DailyPnlChart } from './MyTradeCharts'

type AnyRec = Record<string, unknown>

function asRec(v: unknown): AnyRec {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as AnyRec) : {}
}

function asList(v: unknown): AnyRec[] {
  return Array.isArray(v) ? (v as AnyRec[]) : []
}

function fmt(v: unknown, suffix = ''): string {
  if (v == null || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  const n = Number(v)
  if (!Number.isNaN(n) && typeof v !== 'string') {
    return `${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}${suffix}`
  }
  return String(v)
}

function fmtInr(v: unknown): string {
  if (v == null || v === '') return '—'
  return `₹${Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

function MetricTable({ title, rows }: { title: string; rows: { label: string; value: string }[] }) {
  return (
    <div className="dna-metric-table">
      <h4>{title}</h4>
      <dl>
        {rows.map((r) => (
          <div key={r.label}>
            <dt>{r.label}</dt>
            <dd>{r.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function BarLabels({
  title,
  items,
  valueKey = 'pnl',
}: {
  title: string
  items: AnyRec[]
  valueKey?: string
}) {
  if (!items.length) return null
  const maxAbs = Math.max(...items.map((d) => Math.abs(Number(d[valueKey]) || 0)), 1)
  return (
    <div className="mt-chart-card dna-chart-card">
      <h3>{title}</h3>
      <div className="dna-hbar-list">
        {items.map((d, i) => {
          const v = Number(d[valueKey]) || 0
          const w = (Math.abs(v) / maxAbs) * 100
          const label = String(d.label || d.date || `#${i + 1}`)
          const n = d.n != null ? ` · n=${d.n}` : ''
          return (
            <div key={label} className="dna-hbar-row">
              <span className="dna-hbar-label">{label}{n}</span>
              <div className="dna-hbar-track">
                <div
                  className={`dna-hbar-fill ${v >= 0 ? 'up' : 'down'}`}
                  style={{ width: `${Math.max(w, 2)}%` }}
                />
              </div>
              <span className="dna-hbar-val">{fmtInr(v)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

type Props = {
  report: AnyRec
}

export default function TraderDnaReportView({ report }: Props) {
  const stats = asRec(report.stats)
  const narrative = asRec(report.narrative)
  const overall = asRec(stats.overall)
  const dq = asRec(stats.data_quality)
  const charts = asRec(stats.charts)
  const risk = asRec(stats.risk)
  const wl = asRec(stats.winner_loser)
  const scorecard = asRec(stats.scorecard)
  const finalV = asRec(narrative.final_verdict)
  const strengths = asList(narrative.top_strengths)
  const mistakes = asList(narrative.top_mistakes)
  const rules = asRec(narrative.personalized_rules)
  const bestStyle = asRec(narrative.best_trading_style)
  const styleTable = asRec(stats.style_table)
  const holdingTable = asRec(stats.holding_table)

  const cum = asList(charts.cumulative_pnl).map((d) => ({
    date: String(d.date || ''),
    pnl: Number(d.pnl) || 0,
  }))
  const monthly = asList(charts.monthly_pnl).map((d) => ({
    date: String(d.date || ''),
    pnl: Number(d.pnl) || 0,
  }))

  const sections = [
    { id: 'exec', label: '1. Executive Summary' },
    { id: 'quality', label: '2. Data Quality' },
    { id: 'overall', label: '3. Overall Performance' },
    { id: 'style', label: '4. Style Comparison' },
    { id: 'holding', label: '5. Holding Period' },
    { id: 'timing', label: '6–7. Entry / Exit Timing' },
    { id: 'wl', label: '8. Winner vs Loser' },
    { id: 'stocks', label: '9. Stocks' },
    { id: 'size', label: '10. Position Sizing' },
    { id: 'behavior', label: '11–13. Behavior' },
    { id: 'risk', label: '14. Risk' },
    { id: 'drift', label: '16. Style Drift' },
    { id: 'scorecard', label: '17. Scorecard' },
    { id: 'strengths', label: '18–19. Strengths / Mistakes' },
    { id: 'best', label: '20–22. Style & Rules' },
    { id: 'verdict', label: '23. Final Verdict' },
  ]

  return (
    <div className="dna-report">
      <aside className="dna-toc">
        <strong>Trader DNA</strong>
        <p className="dna-meta">
          {report.fills_through ? `Fills through ${String(report.fills_through).slice(0, 16)}` : '—'}
          {report.from_cache ? ' · cached' : ''}
          {report.llm_used ? ` · ${report.llm_provider || 'AI'}` : ' · template narrative'}
        </p>
        <nav>
          {sections.map((s) => (
            <a key={s.id} href={`#dna-${s.id}`}>
              {s.label}
            </a>
          ))}
        </nav>
      </aside>

      <div className="dna-body">
        <section id="dna-exec" className="dna-section">
          <h2>1. Executive Summary</h2>
          <p className="dna-prose">{String(narrative.executive_summary || 'Run DNA to generate summary.')}</p>
        </section>

        <section id="dna-quality" className="dna-section">
          <h2>2. Data Quality & Methodology</h2>
          <MetricTable
            title="Sample"
            rows={[
              { label: 'Fills', value: fmt(dq.fill_count) },
              { label: 'Completed trades', value: fmt(dq.completed_trades) },
              { label: 'Open positions', value: fmt(dq.open_positions) },
              { label: 'Range', value: `${fmt(asRec(dq.date_range).from)} → ${fmt(asRec(dq.date_range).to)}` },
            ]}
          />
          <p className="dna-prose">{String(dq.methodology || '')}</p>
          <ul className="dna-list">
            {asList(dq.limitations).map((x, i) => (
              <li key={i}>{String(x)}</li>
            ))}
          </ul>
        </section>

        <section id="dna-overall" className="dna-section">
          <h2>3. Overall Trading Performance</h2>
          <div className="dna-kpi-row">
            <div><span>Net P&amp;L</span><strong>{fmtInr(overall.net_pnl)}</strong></div>
            <div><span>Win rate</span><strong>{fmt(overall.win_rate, '%')}</strong></div>
            <div><span>Expectancy</span><strong>{fmtInr(overall.expectancy)}</strong></div>
            <div><span>Profit factor</span><strong>{fmt(overall.profit_factor)}</strong></div>
            <div><span>Max DD</span><strong>{fmtInr(overall.max_drawdown)}</strong></div>
            <div><span>Trades</span><strong>{fmt(overall.trades)}</strong></div>
          </div>
          <div className="dna-charts-grid">
            <CumulativePnlChart title="Cumulative P&L (₹)" data={cum} />
            <DailyPnlChart title="Monthly P&L (₹)" data={monthly} />
          </div>
        </section>

        <section id="dna-style" className="dna-section">
          <h2>4. Intraday vs Swing vs Positional</h2>
          <p className="dna-note">
            Strongest by stats: <strong>{fmt(stats.strongest_style_by_stats)}</strong>.{' '}
            {String(stats.style_sample_warning || '')}
          </p>
          <div className="mt-table-wrap">
            <table className="mt-table dna-table">
              <thead>
                <tr>
                  <th>Style</th>
                  <th>N</th>
                  <th>Win%</th>
                  <th>Net</th>
                  <th>PF</th>
                  <th>Expectancy</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(styleTable).map(([k, v]) => {
                  const m = asRec(v)
                  return (
                    <tr key={k}>
                      <td>{k}</td>
                      <td>{fmt(m.trades)}</td>
                      <td>{fmt(m.win_rate)}</td>
                      <td>{fmtInr(m.net_pnl)}</td>
                      <td>{fmt(m.profit_factor)}</td>
                      <td>{fmtInr(m.expectancy)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <BarLabels title="P&L by style" items={asList(charts.style_pnl)} />
        </section>

        <section id="dna-holding" className="dna-section">
          <h2>5. Optimal Holding Period</h2>
          <p className="dna-note">
            Best bucket (n≥8, expectancy-adjusted): <strong>{fmt(stats.optimal_holding_bucket)}</strong>
          </p>
          <div className="mt-table-wrap">
            <table className="mt-table dna-table">
              <thead>
                <tr>
                  <th>Bucket</th>
                  <th>N</th>
                  <th>Win%</th>
                  <th>Net</th>
                  <th>Expectancy</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(holdingTable).map(([k, v]) => {
                  const m = asRec(v)
                  return (
                    <tr key={k}>
                      <td>{k}</td>
                      <td>{fmt(m.trades)}</td>
                      <td>{fmt(m.win_rate)}</td>
                      <td>{fmtInr(m.net_pnl)}</td>
                      <td>{fmtInr(m.expectancy)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section id="dna-timing" className="dna-section">
          <h2>6–7. Entry / Exit Timing</h2>
          <p className="dna-note">{String(asRec(stats.opening_bias).note || '')}</p>
          <div className="dna-charts-grid">
            <BarLabels title="Entry time vs P&L" items={asList(charts.entry_timing)} />
            <BarLabels title="Exit time vs P&L" items={asList(charts.exit_timing)} />
          </div>
        </section>

        <section id="dna-wl" className="dna-section">
          <h2>8. Winner vs Loser Behavior</h2>
          <p className="dna-prose">{String(wl.interpretation || '')}</p>
          <MetricTable
            title="Hold asymmetry"
            rows={[
              { label: 'Median hold winners (h)', value: fmt(asRec(wl.winners).median_hold_hours) },
              { label: 'Median hold losers (h)', value: fmt(asRec(wl.losers).median_hold_hours) },
              { label: 'Ratio W/L', value: fmt(wl.hold_ratio_winners_over_losers) },
            ]}
          />
        </section>

        <section id="dna-stocks" className="dna-section">
          <h2>9. Stock-wise Performance</h2>
          <div className="dna-charts-grid">
            <BarLabels title="Top stocks by P&L" items={asList(charts.top_stocks)} />
          </div>
          <h4>Repeated poor names</h4>
          <ul className="dna-list">
            {asList(asRec(stats.stocks).repeated_poor).slice(0, 8).map((r) => (
              <li key={String(r.symbol)}>
                {String(r.symbol)} — {fmtInr(r.net_pnl)} · win {fmt(r.win_rate)}% · n={fmt(r.trades)}
              </li>
            ))}
            {!asList(asRec(stats.stocks).repeated_poor).length && <li>None flagged</li>}
          </ul>
        </section>

        <section id="dna-size" className="dna-section">
          <h2>10. Position Sizing</h2>
          <BarLabels
            title="Expectancy by size quintile (shown as ₹ expectancy)"
            items={asList(charts.position_sizing).map((d) => ({
              ...d,
              pnl: d.expectancy,
            }))}
          />
        </section>

        <section id="dna-behavior" className="dna-section">
          <h2>11–13. Sequence, Overtrading, FOMO</h2>
          <p className="dna-prose">{String(asRec(stats.sequence).caution || '')}</p>
          <p className="dna-prose">{String(asRec(stats.overtrading).note || '')}</p>
          <p className="dna-note">{String(asRec(stats.fomo).message || '')}</p>
          <p className="dna-note">{String(asRec(stats.market_condition).message || '')}</p>
        </section>

        <section id="dna-risk" className="dna-section">
          <h2>14. Risk Management</h2>
          <MetricTable
            title="Risk"
            rows={[
              { label: 'Rating', value: fmt(risk.rating) },
              { label: 'Max drawdown', value: fmtInr(risk.max_drawdown) },
              { label: 'Largest loss', value: fmtInr(risk.largest_loss) },
              { label: 'Max consec losses', value: fmt(risk.max_consec_losses) },
              { label: 'Recovery factor', value: fmt(risk.recovery_factor) },
            ]}
          />
        </section>

        <section id="dna-drift" className="dna-section">
          <h2>16. Style Drift</h2>
          <p className="dna-prose">{String(asRec(stats.style_drift).note || '')}</p>
          <p className="dna-note">{String(asRec(stats.style_drift).intention_disclaimer || '')}</p>
        </section>

        <section id="dna-scorecard" className="dna-section">
          <h2>17. Trader DNA Scorecard</h2>
          <p className="dna-note">{String(narrative.scorecard_notes || '')}</p>
          <div className="dna-scorecard">
            {Object.entries(scorecard).map(([k, v]) => (
              <div key={k}>
                <span>{k.replace(/_/g, ' ')}</span>
                <strong>{fmt(v)}{typeof v === 'number' ? '/10' : ''}</strong>
              </div>
            ))}
          </div>
        </section>

        <section id="dna-strengths" className="dna-section">
          <h2>18–19. Strengths & Mistakes</h2>
          <div className="dna-two-col">
            <div>
              <h4>Top 5 strengths</h4>
              <ol>
                {strengths.map((s, i) => (
                  <li key={i}>
                    <strong>{String(s.title || s.behavior || '')}</strong>
                    <p>{String(s.evidence || '')}</p>
                  </li>
                ))}
              </ol>
            </div>
            <div>
              <h4>Top 5 mistakes</h4>
              <ol>
                {mistakes.map((s, i) => (
                  <li key={i}>
                    <strong>{String(s.behavior || s.title || '')}</strong>
                    <p>{String(s.evidence || s.fix || s.cost_hint || '')}</p>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        </section>

        <section id="dna-best" className="dna-section">
          <h2>20–22. Best Style, What-If, Rules</h2>
          <p className="dna-prose">
            <strong>{fmt(bestStyle.recommendation)}</strong> — {String(bestStyle.rationale || '')}
          </p>
          <p className="dna-note">{String(narrative.what_if_commentary || asRec(stats.what_if).assumption || '')}</p>
          <MetricTable
            title="Personalized rules"
            rows={Object.entries(rules).map(([k, v]) => ({
              label: k.replace(/_/g, ' '),
              value: fmt(v),
            }))}
          />
        </section>

        <section id="dna-verdict" className="dna-section dna-verdict">
          <h2>23. Final Verdict</h2>
          <dl className="dna-verdict-dl">
            {[
              ['Who am I', finalV.who_am_i],
              ['Good at', finalV.good_at],
              ['Bad at', finalV.bad_at],
              ['Money comes from', finalV.money_comes_from],
              ['Costliest behavior', finalV.costliest_behavior],
              ['Best holding', finalV.best_holding],
              ['Intraday or swing', finalV.intraday_or_swing],
              ['Biggest psych risk', finalV.biggest_psychological_risk],
              ['Biggest edge', finalV.biggest_edge],
              ['Stop doing', finalV.stop_doing],
              ['Do more', finalV.do_more],
            ].map(([k, v]) => (
              <div key={String(k)}>
                <dt>{k}</dt>
                <dd>{fmt(v)}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </div>
  )
}

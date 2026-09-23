import type { SwingStock } from '../api/client'

function fmt(v: unknown, suffix = ''): string {
  if (v === null || v === undefined || v === '') return '—'
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

function asList(v: unknown): string[] {
  return Array.isArray(v) ? v.map(String).filter(Boolean) : []
}

interface Props {
  stock: SwingStock
  onClose: () => void
}

export default function DashboardStockModal({ stock, onClose }: Props) {
  const x = stock.extra || {}
  const conf = Number(x.confidence ?? 0)
  const llm = Boolean(x.llm_used)
  const llmProvider = String(x.llm_provider || '').toLowerCase()
  const llmBadge =
    llmProvider === 'claude_cli'
      ? 'Claude AI thesis'
      : llmProvider === 'gemini'
        ? 'Gemini AI thesis'
        : llmProvider === 'openai'
          ? 'OpenAI thesis'
          : llm
            ? 'AI thesis'
            : 'Math / rule-based fallback'
  const components = (x.score_components || {}) as Record<string, number>
  const weights = (x.score_weights || {}) as Record<string, number>
  const conviction = asList(x.conviction_points)
  const catalysts = asList(x.catalysts)
  const risks = asList(x.risks)
  const expected = x.expected_move_pct

  return (
    <div className="gw-modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="swing-detail-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-labelledby="swing-detail-title"
      >
        <div className="swing-detail-head">
          <div>
            <h2 id="swing-detail-title">
              {String(x.company || stock.symbol)}
            </h2>
            <div className="swing-detail-meta">
              <span className="swing-detail-sym">{stock.symbol}</span>
              {x.sector ? <span className="xp-tag">{String(x.sector)}</span> : null}
              <span className="swing-detail-price">{fmtInr(x.ltp ?? stock.price)}</span>
              <span className={Number(x.change_pct) >= 0 ? 'xp-chg is-bull' : 'xp-chg is-bear'}>
                {Number(x.change_pct) >= 0 ? '+' : ''}
                {fmt(x.change_pct, '%')}
              </span>
            </div>
          </div>
          <div className="swing-detail-badges">
            <div className={`swing-conf-pill${conf >= 70 ? ' is-high' : ''}`}>
              <strong>{fmt(conf, '%')}</strong>
              <span>Confidence</span>
            </div>
            <button type="button" className="btn secondary" onClick={onClose}>
              Close
            </button>
          </div>
        </div>

        <div className="swing-detail-banner">
          <div>
            <span className="swing-detail-banner-label">Thesis</span>
            <strong>
              Potential +{fmt(expected ?? 20)}% move in next {fmt(x.horizon_days ?? 14)} days
            </strong>
            {x.conviction_met ? (
              <span className="swing-engine-pill is-ai" style={{ marginLeft: 8 }}>
                ≥ +20% conviction
              </span>
            ) : null}
          </div>
          <span className={`swing-engine-pill${llm ? ' is-ai' : ''}`}>
            {llmBadge}
          </span>
        </div>

        <section className="swing-detail-section">
          <h3>Why this is an early +20% / 2-week candidate</h3>
          <p className="swing-detail-justification">
            {String(x.justification || x.ai_remarks || 'No justification available. Re-run Dashboard scan with Gemini configured.')}
          </p>
          {conviction.length > 0 && (
            <ul className="swing-detail-bullets">
              {conviction.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
        </section>

        <div className="swing-detail-grid">
          <section className="swing-detail-section">
            <h3>Trade plan</h3>
            <div className="swing-detail-plan">
              <div><span>Entry</span><strong>{fmtInr(x.entry_price)}</strong></div>
              <div><span>Stop</span><strong>{fmtInr(x.stop_loss)}</strong></div>
              <div><span>Target 1</span><strong>{fmtInr(x.target_1)}</strong></div>
              <div><span>Target 2</span><strong>{fmtInr(x.target_2)}</strong></div>
              <div><span>R:R</span><strong>{x.risk_reward != null ? `${x.risk_reward}:1` : '—'}</strong></div>
              <div><span>Swing score</span><strong>{fmt(x.swing_score ?? x.score)}</strong></div>
            </div>
          </section>

          <section className="swing-detail-section">
            <h3>Catalysts & risks</h3>
            {catalysts.length > 0 ? (
              <>
                <h4 className="is-bull">Catalysts</h4>
                <ul className="swing-detail-bullets">
                  {catalysts.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="swing-detail-muted">No catalyst list returned.</p>
            )}
            {risks.length > 0 && (
              <>
                <h4 className="is-bear">Risks</h4>
                <ul className="swing-detail-bullets">
                  {risks.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </>
            )}
          </section>
        </div>

        <section className="swing-detail-section">
          <h3>Key metrics</h3>
          <div className="swing-detail-metrics">
            {(
              [
                ['5D %', x.return_5d_pct, '%'],
                ['10D %', x.return_10d_pct, '%'],
                ['20D %', x.return_20d_pct, '%'],
                ['Vol ratio', x.volume_ratio, 'x'],
                ['Delivery %', x.delivery_pct ?? stock.delivery_pct, '%'],
                ['Avg volume', stock.avg_daily_volume, ''],
                ['RSI', x.rsi, ''],
                ['ADX', x.adx, ''],
                ['ATR', x.atr, ''],
                ['EMA20', x.ema_20, ''],
                ['EMA50', x.ema_50, ''],
                ['EMA200', x.ema_200, ''],
                ['Rel strength', x.relative_strength_pct, '%'],
                ['Sector rank', x.sector_rank, ''],
                ['Breakout', x.breakout, ''],
                ['From 52W high', x.dist_52w_high_pct, '%'],
                ['News', x.news_sentiment, ''],
                ['News score', x.news_score, ''],
              ] as Array<[string, unknown, string]>
            ).map(([label, val, suffix]) => (
              <div key={label} className="swing-detail-metric">
                <span>{label}</span>
                <strong>
                  {typeof val === 'boolean'
                    ? val
                      ? 'Yes'
                      : 'No'
                    : label === 'EMA20' || label === 'EMA50' || label === 'EMA200' || label === 'ATR'
                      ? fmtInr(val)
                      : fmt(val, suffix)}
                </strong>
              </div>
            ))}
          </div>
        </section>

        {Object.keys(components).length > 0 && (
          <section className="swing-detail-section">
            <h3>Score breakdown (metrics + news weightage)</h3>
            <div className="swing-detail-components">
              {Object.entries(components).map(([k, v]) => (
                <div key={k} className="swing-detail-component">
                  <div className="swing-detail-component-top">
                    <span>{k.replace(/_/g, ' ')}</span>
                    <strong>
                      {fmt(v)}
                      {weights[k] != null ? ` · wt ${weights[k]}` : ''}
                    </strong>
                  </div>
                  <div className="swing-detail-bar">
                    <span style={{ width: `${Math.min(100, Math.max(0, Number(v) || 0))}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  )
}

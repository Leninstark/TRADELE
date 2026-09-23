import type { MarketBriefReport } from '../api/client'

function stanceClass(stance?: string) {
  const s = (stance || '').toLowerCase()
  if (s === 'crisis') return 'is-crisis'
  if (s === 'risk_off') return 'is-risk-off'
  if (s === 'risk_on') return 'is-risk-on'
  return 'is-neutral'
}

function biasClass(bias?: string) {
  const b = (bias || '').toLowerCase()
  if (b === 'up' || b === 'good') return 'bias-good'
  if (b === 'down' || b === 'bad') return 'bias-bad'
  if (b === 'watch') return 'bias-watch'
  return 'bias-flat'
}

function formatWhen(iso?: string | null) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('en-IN', {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

type Props = {
  brief: MarketBriefReport | null
  loading: boolean
  onRefresh: () => void
  /** When false, page owns the Build button — avoid duplicate chrome */
  showActions?: boolean
}

export default function MarketBriefPanel({ brief, loading, onRefresh, showActions = true }: Props) {
  if (!brief?.ok && !loading) {
    return (
      <section className="mb-brief mb-empty">
        {showActions ? (
          <div className="mb-brief-head">
            <div>
              <h2>News Brief</h2>
              <p>Overnight / pre-open risk regime for Nifty, Bank Nifty & sectors</p>
            </div>
            <button type="button" className="btn primary" onClick={onRefresh} disabled={loading}>
              Build brief now
            </button>
          </div>
        ) : null}
        <p className="mb-empty-copy">
          {brief?.message ||
            'No brief yet. Click Build brief now, or wait for the night (~11:00 PM) / morning (~8:15 AM IST) job.'}
        </p>
      </section>
    )
  }

  const action = brief?.action_card || {}
  const series = brief?.crosscheck?.series || {}
  const sectors = brief?.sectors || []

  return (
    <section className={`mb-brief ${stanceClass(brief?.stance)}`}>
      <div className="mb-brief-head">
        <div>
          <h2>Latest verdict</h2>
          <p>
            {(brief?.brief_type || 'manual').toUpperCase()} · {formatWhen(brief?.as_of)} ·{' '}
            {brief?.llm_used ? brief.llm_provider || 'AI' : 'rules + template'}
            {brief?.alerted ? ' · alert sent' : ''}
          </p>
        </div>
        <div className="mb-brief-actions">
          <span className={`mb-stance-pill ${stanceClass(brief?.stance)}`}>
            {(brief?.stance || 'neutral').replace('_', ' ').toUpperCase()}
          </span>
          <span className="mb-conf">{brief?.confidence ?? '—'} conf</span>
          {showActions && (
            <button type="button" className="btn secondary" onClick={onRefresh} disabled={loading}>
              {loading ? 'Building…' : 'Rebuild'}
            </button>
          )}
        </div>
      </div>

      {loading && !brief?.market_summary && (
        <p className="mb-loading">Harvesting global + India headlines and synthesizing verdict…</p>
      )}

      {brief?.market_summary && <p className="mb-summary">{brief.market_summary}</p>}

      <div className="mb-indices">
        {(brief?.indices || []).map((ix) => (
          <div key={ix.index} className={`mb-index ${biasClass(ix.bias)}`}>
            <strong>{ix.index}</strong>
            <span>{(ix.bias || 'flat').toUpperCase()}</span>
            {typeof ix.confidence === 'number' && <em>{ix.confidence}</em>}
            {ix.note && <p>{ix.note}</p>}
          </div>
        ))}
      </div>

      <div className="mb-grid">
        <div>
          <h3>Sectors</h3>
          <div className="mb-sector-grid">
            {sectors.map((s) => (
              <div key={s.sector} className={`mb-sector ${biasClass(s.bias)}`} title={s.reason || s.note || ''}>
                <span>{s.sector}</span>
                <strong>{(s.bias || 'neutral').toUpperCase()}</strong>
              </div>
            ))}
            {!sectors.length && <p className="mb-muted">No sector map yet</p>}
          </div>
        </div>

        <div>
          <h3>Action card</h3>
          <div className="mb-action">
            <p>{action.guidance || '—'}</p>
            <dl>
              <div>
                <dt>Max risk</dt>
                <dd>{action.max_risk_today || '—'}</dd>
              </div>
              <div>
                <dt>Avoid</dt>
                <dd>{(action.avoid_sectors || []).join(', ') || '—'}</dd>
              </div>
              <div>
                <dt>Watch</dt>
                <dd>{(action.watch_sectors || []).join(', ') || '—'}</dd>
              </div>
              <div>
                <dt>Wait first hour</dt>
                <dd>{action.wait_first_hour ? 'Yes' : 'No'}</dd>
              </div>
            </dl>
          </div>

          <h3>Catalysts</h3>
          <ul className="mb-cats">
            {(brief?.catalysts || []).slice(0, 6).map((c, i) => (
              <li key={i}>
                <strong>{c.title || '—'}</strong>
                {c.why && <span>{c.why}</span>}
              </li>
            ))}
            {!(brief?.catalysts || []).length && <li className="mb-muted">None flagged</li>}
          </ul>
        </div>
      </div>

      {Object.keys(series).length > 0 && (
        <div className="mb-cross">
          <h3>Price cross-check</h3>
          <div className="mb-cross-row">
            {Object.entries(series).map(([k, v]) => (
              <div key={k} className={(v.chg_pct || 0) >= 0 ? 'up' : 'down'}>
                <span>{k}</span>
                <strong>
                  {typeof v.chg_pct === 'number' ? `${v.chg_pct > 0 ? '+' : ''}${v.chg_pct.toFixed(2)}%` : '—'}
                </strong>
              </div>
            ))}
          </div>
          {(brief?.crosscheck?.notes || []).map((n, i) => (
            <p key={i} className="mb-muted">
              {n}
            </p>
          ))}
        </div>
      )}

      {(brief?.invalidate_if || []).length > 0 && (
        <p className="mb-invalidate">
          <strong>Invalidate if:</strong> {(brief?.invalidate_if || []).join(' · ')}
        </p>
      )}

      {brief?.disclaimer && <p className="mb-disclaimer">{brief.disclaimer}</p>}
    </section>
  )
}

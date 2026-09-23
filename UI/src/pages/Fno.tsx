import { useEffect, useMemo, useState } from 'react'
import {
  explainFnoMetric,
  fetchFnoIndex,
  type FnoDayRow,
  type FnoIndexAnalytics,
  type FnoIndexId,
  type FnoInterestingNote,
  type FnoKpi,
  type FnoPattern,
} from '../api/client'

const TABS: { id: FnoIndexId; label: string }[] = [
  { id: 'NIFTY', label: 'NIFTY' },
  { id: 'BANKNIFTY', label: 'Bank Nifty' },
  { id: 'SENSEX', label: 'SENSEX' },
]

const EXTREME_LABELS: Record<string, string> = {
  highest_close: 'Highest close',
  lowest_close: 'Lowest close',
  biggest_up_day: 'Biggest up day',
  biggest_down_day: 'Biggest down day',
  highest_volume: 'Highest volume',
  lowest_volume: 'Lowest volume',
  widest_range: 'Widest range',
  tightest_range: 'Tightest range',
  largest_gap_up: 'Largest gap up',
  largest_gap_down: 'Largest gap down',
}

const PATTERN_FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'gap_up', label: 'Gap up' },
  { id: 'gap_down', label: 'Gap down' },
  { id: 'sudden_fall', label: 'Sudden fall' },
  { id: 'sudden_rally', label: 'Sudden rally' },
  { id: 'volume_spike', label: 'Vol spike' },
  { id: 'gap_fade', label: 'Gap fade' },
  { id: 'gap_recovery', label: 'Gap recovery' },
  { id: 'wide_range', label: 'Wide range' },
]

type ExplainState = {
  title: string
  topic: string
  loading: boolean
  text: string
  source: string
  provider: string | null
  error: string | null
}

function fmtPts(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function fmtVol(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return Math.round(n).toLocaleString('en-IN')
}

function renderMarkdownLite(text: string) {
  return text.split('\n').map((line, i) => {
    const html = line
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/^###\s+(.+)$/, '<span class="fno-md-h">$1</span>')
      .replace(/^##\s+(.+)$/, '<span class="fno-md-h">$1</span>')
      .replace(/^#\s+(.+)$/, '<span class="fno-md-h">$1</span>')
    if (!line.trim()) return <br key={i} />
    return <p key={i} dangerouslySetInnerHTML={{ __html: html }} />
  })
}

export default function Fno() {
  const [tab, setTab] = useState<FnoIndexId>('NIFTY')
  const [data, setData] = useState<FnoIndexAnalytics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [patternFilter, setPatternFilter] = useState('all')
  const [explain, setExplain] = useState<ExplainState | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    setData(null)
    fetchFnoIndex(tab)
      .then((d) => {
        if (!cancelled) setData(d)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err?.response?.data?.detail || err?.message || 'Failed to load index analytics')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [tab])

  const filteredPatterns = useMemo(() => {
    if (!data) return []
    if (patternFilter === 'all') return data.patterns
    return data.patterns.filter((p) => p.type === patternFilter)
  }, [data, patternFilter])

  async function openExplain(title: string, topic: string, payload: Record<string, unknown>) {
    setExplain({
      title,
      topic,
      loading: true,
      text: '',
      source: '',
      provider: null,
      error: null,
    })
    try {
      const res = await explainFnoMetric({ index: tab, topic, title, payload })
      setExplain({
        title: res.title || title,
        topic,
        loading: false,
        text: res.explanation || '',
        source: res.source,
        provider: res.provider,
        error: res.error,
      })
    } catch (err: any) {
      setExplain({
        title,
        topic,
        loading: false,
        text: '',
        source: 'error',
        provider: null,
        error: err?.response?.data?.detail || err?.message || 'Explain failed',
      })
    }
  }

  function onKpi(k: FnoKpi) {
    void openExplain(k.label, `kpi:${k.key}`, { ...k })
  }

  function onExtreme(key: string, row: FnoDayRow | null) {
    if (!row) return
    void openExplain(EXTREME_LABELS[key] || key, `extreme:${key}`, {
      label: EXTREME_LABELS[key] || key,
      ...row,
      summary: `${EXTREME_LABELS[key] || key} on ${row.date}: close ${row.close}, change ${fmtPts(row.change)} (${fmtPct(row.change_pct)}), range ${fmtPts(row.range_pts)} pts, vol ${fmtVol(row.volume)}.`,
    })
  }

  function onPattern(p: FnoPattern) {
    void openExplain(p.title, `pattern:${p.id}`, {
      type: p.type,
      severity: p.severity,
      title: p.title,
      summary: p.summary,
      day: p.day,
      metrics: p.metrics,
    })
  }

  function onNote(n: FnoInterestingNote) {
    void openExplain(n.title, `note:${n.key}`, {
      title: n.title,
      text: n.text,
      summary: n.text,
      context: n.context,
    })
  }

  const periodClass =
    data?.period_change_pct == null
      ? ''
      : data.period_change_pct >= 0
        ? 'up'
        : 'down'

  return (
    <div className="explore-page fno-page">
      <header className="page-header">
        <h1>F&amp;O</h1>
        <p>Index study desk — dissect NIFTY, Bank Nifty &amp; SENSEX daily behavior</p>
      </header>

      <div className="fno-tabs" role="tablist" aria-label="Index">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={`fno-tab${tab === t.id ? ' active' : ''}`}
            onClick={() => {
              setTab(t.id)
              setPatternFilter('all')
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading && (
        <div className="gw-empty" style={{ padding: '40px 24px' }}>
          <p style={{ margin: 0 }}>Loading {TABS.find((t) => t.id === tab)?.label} analytics…</p>
        </div>
      )}

      {!loading && error && (
        <div className="gw-empty gw-rate-limit" style={{ padding: '40px 24px' }}>
          <p style={{ margin: 0 }}>{error}</p>
        </div>
      )}

      {!loading && data && (
        <div className="fno-body">
          <section className="fno-hero">
            <div>
              <h2>{data.label}</h2>
              <p className="fno-meta">
                {data.from_date} → {data.to_date} · {data.sessions} sessions · {data.lot_hint}
              </p>
            </div>
            <div className="fno-hero-stats">
              <div>
                <span className="fno-stat-label">Last close</span>
                <span className="fno-stat-value">
                  {data.last.close?.toLocaleString('en-IN', { maximumFractionDigits: 2 }) ?? '—'}
                </span>
              </div>
              <div>
                <span className="fno-stat-label">Last day</span>
                <span className={`fno-stat-value ${data.last.change_pct != null && data.last.change_pct >= 0 ? 'up' : 'down'}`}>
                  {fmtPts(data.last.change)} ({fmtPct(data.last.change_pct)})
                </span>
              </div>
              <div>
                <span className="fno-stat-label">1y change</span>
                <span className={`fno-stat-value ${periodClass}`}>{fmtPct(data.period_change_pct)}</span>
              </div>
              <div>
                <span className="fno-stat-label">Streak</span>
                <span className="fno-stat-value">
                  {data.streaks.current
                    ? `${data.streaks.current.length} ${data.streaks.current.direction}`
                    : '—'}
                </span>
              </div>
            </div>
          </section>

          <section className="fno-section">
            <div className="fno-section-head">
              <h3>Key metrics</h3>
              <span className="fno-hint">Click any card for AI / rule-based justification</span>
            </div>
            <div className="fno-kpi-grid">
              {data.kpis.map((k) => (
                <button key={k.key} type="button" className="fno-kpi" onClick={() => onKpi(k)}>
                  <span className="fno-kpi-label">{k.label}</span>
                  <span className="fno-kpi-value">{k.display}</span>
                  <span className="fno-kpi-ask">What does this mean?</span>
                </button>
              ))}
            </div>
          </section>

          <section className="fno-section">
            <div className="fno-section-head">
              <h3>Extremes</h3>
              <span className="fno-hint">Highest / lowest days in the sample</span>
            </div>
            <div className="fno-extreme-grid">
              {Object.entries(EXTREME_LABELS).map(([key, label]) => {
                const row = data.extremes[key]
                if (!row) return null
                return (
                  <button
                    key={key}
                    type="button"
                    className="fno-extreme"
                    onClick={() => onExtreme(key, row)}
                  >
                    <span className="fno-extreme-label">{label}</span>
                    <span className="fno-extreme-date">{row.date}</span>
                    <span className="fno-extreme-main">
                      {key.includes('volume')
                        ? fmtVol(row.volume)
                        : key.includes('gap')
                          ? fmtPct(row.gap_pct ?? row.metric)
                          : key.includes('range')
                            ? `${fmtPts(row.range_pts)} pts`
                            : key.includes('up') || key.includes('down')
                              ? `${fmtPts(row.change)} (${fmtPct(row.change_pct)})`
                              : row.close?.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                    </span>
                    <span className="fno-kpi-ask">Ask AI</span>
                  </button>
                )
              })}
            </div>
          </section>

          <section className="fno-section">
            <div className="fno-section-head">
              <h3>Interesting patterns</h3>
              <span className="fno-hint">Structural takes from the full sample</span>
            </div>
            <div className="fno-notes">
              {data.interesting.map((n) => (
                <button key={n.key} type="button" className="fno-note" onClick={() => onNote(n)}>
                  <strong>{n.title}</strong>
                  <span>{n.text}</span>
                  <em>Open AI take →</em>
                </button>
              ))}
            </div>
          </section>

          <section className="fno-section">
            <div className="fno-section-head">
              <h3>Weekday profile</h3>
              <span className="fno-hint">Avg behavior by session day</span>
            </div>
            <div className="fno-weekday-table-wrap">
              <table className="fno-weekday-table">
                <thead>
                  <tr>
                    <th>Day</th>
                    <th>Sessions</th>
                    <th>Avg % chg</th>
                    <th>Avg range</th>
                    <th>Green %</th>
                    <th>Avg vol</th>
                  </tr>
                </thead>
                <tbody>
                  {data.weekday.map((w) => (
                    <tr
                      key={w.weekday}
                      className="fno-weekday-row"
                      onClick={() =>
                        void openExplain(`${w.weekday} profile`, `weekday:${w.weekday}`, {
                          ...w,
                          summary: `${w.weekday}: avg ${fmtPct(w.avg_change_pct)}, range ${fmtPts(w.avg_range_pts)} pts, green ${w.green_pct?.toFixed(1)}%, n=${w.sessions}.`,
                        })
                      }
                    >
                      <td>{w.weekday}</td>
                      <td>{w.sessions}</td>
                      <td className={(w.avg_change_pct ?? 0) >= 0 ? 'up' : 'down'}>
                        {fmtPct(w.avg_change_pct)}
                      </td>
                      <td>{fmtPts(w.avg_range_pts)}</td>
                      <td>{w.green_pct != null ? `${w.green_pct.toFixed(1)}%` : '—'}</td>
                      <td>{fmtVol(w.avg_volume)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="fno-section">
            <div className="fno-section-head">
              <h3>Event patterns</h3>
              <span className="fno-hint">
                Gaps, sudden falls/rallies, volume spikes — click for justification
              </span>
            </div>
            <div className="fno-pattern-filters">
              {PATTERN_FILTERS.map((f) => {
                const count =
                  f.id === 'all'
                    ? data.patterns.length
                    : data.pattern_counts[f.id] || 0
                return (
                  <button
                    key={f.id}
                    type="button"
                    className={`fno-chip${patternFilter === f.id ? ' active' : ''}`}
                    onClick={() => setPatternFilter(f.id)}
                  >
                    {f.label}
                    <span>{count}</span>
                  </button>
                )
              })}
            </div>
            <div className="fno-pattern-list">
              {filteredPatterns.length === 0 && (
                <p className="fno-empty-inline">No patterns in this filter.</p>
              )}
              {filteredPatterns.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className={`fno-pattern sev-${p.severity} type-${p.type}`}
                  onClick={() => onPattern(p)}
                >
                  <div className="fno-pattern-top">
                    <span className="fno-pattern-type">{p.type.replace(/_/g, ' ')}</span>
                    <span className="fno-pattern-sev">{p.severity}</span>
                  </div>
                  <strong>{p.title}</strong>
                  <span className="fno-pattern-sum">{p.summary}</span>
                  {p.day && (
                    <span className="fno-pattern-day">
                      {p.day.weekday} · O {p.day.open} H {p.day.high} L {p.day.low} C {p.day.close}
                    </span>
                  )}
                </button>
              ))}
            </div>
          </section>
        </div>
      )}

      {explain && (
        <div className="gw-modal-backdrop" onClick={() => setExplain(null)} role="presentation">
          <div
            className="gw-modal gw-modal-lg fno-explain-modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label={explain.title}
          >
            <div className="gw-modal-title-row">
              <div>
                <h2>{explain.title}</h2>
                <p className="gw-modal-hint" style={{ marginBottom: 0 }}>
                  {explain.loading
                    ? 'Thinking…'
                    : explain.source === 'llm'
                      ? `AI take${explain.provider ? ` · ${explain.provider}` : ''}`
                      : explain.source === 'rules'
                        ? 'Rule-based take (configure LLM for deeper analysis)'
                        : 'Explain'}
                </p>
              </div>
              <button type="button" className="gw-icon-btn" onClick={() => setExplain(null)} aria-label="Close">
                ×
              </button>
            </div>
            <div className="fno-explain-body">
              {explain.loading && <p className="fno-explain-loading">Analyzing this metric against the 1y sample…</p>}
              {!explain.loading && explain.error && !explain.text && (
                <p className="login-error">{explain.error}</p>
              )}
              {!explain.loading && explain.text && (
                <div className="fno-explain-text">{renderMarkdownLite(explain.text)}</div>
              )}
              {!explain.loading && explain.error && explain.text && (
                <p className="fno-explain-note">{explain.error}</p>
              )}
            </div>
            <div className="gw-modal-actions">
              <button type="button" className="btn secondary" onClick={() => setExplain(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

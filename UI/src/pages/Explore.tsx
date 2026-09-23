import { useCallback, useEffect, useRef, useState } from 'react'
import {
  analyzeStock,
  fetchExploreRecent,
  fetchExploreSymbols,
  type ExploreRecentItem,
  type HorizonOutlook,
  type StockAnalysis,
  type SymbolSuggestion,
} from '../api/client'
import { exportStockReportPdf } from '../utils/exportPdf'

function biasClass(bias?: string): string {
  const b = (bias || '').toLowerCase()
  if (b.includes('bull') || b.includes('positive') || b.includes('strong') || b.includes('up')) return 'is-bull'
  if (b.includes('bear') || b.includes('negative') || b.includes('weak') || b.includes('down')) return 'is-bear'
  return 'is-neutral'
}

function verdictClass(v?: string): string {
  const b = (v || '').toLowerCase()
  if (b.includes('buy') || b.includes('accumulate')) return 'is-bull'
  if (b.includes('avoid') || b.includes('reduce') || b.includes('sell')) return 'is-bear'
  return 'is-neutral'
}

function fmtNum(v: unknown): string {
  if (v === null || v === undefined || v === '') return '–'
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return n.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

const METRIC_LABELS: Record<string, string> = {
  close: 'Last Price (₹)',
  change_pct: 'Change %',
  return_1w_pct: '1W Return %',
  return_1m_pct: '1M Return %',
  return_3m_pct: '3M Return %',
  return_6m_pct: '6M Return %',
  return_1y_pct: '1Y Return %',
  rsi: 'RSI (14)',
  adx: 'ADX',
  atr: 'ATR',
  ema_20: 'EMA 20',
  ema_50: 'EMA 50',
  ema_200: 'EMA 200',
  high_52w: '52W High',
  low_52w: '52W Low',
  dist_52w_high_pct: 'Below 52W High %',
  volume_ratio: 'Volume Ratio',
  avg_daily_volume: 'Avg Daily Volume',
  ema_aligned_bull: 'EMA Bull Aligned',
  near_20d_breakout: 'Near 20D Breakout',
}

const METRIC_ORDER = Object.keys(METRIC_LABELS)

function HorizonCard({ title, data }: { title: string; data?: HorizonOutlook }) {
  if (!data) return null
  return (
    <div className={`xp-horizon ${biasClass(data.bias)}`}>
      <div className="xp-horizon-head">
        <span className="xp-horizon-title">{title}</span>
        <span className="xp-horizon-bias">{data.bias || '–'}</span>
      </div>
      {data.expected_range && <div className="xp-horizon-range">{data.expected_range}</div>}
      {typeof data.confidence === 'number' && (
        <div className="xp-conf">
          <div className="xp-conf-bar">
            <span style={{ width: `${Math.min(100, Math.max(0, data.confidence))}%` }} />
          </div>
          <span className="xp-conf-label">{data.confidence}% confidence</span>
        </div>
      )}
      {data.rationale && <p className="xp-horizon-note">{data.rationale}</p>}
    </div>
  )
}

function PointList({ title, points, tone }: { title: string; points?: string[]; tone?: string }) {
  if (!points || points.length === 0) return null
  return (
    <div className="xp-points">
      <h4 className={tone}>{title}</h4>
      <ul>
        {points.map((p, i) => (
          <li key={i}>{p}</li>
        ))}
      </ul>
    </div>
  )
}

export default function Explore() {
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState<SymbolSuggestion[]>([])
  const [showSuggest, setShowSuggest] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [analysis, setAnalysis] = useState<StockAnalysis | null>(null)
  const [recent, setRecent] = useState<ExploreRecentItem[]>([])
  const [recentLoading, setRecentLoading] = useState(true)
  const boxRef = useRef<HTMLDivElement>(null)

  const loadRecent = useCallback(async () => {
    try {
      const items = await fetchExploreRecent(30)
      setRecent(items)
    } catch {
      /* keep prior list */
    } finally {
      setRecentLoading(false)
    }
  }, [])

  useEffect(() => {
    loadRecent()
  }, [loadRecent])

  useEffect(() => {
    const q = query.trim()
    if (q.length < 1) {
      setSuggestions([])
      return
    }
    const t = setTimeout(async () => {
      try {
        const res = await fetchExploreSymbols(q)
        setSuggestions(res)
      } catch {
        setSuggestions([])
      }
    }, 200)
    return () => clearTimeout(t)
  }, [query])

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setShowSuggest(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const runAnalysis = useCallback(
    async (symbol: string) => {
      const q = symbol.trim()
      if (!q) return
      setShowSuggest(false)
      setQuery(q.toUpperCase())
      setLoading(true)
      setError('')
      setAnalysis(null)
      try {
        const res = await analyzeStock(q)
        if (res.error) {
          setError(res.message || 'Could not analyse this stock.')
          setAnalysis(null)
        } else {
          setAnalysis(res)
          void loadRecent()
        }
      } catch (e) {
        const err = e as { response?: { data?: { detail?: string } }; message?: string }
        setError(err.response?.data?.detail || err.message || 'Analysis failed. Try again.')
      } finally {
        setLoading(false)
      }
    },
    [loadRecent],
  )

  const report = analysis?.report

  return (
    <div className="explore-page">
      <div>
        <h1 className="explore-title">Deep Agent</h1>
        <p className="xp-sub">
          AI deep research on any NSE stock.
          Same-day reports are cached; they refresh automatically the next day.
        </p>
      </div>

      <div className="xp-searchbar" ref={boxRef}>
        <div className="xp-search-input">
          <span className="xp-search-icon">⌕</span>
          <input
            type="search"
            value={query}
            placeholder="Enter stock name or symbol (e.g. RELIANCE, Tata Motors)…"
            onChange={(e) => {
              setQuery(e.target.value)
              setShowSuggest(true)
            }}
            onFocus={() => setShowSuggest(true)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') runAnalysis(query)
            }}
          />
          <button
            type="button"
            className="btn primary"
            disabled={loading || !query.trim()}
            onClick={() => runAnalysis(query)}
          >
            {loading ? 'Analysing…' : 'Analyse'}
          </button>
          {analysis && !loading && (
            <button
              type="button"
              className="btn ghost xp-recent-btn"
              onClick={() => {
                setAnalysis(null)
                setError('')
                void loadRecent()
              }}
            >
              ← Recent
            </button>
          )}
        </div>
        {showSuggest && suggestions.length > 0 && (
          <ul className="xp-suggest">
            {suggestions.map((s) => (
              <li
                key={s.symbol}
                onClick={() => {
                  setQuery(s.symbol)
                  runAnalysis(s.symbol)
                }}
              >
                <span className="xp-suggest-sym">{s.symbol}</span>
                <span className="xp-suggest-co">{s.company}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {!loading && !analysis && (
        <section className="xp-recent" aria-label="Recent Deep Agent searches">
          <div className="xp-recent-head">
            <h2>Recent searches</h2>
            <span>Last 30 · click a box for the full report</span>
          </div>
          {recentLoading && <p className="xp-recent-empty">Loading recent…</p>}
          {!recentLoading && recent.length === 0 && (
            <div className="gw-empty" style={{ padding: '32px 24px' }}>
              <p style={{ margin: '0 0 8px', fontWeight: 600, color: 'var(--gw-text-primary)' }}>
                No searches yet
              </p>
              <p style={{ margin: 0 }}>
                Type a stock symbol or company name above and hit Analyse. Results appear here as a
                3×10 grid.
              </p>
            </div>
          )}
          {!recentLoading && recent.length > 0 && (
            <div className="xp-recent-grid">
              {Array.from({ length: 30 }, (_, i) => {
                const item = recent[i]
                if (!item) {
                  return <div key={`empty-${i}`} className="xp-recent-cell is-empty" aria-hidden />
                }
                return (
                  <button
                    key={item.symbol}
                    type="button"
                    className="xp-recent-cell"
                    title={`${item.symbol} — ${item.company}`}
                    onClick={() => runAnalysis(item.symbol)}
                  >
                    <span className="xp-recent-sym">{item.symbol}</span>
                    <span className="xp-recent-name">{item.company}</span>
                  </button>
                )
              })}
            </div>
          )}
        </section>
      )}

      {loading && (
        <div className="gw-loading">
          <span className="gw-spinner" />
          Building report — fetching prices, fundamentals & news, then running AI analysis…
        </div>
      )}

      {error && !loading && <div className="gw-empty">{error}</div>}

      {analysis && report && !loading && (
        <div className="xp-report">
          {/* Header / verdict */}
          <div className="xp-report-head">
            <div>
              <h2 className="xp-co">{analysis.company}</h2>
              <div className="xp-meta">
                <span className="xp-sym">{analysis.symbol}</span>
                {analysis.sector && analysis.sector !== 'Unknown' && (
                  <span className="xp-tag">{analysis.sector}</span>
                )}
                <span className="xp-price">₹{fmtNum(analysis.metrics.close)}</span>
                <span
                  className={
                    Number(analysis.metrics.change_pct) >= 0 ? 'xp-chg is-bull' : 'xp-chg is-bear'
                  }
                >
                  {Number(analysis.metrics.change_pct) >= 0 ? '+' : ''}
                  {fmtNum(analysis.metrics.change_pct)}%
                </span>
                {analysis.from_cache && <span className="xp-tag xp-cache-tag">Cached today</span>}
              </div>
            </div>
            <div className="xp-head-right">
              <div className={`xp-verdict ${verdictClass(report.verdict)}`}>
                <span className="xp-verdict-label">{report.verdict || 'Hold'}</span>
                {typeof report.conviction === 'number' && (
                  <span className="xp-verdict-conv">{report.conviction}% conviction</span>
                )}
              </div>
              <button
                type="button"
                className="btn secondary xp-pdf-btn"
                onClick={() => exportStockReportPdf(analysis)}
              >
                ⭳ Download PDF
              </button>
            </div>
          </div>

          {report.summary && <p className="xp-summary">{report.summary}</p>}
          {report.parse_note && <p className="xp-note">{report.parse_note}</p>}

          {/* Outlook horizons */}
          <div className="xp-section">
            <h3>Outlook</h3>
            <div className="xp-horizons">
              <HorizonCard title="Next Week" data={report.outlook?.next_week} />
              <HorizonCard title="Next Month" data={report.outlook?.next_month} />
              <HorizonCard title="Next 3 Months" data={report.outlook?.next_3_months} />
            </div>
          </div>

          {/* Trade plan */}
          {report.entry && (
            <div className="xp-section">
              <h3>Trade Plan</h3>
              <div className="xp-plan">
                <div><span>Buy Zone</span><strong>{report.entry.buy_zone || '–'}</strong></div>
                <div><span>Stop Loss</span><strong>₹{fmtNum(report.entry.stop_loss)}</strong></div>
                <div><span>Target 1</span><strong>₹{fmtNum(report.entry.target_1)}</strong></div>
                <div><span>Target 2</span><strong>₹{fmtNum(report.entry.target_2)}</strong></div>
                <div><span>Risk / Reward</span><strong>{report.entry.risk_reward || '–'}</strong></div>
              </div>
            </div>
          )}

          {/* Analysis columns */}
          <div className="xp-section">
            <h3>Analysis</h3>
            <div className="xp-analysis-grid">
              <div className="xp-analysis-card">
                <div className="xp-analysis-head">
                  <span>Fundamental</span>
                  <span className={`xp-badge ${biasClass(report.fundamental?.rating)}`}>
                    {report.fundamental?.rating || '–'}
                  </span>
                </div>
                <PointList title="Highlights" points={report.fundamental?.points} />
                <PointList title="Risks" points={report.fundamental?.risks} tone="is-bear" />
              </div>

              <div className="xp-analysis-card">
                <div className="xp-analysis-head">
                  <span>Technical</span>
                  <span className={`xp-badge ${biasClass(report.technical?.trend || report.technical?.rating)}`}>
                    {report.technical?.trend || report.technical?.rating || '–'}
                  </span>
                </div>
                <PointList title="Signals" points={report.technical?.points} />
                {report.technical?.key_levels && (
                  <div className="xp-levels">
                    <span>Support <strong>₹{fmtNum(report.technical.key_levels.support)}</strong></span>
                    <span>Resistance <strong>₹{fmtNum(report.technical.key_levels.resistance)}</strong></span>
                  </div>
                )}
              </div>

              <div className="xp-analysis-card">
                <div className="xp-analysis-head">
                  <span>Sentiment</span>
                  <span className={`xp-badge ${biasClass(report.sentiment?.rating)}`}>
                    {report.sentiment?.rating || '–'}
                  </span>
                </div>
                <PointList title="Read" points={report.sentiment?.points} />
                {report.sentiment?.industry_impact && (
                  <div className="xp-industry-impact">
                    <h4>Industry Impact</h4>
                    <p>{report.sentiment.industry_impact}</p>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Catalysts / red flags */}
          {Boolean(report.catalysts?.length || report.red_flags?.length) && (
            <div className="xp-section xp-two-col">
              <PointList title="Catalysts" points={report.catalysts} tone="is-bull" />
              <PointList title="Red Flags" points={report.red_flags} tone="is-bear" />
            </div>
          )}

          {/* Key metrics */}
          <div className="xp-section">
            <h3>Key Metrics</h3>
            <div className="xp-metrics">
              {METRIC_ORDER.filter((k) => analysis.metrics[k] !== undefined && analysis.metrics[k] !== null).map(
                (k) => (
                  <div key={k} className="xp-metric">
                    <span className="xp-metric-label">{METRIC_LABELS[k]}</span>
                    <span className="xp-metric-val">{fmtNum(analysis.metrics[k])}</span>
                  </div>
                ),
              )}
            </div>
          </div>

          {/* News */}
          {analysis.news.length > 0 && (
            <div className="xp-section">
              <h3>Company News</h3>
              <ul className="xp-news">
                {analysis.news.map((n, i) => (
                  <li key={i}>
                    <a href={n.link} target="_blank" rel="noreferrer">
                      {n.title}
                    </a>
                    <span className="xp-news-src">{n.source}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {analysis.industry_news?.length > 0 && (
            <div className="xp-section">
              <h3>Industry / Sector News{analysis.sector && analysis.sector !== 'Unknown' ? ` · ${analysis.sector}` : ''}</h3>
              <ul className="xp-news">
                {analysis.industry_news.map((n, i) => (
                  <li key={i}>
                    <a href={n.link} target="_blank" rel="noreferrer">
                      {n.title}
                    </a>
                    <span className="xp-news-src">{n.source}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {report.conclusion && (
            <div className={`xp-conclusion ${verdictClass(report.verdict)}`}>
              <h3>Bottom Line</h3>
              <p>{report.conclusion}</p>
              <span className="xp-conclusion-note">Target horizon: up to 3 months</span>
            </div>
          )}

          <p className="xp-disclaimer">
            Generated {analysis.generated_at} · engine: {report.engine || 'ai'}. For research and
            educational purposes only — not investment advice. Past signals do not guarantee future
            results.
          </p>
        </div>
      )}
    </div>
  )
}

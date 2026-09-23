import { useCallback, useEffect, useRef, useState } from 'react'
import {
  acknowledgeNewsFeed,
  addNewsWatchSymbol,
  fetchExploreSymbols,
  fetchNewsFeed,
  getNewsWsUrl,
  removeNewsWatchSymbol,
  refreshNewsFeed,
  type NewsSymbolFeedGroup,
} from '../api/client'
import { getAuthUser } from '../auth'

function verdictClass(v?: string) {
  const b = (v || '').toLowerCase()
  if (b.includes('bull')) return 'is-bull'
  if (b.includes('bear')) return 'is-bear'
  return 'is-neutral'
}

function formatWhen(iso?: string | null) {
  if (!iso) return ''
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

function sentimentTier(score?: number, verdict?: string): { heat: string; label: string } {
  let s = typeof score === 'number' ? score : 50
  if (typeof score !== 'number') {
    const v = (verdict || '').toLowerCase()
    if (v.includes('bull')) s = 70
    else if (v.includes('bear')) s = 30
  }
  if (s >= 67) return { heat: 'heat-good', label: 'Good' }
  if (s >= 40) return { heat: 'heat-moderate', label: 'Moderate' }
  return { heat: 'heat-risk', label: 'Risk' }
}

function headlineCount(group: NewsSymbolFeedGroup) {
  const f = group.feed
  return (f?.company_news?.length || 0) + (f?.sector_news?.length || 0) + (f?.rss_hits?.length || 0)
}

function HeatmapTile({
  group,
  onOpen,
  onRemove,
}: {
  group: NewsSymbolFeedGroup
  onOpen: (sym: string) => void
  onRemove: (sym: string) => void
}) {
  const feed = group.feed
  const analysis = feed?.analysis
  const score = analysis?.sentiment_score
  const hasNew = Boolean(feed?.has_new)
  const count = headlineCount(group)
  const tier = sentimentTier(score, analysis?.verdict)

  return (
    <div className={`mn-tile ${tier.heat} ${hasNew ? 'has-alert' : ''}`}>
      <button
        type="button"
        className="mn-tile-remove"
        onClick={() => onRemove(group.symbol)}
        title={`Remove ${group.symbol}`}
        aria-label={`Remove ${group.symbol}`}
      >
        ×
      </button>
      {hasNew && (
        <span className="mn-alert" title={`${feed?.new_count || ''} new headline(s)`}>
          <span className="mn-alert-dot" />
        </span>
      )}
      <button type="button" className="mn-tile-hit" onClick={() => onOpen(group.symbol)}>
        <span className="mn-tile-tier">{tier.label}</span>
        <span className="mn-tile-sym">{group.symbol}</span>
        <span className="mn-tile-co">{group.company}</span>
        {group.sector && <span className="mn-tile-sector">{group.sector}</span>}
        <div className="mn-tile-meta">
          {typeof score === 'number' && <span className="mn-tile-score">{score}</span>}
          <span className="mn-tile-score-label">sentiment</span>
        </div>
        <p className="mn-tile-snippet">
          {analysis?.impact_summary?.slice(0, 120) || `${count} headlines tracked`}
          {(analysis?.impact_summary?.length || 0) > 120 ? '…' : ''}
        </p>
        <span className="mn-tile-foot">
          {count} stories · {formatWhen(group.updated_at) || 'pending'}
        </span>
      </button>
    </div>
  )
}

function SymbolDetailModal({
  group,
  onClose,
  onRemove,
  onRefresh,
  busy,
}: {
  group: NewsSymbolFeedGroup
  onClose: () => void
  onRemove: (sym: string) => void
  onRefresh: (sym: string) => void
  busy: boolean
}) {
  const feed = group.feed
  const analysis = feed?.analysis
  const headlines = [
    ...(feed?.company_news || []),
    ...(feed?.sector_news || []),
    ...(feed?.rss_hits || []),
  ]

  return (
    <div className="mn-detail-backdrop" onClick={onClose} role="presentation">
      <div className="mn-detail-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <header className="mn-detail-head">
          <div>
            <h2>{group.symbol}</h2>
            <p>{group.company}</p>
            {group.sector && <span className="mn-sector">{group.sector}</span>}
          </div>
          <div className="mn-card-actions">
            {analysis?.verdict && (
              <span className={`mn-verdict ${verdictClass(analysis.verdict)}`}>
                {analysis.verdict.toUpperCase()}
              </span>
            )}
            <button type="button" className="btn ghost small" onClick={() => onRefresh(group.symbol)} disabled={busy}>
              Refresh
            </button>
            <button type="button" className="mn-remove" onClick={() => onRemove(group.symbol)} title="Remove">
              ×
            </button>
            <button type="button" className="mn-remove" onClick={onClose} title="Close">
              ✕
            </button>
          </div>
        </header>

        <div className="mn-detail-body">
          {analysis && (
            <section className="mn-ai-block">
              <div className="mn-ai-top">
                <strong>AI market impact</strong>
                {typeof analysis.sentiment_score === 'number' && (
                  <span className="mn-score">{analysis.sentiment_score}/100</span>
                )}
              </div>
              <p>{analysis.impact_summary}</p>
              {analysis.sector_note && <p className="mn-sector-note">{analysis.sector_note}</p>}
              {(analysis.highlights?.length || 0) > 0 && (
                <ul className="mn-highlights">
                  {analysis.highlights!.map((h, i) => (
                    <li key={i}>
                      {h.link ? (
                        <a href={h.link} target="_blank" rel="noopener noreferrer">
                          {h.title}
                        </a>
                      ) : (
                        h.title
                      )}
                      {h.impact && <span className="mn-impact-note">{h.impact}</span>}
                      {h.source && <span className="mn-src">{h.source}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          <section className="mn-headlines">
            <h3>All headlines ({headlines.length})</h3>
            {headlines.length === 0 ? (
              <p className="mn-muted">No headlines yet — auto-updates every 60s.</p>
            ) : (
              <ul>
                {headlines.map((h, i) => (
                  <li key={`${h.link || h.title}-${i}`}>
                    <div className="mn-hl-main">
                      {h.link ? (
                        <a href={h.link} target="_blank" rel="noopener noreferrer">
                          {h.title}
                        </a>
                      ) : (
                        h.title
                      )}
                    </div>
                    <div className="mn-hl-meta">
                      {h.source && <span>{h.source}</span>}
                      {h.published && <span>{formatWhen(h.published)}</span>}
                    </div>
                    {h.summary && <p className="mn-hl-snippet">{h.summary}</p>}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <footer className="mn-card-foot">
          Updated {formatWhen(group.updated_at) || '—'} · Live sentiment agent (60s poll)
        </footer>
      </div>
    </div>
  )
}

export default function MarketNews() {
  const user = getAuthUser()
  const username = user?.username || 'leninstark'

  const [feeds, setFeeds] = useState<NewsSymbolFeedGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [live, setLive] = useState(false)

  const [addOpen, setAddOpen] = useState(false)
  const [detailSymbol, setDetailSymbol] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState<{ symbol: string; company: string }[]>([])
  const [adding, setAdding] = useState(false)

  const wsRef = useRef<WebSocket | null>(null)
  const searchDebounce = useRef<ReturnType<typeof setTimeout> | null>(null)

  const applyFeeds = useCallback((rows: NewsSymbolFeedGroup[]) => {
    setFeeds(rows)
    setLoading(false)
  }, [])

  const load = useCallback(async (q?: string) => {
    setError(null)
    try {
      const rows = await fetchNewsFeed(username, q)
      applyFeeds(rows)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load news feed')
      setLoading(false)
    }
  }, [username, applyFeeds])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (searchDebounce.current) clearTimeout(searchDebounce.current)
    searchDebounce.current = setTimeout(() => {
      load(search.trim() || undefined)
    }, 250)
    return () => {
      if (searchDebounce.current) clearTimeout(searchDebounce.current)
    }
  }, [search, load])

  useEffect(() => {
    const url = getNewsWsUrl(username)
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => setLive(true)
    ws.onclose = () => setLive(false)
    ws.onerror = () => setLive(false)
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'feed_update' && Array.isArray(msg.feeds)) {
          setFeeds(() => {
            const q = search.trim().toLowerCase()
            if (!q) return msg.feeds
            return msg.feeds.filter((f: NewsSymbolFeedGroup) => {
              const blob = `${f.symbol} ${f.company} ${f.sector || ''}`.toLowerCase()
              return blob.includes(q)
            })
          })
          setLoading(false)
        }
      } catch {
        /* ignore */
      }
    }

    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [username, search])

  useEffect(() => {
    const q = query.trim()
    if (!addOpen || q.length < 1) {
      setSuggestions([])
      return
    }
    const t = setTimeout(() => {
      fetchExploreSymbols(q).then(setSuggestions).catch(() => setSuggestions([]))
    }, 200)
    return () => clearTimeout(t)
  }, [query, addOpen])

  async function openDetail(sym: string) {
    setDetailSymbol(sym)
    setFeeds((prev) =>
      prev.map((f) =>
        f.symbol === sym && f.feed
          ? { ...f, feed: { ...f.feed, has_new: false, new_count: 0 } }
          : f,
      ),
    )
    try {
      await acknowledgeNewsFeed(sym, username)
    } catch {
      /* non-blocking */
    }
  }

  async function onAdd(sym: string, company?: string) {
    setAdding(true)
    setError(null)
    try {
      await addNewsWatchSymbol(sym, username, company)
      setAddOpen(false)
      setQuery('')
      setSuggestions([])
      await load(search.trim() || undefined)
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail || (e instanceof Error ? e.message : 'Add failed'))
    } finally {
      setAdding(false)
    }
  }

  async function onRemove(sym: string) {
    if (!window.confirm(`Remove ${sym} from Market News watch?`)) return
    try {
      await removeNewsWatchSymbol(sym, username)
      if (detailSymbol === sym) setDetailSymbol(null)
      await load(search.trim() || undefined)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Remove failed')
    }
  }

  async function onRefresh(sym?: string) {
    setBusy(true)
    try {
      await refreshNewsFeed(username, sym)
      await load(search.trim() || undefined)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Refresh failed')
    } finally {
      setBusy(false)
    }
  }

  const detailGroup = detailSymbol ? feeds.find((f) => f.symbol === detailSymbol) : null
  const unreadTotal = feeds.filter((f) => f.feed?.has_new).length

  return (
    <div className="mn-page">
      <header className="mn-toolbar">
        <div>
          <h1>Market News</h1>
          <p>
            Real-time sentiment heatmap ·{' '}
            <span className={live ? 'mn-live on' : 'mn-live'}>{live ? 'Live agent' : 'Connecting…'}</span>
            {unreadTotal > 0 && <span className="mn-unread-pill">{unreadTotal} with new news</span>}
          </p>
        </div>
        <div className="mn-toolbar-actions">
          <input
            className="mn-search"
            placeholder="Search symbols…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button type="button" className="btn secondary" onClick={() => onRefresh()} disabled={busy}>
            Refresh all
          </button>
          <button type="button" className="btn primary" onClick={() => setAddOpen(true)}>
            + Add stock
          </button>
        </div>
      </header>

      {error && (
        <div className="mn-error" role="alert">
          {error}
          <button type="button" onClick={() => setError(null)} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}

      <main className="mn-main">
        {loading && feeds.length === 0 && (
          <div className="mn-status">
            <span className="wl-spinner" />
            Loading sentiment heatmap…
          </div>
        )}

        {!loading && feeds.length === 0 && (
          <div className="mn-empty">
            <h2>Build your news heatmap</h2>
            <p>
              Add stocks to track live headlines and AI sentiment. Cards color by bullish/bearish/neutral —
              tap any tile for full analysis and linked sources.
            </p>
            <button type="button" className="btn primary" onClick={() => setAddOpen(true)}>
              + Add your first stock
            </button>
          </div>
        )}

        {feeds.length > 0 && (
          <div className="mn-legend">
            <span><i className="risk" /> Risk · score &lt; 40</span>
            <span><i className="mod" /> Moderate · 40–66</span>
            <span><i className="good" /> Good · 67+</span>
          </div>
        )}

        <div className="mn-heatmap">
          {feeds.map((g) => (
            <HeatmapTile key={g.symbol} group={g} onOpen={openDetail} onRemove={onRemove} />
          ))}
        </div>
      </main>

      {addOpen && (
        <div className="mn-modal-backdrop" onClick={() => setAddOpen(false)} role="presentation">
          <div className="mn-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
            <header>
              <h2>Add stock to news watch</h2>
              <button type="button" className="mn-remove" onClick={() => setAddOpen(false)}>
                ×
              </button>
            </header>
            <input
              className="mn-search full"
              autoFocus
              placeholder="Search NSE symbol or company…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <ul className="mn-suggest">
              {suggestions.map((s) => (
                <li key={s.symbol}>
                  <button type="button" onClick={() => onAdd(s.symbol, s.company)} disabled={adding}>
                    <strong>{s.symbol}</strong>
                    <span>{s.company}</span>
                  </button>
                </li>
              ))}
              {query.trim() && suggestions.length === 0 && !adding && (
                <li className="mn-muted">No matches — try ticker or company name</li>
              )}
              {adding && <li className="mn-muted">Fetching news & running AI analysis…</li>}
            </ul>
          </div>
        </div>
      )}

      {detailGroup && (
        <SymbolDetailModal
          group={detailGroup}
          onClose={() => setDetailSymbol(null)}
          onRemove={onRemove}
          onRefresh={onRefresh}
          busy={busy}
        />
      )}
    </div>
  )
}

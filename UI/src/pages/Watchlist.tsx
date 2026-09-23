import { useCallback, useEffect, useRef, useState } from 'react'
import {
  addWatchlistSymbol,
  fetchExploreSymbols,
  fetchWatchlist,
  fetchWatchlistHistory,
  removeWatchlistSymbol,
  watchlistChat,
  type WatchlistAnalystAnswer,
  type WatchlistAnswerBlock,
  type WatchlistChatResult,
  type WatchlistItemRow,
} from '../api/client'
import { getAuthUser } from '../auth'
import { exportWatchlistChatPdf } from '../utils/exportPdf'

type ChatTurn = {
  role: 'user' | 'analyst'
  text: string
  answer?: WatchlistAnalystAnswer
}

function verdictClass(v?: string) {
  const b = (v || '').toLowerCase()
  if (b.includes('bull')) return 'is-bull'
  if (b.includes('bear')) return 'is-bear'
  if (b.includes('wait')) return 'is-wait'
  return 'is-neutral'
}

function AnswerBlocks({ blocks }: { blocks: WatchlistAnswerBlock[] }) {
  return (
    <div className="wl-blocks">
      {blocks.map((b, i) => {
        const key = `${b.type}-${i}`
        if (b.type === 'paragraph' && b.text) {
          return (
            <section key={key} className="wl-block wl-block-paragraph">
              {b.title ? <h4>{b.title}</h4> : null}
              <p>{b.text}</p>
            </section>
          )
        }
        if (b.type === 'bullets' && Array.isArray(b.items) && b.items.length) {
          return (
            <section key={key} className="wl-block wl-block-bullets">
              {b.title ? <h4>{b.title}</h4> : null}
              <ul>
                {b.items.map((item, j) => (
                  <li key={j}>{typeof item === 'string' ? item : `${item.label ?? ''}: ${item.value ?? ''}`}</li>
                ))}
              </ul>
            </section>
          )
        }
        if (b.type === 'kv' && Array.isArray(b.items) && b.items.length) {
          return (
            <section key={key} className="wl-block wl-block-kv">
              {b.title ? <h4>{b.title}</h4> : null}
              <dl>
                {b.items.map((item, j) => {
                  if (typeof item === 'string') {
                    return (
                      <div key={j} className="wl-kv-row">
                        <dt>—</dt>
                        <dd>{item}</dd>
                      </div>
                    )
                  }
                  return (
                    <div key={j} className="wl-kv-row">
                      <dt>{item.label || '—'}</dt>
                      <dd>{String(item.value ?? '—')}</dd>
                    </div>
                  )
                })}
              </dl>
            </section>
          )
        }
        if (b.type === 'table' && b.columns?.length && b.rows?.length) {
          return (
            <section key={key} className="wl-block wl-block-table">
              {b.title ? <h4>{b.title}</h4> : null}
              <div className="wl-table-wrap">
                <table>
                  <thead>
                    <tr>
                      {b.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((row, ri) => (
                      <tr key={ri}>
                        {row.map((cell, ci) => (
                          <td key={ci}>{String(cell)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )
        }
        if (b.type === 'bars' && Array.isArray(b.items) && b.items.length) {
          const numeric = b.items
            .map((item) => {
              if (typeof item === 'string') return { label: item, value: 0 }
              const n = Number(item.value)
              return { label: String(item.label ?? ''), value: Number.isFinite(n) ? n : 0 }
            })
            .filter((x) => x.label)
          const maxAbs = Math.max(...numeric.map((x) => Math.abs(x.value)), 1)
          return (
            <section key={key} className="wl-block wl-block-bars">
              {b.title ? <h4>{b.title}</h4> : null}
              <div className="wl-bars">
                {numeric.map((x) => (
                  <div key={x.label} className="wl-bar-row">
                    <span className="wl-bar-label">{x.label}</span>
                    <div className="wl-bar-track">
                      <span
                        className={`wl-bar-fill ${x.value >= 0 ? 'pos' : 'neg'}`}
                        style={{ width: `${(Math.abs(x.value) / maxAbs) * 100}%` }}
                      />
                    </div>
                    <span className="wl-bar-value">
                      {x.value > 0 ? '+' : ''}
                      {x.value.toFixed(1)}%
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )
        }
        if (b.text) {
          return (
            <section key={key} className="wl-block wl-block-paragraph">
              {b.title ? <h4>{b.title}</h4> : null}
              <p>{b.text}</p>
            </section>
          )
        }
        return null
      })}
    </div>
  )
}

function AnalystReport({ answer }: { answer: WatchlistAnalystAnswer }) {
  if (answer.blocked) {
    return (
      <div className="wl-blocked-card">
        <span className="wl-blocked-label">Out of scope</span>
        <p className="wl-blocked">{answer.summary_plain}</p>
      </div>
    )
  }

  const blocks = (answer.blocks || []).filter(Boolean)
  const hasBlocks = blocks.length > 0

  return (
    <article className="wl-report">
      <header className="wl-report-head">
        <div className={`wl-verdict-pill ${verdictClass(answer.verdict)}`}>
          {(answer.verdict || 'neutral').toUpperCase()}
        </div>
        {typeof answer.conviction === 'number' && (
          <div className="wl-conviction">
            <div className="wl-conviction-bar">
              <span style={{ width: `${Math.max(0, Math.min(100, answer.conviction))}%` }} />
            </div>
            <span className="wl-conviction-label">{answer.conviction}% conviction</span>
          </div>
        )}
      </header>

      {hasBlocks ? (
        <AnswerBlocks blocks={blocks} />
      ) : (
        answer.summary_plain && <p className="wl-summary">{answer.summary_plain}</p>
      )}

      {((answer.catalysts?.length || 0) > 0 || (answer.risks?.length || 0) > 0) && (
        <div className="wl-dual-grid">
          {(answer.catalysts?.length || 0) > 0 && (
            <section className="wl-report-block catalysts">
              <h4>Catalysts</h4>
              <ul>
                {answer.catalysts!.map((c, j) => (
                  <li key={j}>{c}</li>
                ))}
              </ul>
            </section>
          )}
          {(answer.risks?.length || 0) > 0 && (
            <section className="wl-report-block risks">
              <h4>Risks</h4>
              <ul>
                {answer.risks!.map((c, j) => (
                  <li key={j}>{c}</li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </article>
  )
}

export default function Watchlist() {
  const user = getAuthUser()
  const username = user?.username || 'leninstark'

  const [items, setItems] = useState<WatchlistItemRow[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState<{ symbol: string; company: string }[]>([])
  const [adding, setAdding] = useState(false)

  const [chatInput, setChatInput] = useState('')
  const [chatBusy, setChatBusy] = useState(false)
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const chatEndRef = useRef<HTMLDivElement>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const rows = await fetchWatchlist(username)
      setItems(rows)
      setSelected((prev) => {
        if (prev && rows.some((r) => r.symbol === prev)) return prev
        return rows.length ? rows[0].symbol : null
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load watchlist')
    } finally {
      setLoading(false)
    }
  }, [username])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!selected) {
      setTurns([])
      return
    }
    fetchWatchlistHistory(selected, username, 15).then((hist) => {
      const mapped: ChatTurn[] = []
      for (const h of [...hist].reverse()) {
        if (h.question) mapped.push({ role: 'user', text: h.question })
        mapped.push({
          role: 'analyst',
          text: h.payload?.summary_plain || '',
          answer: h.payload,
        })
      }
      setTurns(mapped)
    })
  }, [selected, username])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns, chatBusy])

  useEffect(() => {
    const q = query.trim()
    if (q.length < 1) {
      setSuggestions([])
      return
    }
    const t = setTimeout(() => {
      fetchExploreSymbols(q).then(setSuggestions).catch(() => setSuggestions([]))
    }, 200)
    return () => clearTimeout(t)
  }, [query])

  async function onAdd(sym: string, company?: string) {
    setAdding(true)
    try {
      await addWatchlistSymbol(sym, username, company)
      setQuery('')
      setSuggestions([])
      await load()
      setSelected(sym.toUpperCase())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Add failed')
    } finally {
      setAdding(false)
    }
  }

  async function onRemove(sym: string) {
    try {
      await removeWatchlistSymbol(sym, username)
      if (selected === sym) setSelected(null)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Remove failed')
    }
  }

  async function onSend(forceRefresh = false) {
    const msg = chatInput.trim()
    if (!msg || !selected || chatBusy) return
    const sym = selected
    setChatInput('')
    setTurns((t) => [...t, { role: 'user', text: msg }])
    setChatBusy(true)
    setError(null)
    try {
      const res: WatchlistChatResult = await watchlistChat({
        symbol: sym,
        message: msg,
        username,
        force_refresh: forceRefresh,
      })
      const ans = res.answer || {}
      setTurns((t) => [
        ...t,
        {
          role: 'analyst',
          text: ans.summary_plain || 'No response',
          answer: ans,
        },
      ])
      // Optimistically pin this symbol to top, then sync from server
      setItems((prev) => {
        const idx = prev.findIndex((r) => r.symbol === sym)
        if (idx <= 0) return prev
        const next = [...prev]
        const [row] = next.splice(idx, 1)
        next.unshift(row)
        return next
      })
      const rows = await fetchWatchlist(username)
      setItems(rows)
      setSelected(sym)
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } } }
      setError(err.response?.data?.detail || (e instanceof Error ? e.message : 'Chat failed'))
    } finally {
      setChatBusy(false)
    }
  }

  const selectedRow = items.find((i) => i.symbol === selected)
  const lastAnswer = [...turns].reverse().find((t) => t.role === 'analyst' && t.answer)

  return (
    <div className="wl-page">
      <header className="wl-toolbar">
        <div className="wl-toolbar-left">
          <h1>Watchlist Analyst</h1>
          <p>Multi-chat workspace · pick a symbol anytime</p>
        </div>
        <div className="wl-toolbar-actions">
          <span className="wl-count-badge">{items.length} symbols</span>
          {lastAnswer?.answer && selected && (
            <button
              type="button"
              className="btn secondary"
              onClick={() =>
                exportWatchlistChatPdf(selected, selectedRow?.company || selected, turns)
              }
            >
              Download PDF
            </button>
          )}
        </div>
      </header>

      {error && (
        <div className="wl-error-banner" role="alert">
          {error}
          <button type="button" onClick={() => setError(null)} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}

      <div className="wl-shell">
        <aside className="wl-rail">
          <div className="wl-rail-head">
            <span className="wl-rail-title">Symbols</span>
          </div>

          <div className="wl-search-wrap">
            <input
              className="wl-search"
              placeholder="Search & add symbol…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Add symbol"
            />
            {suggestions.length > 0 && (
              <ul className="wl-suggest">
                {suggestions.map((s) => (
                  <li key={s.symbol}>
                    <button type="button" onClick={() => onAdd(s.symbol, s.company)} disabled={adding}>
                      <strong>{s.symbol}</strong>
                      <span>{s.company}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="wl-symbol-list">
            {loading && (
              <div className="wl-list-status">
                <span className="wl-spinner" />
                Loading watchlist…
              </div>
            )}
            {!loading && items.length === 0 && (
              <div className="wl-empty">
                <p>No symbols yet</p>
                <span>Search above to track NSE stocks</span>
              </div>
            )}
            {!loading &&
              items.map((row) => (
                <div
                  key={row.symbol}
                  className={`wl-symbol-row ${selected === row.symbol ? 'is-active' : ''}`}
                  onClick={() => setSelected(row.symbol)}
                  onKeyDown={(e) => e.key === 'Enter' && setSelected(row.symbol)}
                  role="button"
                  tabIndex={0}
                >
                  <div className="wl-symbol-main">
                    <span className="wl-symbol-ticker">{row.symbol}</span>
                    <span className="wl-symbol-co">{row.company}</span>
                  </div>
                  <div className="wl-symbol-meta">
                    {row.sector && <span className="wl-sector-tag">{row.sector}</span>}
                    <button
                      type="button"
                      className="wl-remove"
                      onClick={(e) => {
                        e.stopPropagation()
                        onRemove(row.symbol)
                      }}
                      title={`Remove ${row.symbol}`}
                      aria-label={`Remove ${row.symbol}`}
                    >
                      ×
                    </button>
                  </div>
                </div>
              ))}
          </div>
        </aside>

        <main className="wl-chat-panel">
          {!selected ? (
            <div className="wl-placeholder">
              <div className="wl-placeholder-icon">◎</div>
              <h2>Select a symbol</h2>
              <p>Pick a stock from the left. Chat stays in this panel — symbols stay visible so you can switch anytime.</p>
            </div>
          ) : (
            <>
              <header className="wl-chat-header">
                <div className="wl-chat-title">
                  <h2>{selected}</h2>
                  <p>{selectedRow?.company}</p>
                </div>
                {selectedRow?.sector && <span className="wl-head-sector">{selectedRow.sector}</span>}
              </header>

              <div className="wl-thread" role="log" aria-live="polite">
                {turns.length === 0 && !chatBusy && (
                  <div className="wl-starter-prompts">
                    <p className="wl-starter-label">Suggested questions</p>
                    <button type="button" className="wl-prompt-chip" onClick={() => setChatInput(`Should I buy ${selected} for tomorrow intraday?`)}>
                      Intraday setup for tomorrow
                    </button>
                    <button type="button" className="wl-prompt-chip" onClick={() => setChatInput(`What are support and resistance levels for ${selected}?`)}>
                      Support & resistance levels
                    </button>
                    <button type="button" className="wl-prompt-chip" onClick={() => setChatInput(`Summarize latest news and sector context for ${selected}`)}>
                      News & sector context
                    </button>
                  </div>
                )}

                {turns.map((t, i) => (
                  <div key={i} className={`wl-turn ${t.role}`}>
                    {t.role === 'user' ? (
                      <div className="wl-user-msg">
                        <span className="wl-turn-label">You</span>
                        <p>{t.text}</p>
                      </div>
                    ) : t.answer ? (
                      <div className="wl-analyst-msg">
                        <span className="wl-turn-label">Analyst</span>
                        <AnalystReport answer={t.answer} />
                      </div>
                    ) : null}
                  </div>
                ))}

                {chatBusy && (
                  <div className="wl-turn analyst">
                    <div className="wl-analyst-msg loading">
                      <span className="wl-turn-label">Analyst</span>
                      <div className="wl-loading-row">
                        <span className="wl-spinner" />
                        Gathering NSE, news & technical data…
                      </div>
                    </div>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>

              <footer className="wl-compose">
                <div className="wl-compose-row">
                  <textarea
                    rows={2}
                    placeholder={`Message about ${selected} — stocks & trading only`}
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        onSend()
                      }
                    }}
                  />
                  <div className="wl-compose-actions">
                    <button
                      type="button"
                      className="wl-icon-btn primary"
                      onClick={() => onSend(false)}
                      disabled={chatBusy || !chatInput.trim()}
                      title="Send"
                      aria-label="Send"
                    >
                      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="currentColor">
                        <path d="M3.4 20.4 20.85 12.92c.7-.3.7-1.3 0-1.6L3.4 3.84c-.6-.27-1.25.28-1.1.93l1.6 6.5c.08.34.35.59.7.64L14 12 4.6 12.09c-.35.05-.62.3-.7.64l-1.6 6.5c-.15.65.5 1.2 1.1.93Z" />
                      </svg>
                    </button>
                    <button
                      type="button"
                      className="wl-icon-btn secondary"
                      onClick={() => onSend(true)}
                      disabled={chatBusy || !chatInput.trim()}
                      title="Deep analysis — answer with freshly fetched market data"
                      aria-label="Deep analysis"
                    >
                      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="currentColor">
                        <path d="M4 19h10v1.8H4z" />
                        <path d="M5.2 17V11h1.8v6H5.2zm3.5 0V7.5h1.8V17H8.7zm3.5 0v-3.8h1.8V17h-1.8z" />
                        <path d="M15.6 4.4a4.1 4.1 0 1 1 0 8.2 4.1 4.1 0 0 1 0-8.2Zm0 1.7a2.4 2.4 0 1 0 0 4.8 2.4 2.4 0 0 0 0-4.8Z" />
                        <path d="m18.7 12.8 2.9 2.9-1.2 1.2-2.9-2.9 1.2-1.2Z" />
                      </svg>
                    </button>
                  </div>
                </div>
              </footer>
            </>
          )}
        </main>
      </div>
    </div>
  )
}

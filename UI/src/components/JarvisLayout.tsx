import { useCallback, useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  jarvisWatchAdd,
  jarvisWatchRemove,
  updateJarvisConfig,
} from '../api/client'
import { getAuthUser } from '../auth'

export type JarvisLane = 'time' | 'mind'

export type JarvisLabChrome = {
  running: boolean
  packReady: boolean
  dayPnl?: number
  unrealizedPnl?: number
  /** Short execution status shown between Reset and Start */
  statusText?: string
  onReset: () => void
  onRun: () => void
}

export type JarvisOutletContext = {
  setLabChrome: (chrome: JarvisLabChrome | null) => void
  lane: JarvisLane
  setLane: (lane: JarvisLane) => void
  mindSymbols: string[]
  openMindPicker: () => void
}

function MindPickerModal({
  open,
  symbols,
  draft,
  error,
  busy,
  onDraft,
  onAdd,
  onRemove,
  onClose,
  onSave,
}: {
  open: boolean
  symbols: string[]
  draft: string
  error: string
  busy: boolean
  onDraft: (v: string) => void
  onAdd: () => void
  onRemove: (s: string) => void
  onClose: () => void
  onSave: () => void
}) {
  if (!open) return null
  return (
    <div className="gw-modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="gw-modal jv-mind-modal"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="jv-mind-title"
      >
        <h2 id="jv-mind-title">MIND · add stocks to observe</h2>
        <p className="gw-modal-hint">
          Lane B — you choose the list. JARVIS will watch these for entry (same 30m rule as TIME).
        </p>
        <div className="jv-watch-add">
          <input
            value={draft}
            autoFocus
            onChange={(e) => onDraft(e.target.value.toUpperCase())}
            placeholder="Symbol e.g. RELIANCE"
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                onAdd()
              }
            }}
            disabled={busy}
          />
          <button type="button" className="btn primary small" onClick={onAdd} disabled={busy || !draft.trim()}>
            Add
          </button>
        </div>
        <div className="jv-watch-chips" style={{ marginTop: 12 }}>
          {symbols.length === 0 ? (
            <span className="jv-muted">No symbols yet.</span>
          ) : (
            symbols.map((s) => (
              <span key={s} className="jv-watch-chip active">
                {s}
                <button type="button" className="jv-watch-x" aria-label={`Remove ${s}`} onClick={() => onRemove(s)}>
                  ×
                </button>
              </span>
            ))
          )}
        </div>
        {error ? (
          <p className="login-error" style={{ marginTop: 12 }}>
            {error}
          </p>
        ) : null}
        <div className="gw-modal-actions">
          <button type="button" className="btn ghost small" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className="btn primary small"
            disabled={busy || symbols.length === 0}
            onClick={onSave}
          >
            {busy ? 'Starting…' : 'Start'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function JarvisLayout() {
  const location = useLocation()
  const onTest = location.pathname.includes('/jarvis/test')
  const onAgent = location.pathname.includes('/jarvis/agent')
  const username = getAuthUser()?.username || 'leninstark'
  const [labChrome, setLabChromeState] = useState<JarvisLabChrome | null>(null)
  const [lane, setLaneState] = useState<JarvisLane>(() => {
    try {
      const raw = localStorage.getItem('jarvis_observe_lane')
      return raw === 'mind' ? 'mind' : 'time'
    } catch {
      return 'time'
    }
  })
  const [mindOpen, setMindOpen] = useState(false)
  const [mindDraft, setMindDraft] = useState('')
  const [mindSymbols, setMindSymbols] = useState<string[]>(() => {
    try {
      const raw = localStorage.getItem('jarvis_mind_symbols')
      const parsed = raw ? (JSON.parse(raw) as unknown) : []
      return Array.isArray(parsed) ? parsed.map(String) : []
    } catch {
      return []
    }
  })
  const [mindError, setMindError] = useState('')
  const [mindBusy, setMindBusy] = useState(false)

  const persistMindSymbols = useCallback((syms: string[]) => {
    setMindSymbols(syms)
    try {
      localStorage.setItem('jarvis_mind_symbols', JSON.stringify(syms))
    } catch {
      /* ignore */
    }
  }, [])

  const setLabChrome = useCallback((chrome: JarvisLabChrome | null) => {
    setLabChromeState(chrome)
  }, [])

  const openMindPicker = useCallback(() => {
    setMindError('')
    setMindDraft('')
    setMindOpen(true)
  }, [])

  const applyLane = useCallback(
    (next: JarvisLane, openPicker: boolean) => {
      setLaneState(next)
      try {
        localStorage.setItem('jarvis_observe_lane', next)
      } catch {
        /* ignore */
      }
      void updateJarvisConfig(username, { observe_lane: next }).catch(() => {})
      if (next === 'mind' && openPicker) openMindPicker()
    },
    [username, openMindPicker],
  )

  const setLane = useCallback(
    (next: JarvisLane) => {
      applyLane(next, next === 'mind')
    },
    [applyLane],
  )

  useEffect(() => {
    void updateJarvisConfig(username, { observe_lane: lane }).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount sync only
  }, [username])

  const addMindSymbol = () => {
    const s = mindDraft.trim().toUpperCase()
    if (!s) return
    if (!/^[A-Z0-9][A-Z0-9&-]*$/.test(s)) {
      setMindError('Invalid symbol')
      return
    }
    if (mindSymbols.includes(s)) {
      setMindDraft('')
      return
    }
    persistMindSymbols([...mindSymbols, s])
    setMindDraft('')
    setMindError('')
  }

  const removeMindSymbol = (sym: string) => {
    persistMindSymbols(mindSymbols.filter((x) => x !== sym))
  }

  const saveMindList = async () => {
    if (mindSymbols.length === 0) {
      setMindError('Add at least one stock')
      return
    }
    setMindBusy(true)
    setMindError('')
    try {
      for (const s of mindSymbols) {
        await jarvisWatchAdd(username, s)
      }
      setMindOpen(false)
    } catch (e) {
      setMindError(e instanceof Error ? e.message : 'Failed to save watch list')
    } finally {
      setMindBusy(false)
    }
  }

  const ctx = useMemo<JarvisOutletContext>(
    () => ({ setLabChrome, lane, setLane, mindSymbols, openMindPicker }),
    [setLabChrome, lane, setLane, mindSymbols, openMindPicker],
  )

  return (
    <div className="jv-shell">
      <nav className="jv-subtabs" aria-label="Jarvis">
        <div className="jv-subtabs-center">
          <div className="jv-lane-toggle" role="group" aria-label="Observation lane">
            <button
              type="button"
              className={`jv-lane-btn${lane === 'mind' ? ' active' : ''}`}
              title="MIND · Lane B · you pick stocks"
              aria-pressed={lane === 'mind'}
              onClick={() => applyLane('mind', true)}
            >
              MIND
            </button>
            <button
              type="button"
              className={`jv-lane-btn${lane === 'time' ? ' active' : ''}`}
              title="TIME · Lane A · Jarvis picks stocks"
              aria-pressed={lane === 'time'}
              onClick={() => applyLane('time', false)}
            >
              TIME
            </button>
          </div>

          <NavLink
            to="/infinity/jarvis/test"
            className={({ isActive }) => `jv-nav-icon${isActive ? ' active' : ''}`}
            title="Test Lab"
            aria-label="Test Lab"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path
                d="M9 3h6M10 3v6.2L5.2 17.5A3 3 0 0 0 7.8 22h8.4a3 3 0 0 0 2.6-4.5L14 9.2V3"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path d="M8.5 14h7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </NavLink>

          <NavLink
            to="/infinity/jarvis/agent"
            className={({ isActive }) => `jv-nav-icon${isActive ? ' active' : ''}`}
            title="Run Agent"
            aria-label="Run Agent"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
              <rect x="5" y="7" width="14" height="12" rx="3" stroke="currentColor" strokeWidth="2" />
              <path
                d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7"
                stroke="currentColor"
                strokeWidth="2"
              />
              <circle cx="9.5" cy="13" r="1.25" fill="currentColor" />
              <circle cx="14.5" cy="13" r="1.25" fill="currentColor" />
              <path d="M3 12h2M19 12h2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </NavLink>
        </div>

        {(onTest || onAgent || labChrome) && (
          <div
            className={`jv-exec-status${labChrome?.running ? ' live' : ''}`}
            aria-live="polite"
            title={labChrome?.statusText || 'Idle'}
          >
            <span className={`jv-exec-dot${labChrome?.running ? ' on' : ''}`} aria-hidden />
            <span className="jv-exec-text">
              {labChrome?.statusText || (labChrome?.running ? 'Running…' : 'Idle')}
            </span>
          </div>
        )}

        {(labChrome || onTest || onAgent) && (
          <div className="jv-subtabs-actions">
            <div
              className={`jv-top-pnl${(labChrome?.dayPnl ?? 0) > 0 ? ' up' : (labChrome?.dayPnl ?? 0) < 0 ? ' down' : ''}`}
              title="Execution P&L"
            >
              <span className="jv-top-pnl-label">P&amp;L</span>
              <strong>
                {(labChrome?.dayPnl ?? 0) >= 0 ? '+' : '−'}₹
                {Math.abs(labChrome?.dayPnl ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              </strong>
              {labChrome?.unrealizedPnl != null && labChrome.unrealizedPnl !== 0 && (
                <span className="jv-top-pnl-u">
                  u {labChrome.unrealizedPnl >= 0 ? '+' : ''}
                  {Math.round(labChrome.unrealizedPnl).toLocaleString('en-IN')}
                </span>
              )}
            </div>
            {(onTest || onAgent) && (
              <>
                <button
                  type="button"
                  className="jv-icon-btn"
                  title="Reset"
                  aria-label="Reset"
                  disabled={!labChrome || (onTest && labChrome.running)}
                  onClick={() => labChrome?.onReset()}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
                    <path
                      d="M21 12a9 9 0 1 1-2.64-6.36"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                    />
                    <path
                      d="M21 3v6h-6"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>

                <button
                  type="button"
                  className="jv-icon-btn primary"
                  title={onAgent && labChrome?.running ? 'Stop live scan' : onTest ? 'Run pack' : 'Run live scan'}
                  aria-label={onAgent && labChrome?.running ? 'Stop' : 'Run'}
                  disabled={!labChrome || (onTest && (labChrome.running || !labChrome.packReady))}
                  onClick={() => labChrome?.onRun()}
                >
                  {labChrome?.running ? (
                    onAgent ? (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                        <rect x="6" y="6" width="12" height="12" rx="2" />
                      </svg>
                    ) : (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                        <circle cx="12" cy="12" r="8" opacity="0.25" />
                        <path
                          d="M12 4a8 8 0 0 1 8 8"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2.5"
                          strokeLinecap="round"
                        >
                          <animateTransform
                            attributeName="transform"
                            type="rotate"
                            from="0 12 12"
                            to="360 12 12"
                            dur="0.8s"
                            repeatCount="indefinite"
                          />
                        </path>
                      </svg>
                    )
                  ) : (
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                      <path d="M8 5v14l11-7L8 5z" />
                    </svg>
                  )}
                </button>
              </>
            )}
          </div>
        )}
      </nav>

      <Outlet context={ctx} />

      <MindPickerModal
        open={mindOpen}
        symbols={mindSymbols}
        draft={mindDraft}
        error={mindError}
        busy={mindBusy}
        onDraft={setMindDraft}
        onAdd={addMindSymbol}
        onRemove={(s) => {
          void jarvisWatchRemove(username, s).catch(() => {})
          removeMindSymbol(s)
        }}
        onClose={() => !mindBusy && setMindOpen(false)}
        onSave={() => void saveMindList()}
      />
    </div>
  )
}

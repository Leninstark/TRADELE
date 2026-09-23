import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import {
  fetchJarvisObserve,
  focusJarvisObserve,
  startJarvisObserve,
  stopJarvisObserve,
  type JarvisObserveState,
} from '../api/client'
import type { JarvisOutletContext } from '../components/JarvisLayout'
import {
  PriceActionChart,
  type BrainActivity,
  type BrainFocusChart,
} from '../components/JarvisBrainCharts'
import { getAuthUser } from '../auth'

type LiveUi = NonNullable<JarvisObserveState['live_ui']>

function activeQuad(phase?: string): 1 | 2 | 3 | 4 | 0 {
  const p = (phase || '').toLowerCase()
  if (p === 'boot' || p === 'scan') return 1
  if (p === 'decide' || p === 'claude') return 2
  if (p === 'observe' || p === 'risk') return 3
  if (p === 'exec' || p === 'manage' || p === 'done') return 4
  return 0
}

function ScanSpark({ scores }: { scores: number[] }) {
  const w = 220
  const h = 40
  if (scores.length === 0) {
    return (
      <svg viewBox={`0 0 ${w} ${h}`} className="jv-spark" aria-hidden>
        <text x={8} y={24} fontSize="11" fill="currentColor" opacity="0.45">
          Waiting for scan…
        </text>
      </svg>
    )
  }
  const max = Math.max(...scores.map(Math.abs), 1)
  const n = scores.length
  const barW = Math.max(2, (w - 8) / n - 1)
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="jv-spark" role="img">
      {scores.map((s, i) => {
        const bh = (Math.abs(s) / max) * (h - 8)
        const x = 4 + i * (barW + 1)
        const y = h - 4 - bh
        return (
          <rect
            key={i}
            x={x}
            y={y}
            width={barW}
            height={bh}
            rx={1}
            fill={s >= 0 ? '#16a34a' : '#dc2626'}
            opacity={0.85}
          />
        )
      })}
    </svg>
  )
}

export default function JarvisDesk() {
  const username = getAuthUser()?.username || 'leninstark'
  const { lane, mindSymbols, openMindPicker, setLabChrome } = useOutletContext<JarvisOutletContext>()
  const [observe, setObserve] = useState<JarvisObserveState | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [chartFocus, setChartFocus] = useState<string | null>(null)
  const scanEndRef = useRef<HTMLDivElement>(null)
  const roundKeyRef = useRef<string>('')

  const live = (observe?.live_ui || {}) as LiveUi
  const active = Boolean(observe?.active) || Boolean(live.running)
  const phase = live.phase || observe?.status || 'idle'
  const scanning = phase === 'scan' || phase === 'boot' || observe?.status === 'scanning'

  const refresh = useCallback(async () => {
    const res = await fetchJarvisObserve(username)
    if (res.observe) setObserve(res.observe)
  }, [username])

  useEffect(() => {
    refresh().catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'))
  }, [refresh])

  useEffect(() => {
    if (!active && observe?.status !== 'scanning') return
    // Fast poll while scanning; slow while observing (chart updates ~1m server-side)
    const ms = scanning ? 500 : 2000
    const id = window.setInterval(() => {
      refresh().catch(() => undefined)
    }, ms)
    return () => window.clearInterval(id)
  }, [active, observe?.status, scanning, refresh])

  useEffect(() => {
    scanEndRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [live.scan_log?.length])

  const statusText = useMemo(() => {
    if (live.detail) return String(live.detail).slice(0, 72)
    if (observe?.message) return String(observe.message).slice(0, 72)
    if (active) return 'Scanning Zerodha 1m…'
    return lane === 'mind' ? 'MIND ready' : 'TIME ready · Run to pick top 5'
  }, [live.detail, observe?.message, active, lane])

  const onRun = useCallback(async () => {
    if (observe?.active) {
      setBusy(true)
      setError('')
      try {
        const res = await stopJarvisObserve(username)
        setObserve(res.observe)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Stop failed')
      } finally {
        setBusy(false)
      }
      return
    }
    if (lane === 'mind') {
      if (mindSymbols.length === 0) {
        openMindPicker()
        return
      }
    }
    setBusy(true)
    setError('')
    setChartFocus(null)
    try {
      const res = await startJarvisObserve(
        username,
        lane === 'mind' ? 'mind' : 'time',
        lane === 'mind' ? mindSymbols : undefined,
      )
      if (!res.ok) {
        setError(res.error || 'Live scan failed')
      }
      setObserve(res.observe)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Live scan failed')
    } finally {
      setBusy(false)
    }
  }, [observe?.active, username, lane, mindSymbols, openMindPicker])

  useEffect(() => {
    setLabChrome({
      running: active || busy,
      packReady: true,
      dayPnl: 0,
      unrealizedPnl: 0,
      statusText,
      onReset: () => {
        void stopJarvisObserve(username).then((r) => setObserve(r.observe)).catch(() => undefined)
      },
      onRun: () => {
        void onRun()
      },
    })
    return () => setLabChrome(null)
  }, [setLabChrome, active, busy, statusText, username, onRun])

  const scanLog = (live.scan_log || []) as Array<{
    symbol?: string
    status?: string
    score?: number | null
    side?: string
    reason?: string
    strategy?: string
  }>
  const decisions = (live.decisions || []) as Array<{
    symbol?: string
    side?: string
    score?: number
    strategy?: string
    verdict?: string
    why?: string
    entry?: number
    sl?: number
    tp?: number
  }>
  const execution = live.execution || []
  const activity = (live.charts?.activity || null) as BrainActivity | null
  const picked = live.picked
  const quad = activeQuad(phase)

  const focusChart = useMemo(() => {
    const cands = (observe?.candidates || []) as Array<{ symbol?: string; chart?: BrainFocusChart }>
    if (chartFocus) {
      const hit = cands.find((c) => c.symbol === chartFocus)
      if (hit?.chart) return hit.chart
    }
    return (live.charts?.focus || null) as BrainFocusChart | null
  }, [observe?.candidates, chartFocus, live.charts?.focus])

  const chartSymbol = focusChart?.symbol || chartFocus || '—'

  const pickedRows = useMemo(() => {
    if (decisions.length) return decisions.slice(0, 10)
    const fromCands = (observe?.candidates || []) as Array<{
      symbol?: string
      side?: string
      score?: number
      action?: string
      watch_status?: string
    }>
    if (fromCands.length) {
      return fromCands.slice(0, 10).map((c) => ({
        symbol: c.symbol,
        side: c.side,
        score: c.score,
        verdict: c.watch_status || c.action || 'watch',
        why: '',
      }))
    }
    return scanLog
      .filter((r) => r.status === 'keep')
      .slice(-10)
      .map((r) => ({
        symbol: r.symbol,
        side: r.side,
        score: r.score ?? undefined,
        verdict: r.status,
        why: r.reason,
      }))
  }, [decisions, observe?.candidates, scanLog])

  // Reset focus when a new pick round lands
  useEffect(() => {
    const key = `${observe?.round || 0}:${observe?.started_at || ''}:${pickedRows[0]?.symbol || ''}`
    if (!pickedRows[0]?.symbol) return
    if (roundKeyRef.current === key) return
    roundKeyRef.current = key
    setChartFocus(pickedRows[0].symbol || null)
  }, [observe?.round, observe?.started_at, pickedRows])

  const onFocusChip = useCallback(
    async (sym: string) => {
      setChartFocus(sym)
      if (!observe?.active) return
      try {
        const res = await focusJarvisObserve(username, sym)
        if (res.observe) setObserve(res.observe)
      } catch {
        /* keep local chip selection */
      }
    },
    [username, observe?.active],
  )

  const alerts = (live.alerts || observe?.alerts || []) as Array<{
    symbol?: string
    side?: string
    last?: number
    entry?: number
    message?: string
  }>
  const latestAlert = alerts.length ? alerts[alerts.length - 1] : null

  const headerPicks =
    pickedRows.length > 0
      ? `Watching ${pickedRows.length} · entry notify`
      : 'Zerodha live scan · waiting for top 10'

  const sparkScores = useMemo(() => {
    const feed = activity?.score_feed || []
    if (feed.length) return feed.slice(-48).map((f) => (f.side === 'SHORT' ? -Number(f.score) : Number(f.score)))
    return scanLog.slice(-48).map((r) => {
      const s = Number(r.score || 0)
      return r.side === 'SHORT' ? -s : s
    })
  }, [activity?.score_feed, scanLog])

  const remainSec =
    observe?.observe_until && observe.active
      ? Math.max(0, Math.floor(Number(observe.observe_until) - Date.now() / 1000))
      : null

  return (
    <div className={`inf-desk jv-lab jv-quad-desk${active ? ' is-running' : ''}`}>
      {error && <p className="jv-banner err">{error}</p>}
      {latestAlert && (
        <p className="jv-banner alert" role="alert">
          {latestAlert.message ||
            `ENTRY HIT · ${latestAlert.symbol} ${latestAlert.side} @ ${latestAlert.last} — execute manually`}
        </p>
      )}

      <div className="jv-quad-grid">
        <section className={`jv-quad q1${quad === 1 ? ' active' : ''}${active ? ' anim' : ''}`}>
          <header className="jv-quad-head">
            <h3>{headerPicks}</h3>
            <span className="jv-quad-tag">Q1 · Live scan</span>
          </header>
          <div className="jv-quad-body">
            <ScanSpark scores={sparkScores} />
            <div className="jv-pick-chips">
              {pickedRows.length === 0 && <p className="jv-muted">Run TIME to scan Zerodha 1m…</p>}
              {pickedRows.map((p, i) => (
                <button
                  key={`${p.symbol}-${i}`}
                  type="button"
                  className={`jv-watch-chip${chartFocus === p.symbol ? ' active' : ''}${
                    String(p.verdict || '').includes('ENTRY_HIT') ? ' hit' : ''
                  }`}
                  onClick={() => p.symbol && void onFocusChip(p.symbol)}
                >
                  {p.symbol} · {p.side || '—'} · {p.score ?? '—'}
                  {String(p.verdict || '').includes('ENTRY_HIT') ? ' · HIT' : ''}
                </button>
              ))}
            </div>
            <div className="jv-scan-stream jv-quad-scroll">
              {scanLog.length === 0 && (
                <p className="jv-muted">Live Zerodha scores stream here while JARVIS scans…</p>
              )}
              {scanLog
                .slice(-40)
                .reverse()
                .map((row, i) => (
                  <div key={`${row.symbol}-${i}`} className={`jv-scan-row ${row.status || ''}`}>
                    <strong>{row.symbol}</strong>
                    <span className="jv-score">{row.score ?? '—'}</span>
                    <span>{row.side || ''}</span>
                    <span className="jv-muted">{row.reason || row.status}</span>
                  </div>
                ))}
              <div ref={scanEndRef} />
            </div>
          </div>
        </section>

        <section className={`jv-quad q2${quad === 2 || quad === 3 ? ' active' : ''}${active ? ' anim' : ''}`}>
          <header className="jv-quad-head">
            <h3>Decision board</h3>
            <span className="jv-quad-tag">
              Q2 · 30m watch
              {remainSec != null ? ` · ${Math.floor(remainSec / 60)}m` : ''}
            </span>
          </header>
          <div className="jv-quad-body jv-quad-scroll">
            {decisions.length === 0 ? (
              <p className="jv-muted">Top 10 locked — waiting for any name to reach entry for manual exec…</p>
            ) : (
              <ul className="jv-decision-list">
                {decisions.map((d, i) => (
                  <li key={`${d.symbol}-${d.verdict}-${i}`}>
                    <div className="jv-decision-head">
                      <strong>
                        {d.symbol} {d.side}
                      </strong>
                      <span className={`jv-verdict ${d.verdict || ''}`}>{d.verdict}</span>
                      <span className="jv-score">{d.score}</span>
                    </div>
                    <p>{d.why}</p>
                    {(d.entry != null || d.sl != null || d.tp != null) && (
                      <p className="jv-muted">
                        Entry {d.entry ?? '—'} · SL {d.sl ?? '—'} · TP {d.tp ?? '—'}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <section className={`jv-quad q3${quad === 3 ? ' active' : ''}${active ? ' anim' : ''}`}>
          <header className="jv-quad-head">
            <h3>Live candles · {chartSymbol}</h3>
            <span className="jv-quad-tag">Q3 · Zerodha 1m</span>
          </header>
          <div className="jv-quad-body jv-quad-scroll">
            {focusChart ? (
              <PriceActionChart focus={focusChart} />
            ) : (
              <p className="jv-muted">Candles for the top pick appear after the live scan…</p>
            )}
            {activity && (
              <div className="jv-brain-meta-row" style={{ marginTop: 8 }}>
                <span className="jv-muted">
                  Scanned {activity.scanned_ok ?? 0} · L {activity.long_n ?? 0} / S {activity.short_n ?? 0}
                </span>
              </div>
            )}
          </div>
        </section>

        <section className={`jv-quad q4${quad === 4 ? ' active' : ''}${active ? ' anim' : ''}`}>
          <header className="jv-quad-head">
            <h3>Alerts · manual exec</h3>
            <span className="jv-quad-tag">Q4 · No auto order</span>
          </header>
          <div className="jv-quad-body jv-quad-scroll">
            <ul className="jv-exec-list">
              {execution.length === 0 && (
                <li className="jv-muted">Selection steps only — no Groww / Zerodha orders.</li>
              )}
              {execution
                .slice()
                .reverse()
                .map((e, i) => (
                  <li key={`ex-${i}`}>
                    <span className="jv-tape-kind">{e.step || 'select'}</span>
                    <span>{e.message}</span>
                  </li>
                ))}
            </ul>
            {picked && (
              <div className="jv-master-card" style={{ marginTop: 10 }}>
                <strong>
                  Primary · {String(picked.symbol)} {String(picked.side || '')}
                </strong>
                <div className="jv-master-grid">
                  <span>Score {String(picked.score ?? '—')}</span>
                  <span>Entry {String(picked.entry ?? '—')}</span>
                  <span>SL {String(picked.sl ?? '—')}</span>
                  <span>TP {String(picked.tp ?? '—')}</span>
                </div>
              </div>
            )}
            <p className="jv-muted" style={{ marginTop: 8 }}>
              {observe?.zerodha_connected ? 'Zerodha connected' : 'Zerodha status unknown'} · lane{' '}
              {(observe?.lane || lane).toUpperCase()} · round {observe?.round || 0}
            </p>
          </div>
        </section>
      </div>
    </div>
  )
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import {
  fetchJarvisThink,
  jarvisTestPackInfo,
  jarvisTestPackRun,
  jarvisTestReset,
  type JarvisSnapshot,
} from '../api/client'
import type { JarvisOutletContext } from '../components/JarvisLayout'
import {
  PriceActionChart,
  type BrainActivity,
  type BrainFocusChart,
} from '../components/JarvisBrainCharts'
import { getAuthUser } from '../auth'

type ThinkState = {
  running?: boolean
  phase?: string
  progress?: number
  title?: string
  detail?: string
  scan_log?: Array<{
    symbol?: string
    status?: string
    score?: number | null
    side?: string
    reason?: string
    strategy?: string
  }>
  decisions?: Array<{
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
  claude?: {
    provider?: string
    summary?: string
    approve?: boolean
    why?: string
    size?: string
  } | null
  execution?: Array<{ step?: string; message?: string }>
  timeline?: Array<{ phase?: string; title?: string; detail?: string; at?: number }>
  picked?: {
    symbol?: string
    side?: string
    score?: number
    strategy?: string
    entry?: number
    sl?: number
    tp?: number
    reasons?: string[]
  } | null
  charts?: {
    focus?: BrainFocusChart
    activity?: BrainActivity
    mode?: string
  } | null
  pack?: { session?: string; symbols?: number; bars?: number }
  error?: string | null
}

type SimState = {
  paper_positions?: Array<Record<string, unknown>>
  day_pnl?: number
  unrealized_pnl?: number
  scenario?: string | null
}

function fmtPnl(n: number | null | undefined) {
  if (n == null || Number.isNaN(n)) return '—'
  const sign = n >= 0 ? '+' : ''
  return `${sign}₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

function activeQuad(phase?: string): 1 | 2 | 3 | 4 | 0 {
  const p = (phase || '').toLowerCase()
  if (p === 'boot' || p === 'scan') return 1
  if (p === 'decide' || p === 'claude') return 2
  if (p === 'risk') return 3
  if (p === 'exec' || p === 'manage') return 4
  if (p === 'done') return 4
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
          >
            {i === n - 1 && (
              <animate attributeName="opacity" values="0.4;1;0.4" dur="1.2s" repeatCount="indefinite" />
            )}
          </rect>
        )
      })}
    </svg>
  )
}

export default function JarvisTestLab() {
  const username = getAuthUser()?.username || 'leninstark'
  const { setLabChrome } = useOutletContext<JarvisOutletContext>()
  const [think, setThink] = useState<ThinkState>({})
  const [sim, setSim] = useState<SimState>({})
  const [snapshot, setSnapshot] = useState<JarvisSnapshot | null>(null)
  const [packInfo, setPackInfo] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState('')
  const [chartFocus, setChartFocus] = useState<string | null>(null)
  const scanEndRef = useRef<HTMLDivElement>(null)
  const execEndRef = useRef<HTMLDivElement>(null)

  const packReady = Boolean(packInfo?.exists)

  const refreshThink = useCallback(async () => {
    const res = await fetchJarvisThink(username)
    setThink((res.think || {}) as ThinkState)
    setSim((res.sim || {}) as SimState)
    setSnapshot(res.snapshot || null)
  }, [username])

  const onRun = useCallback(async () => {
    setError('')
    try {
      await jarvisTestPackRun(username, { use_claude: true, pace: 0.07 })
      setThink((t) => ({ ...t, running: true, phase: 'boot', progress: 1, title: 'Starting…' }))
      await refreshThink()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start run')
    }
  }, [username, refreshThink])

  const onReset = useCallback(async () => {
    setError('')
    try {
      await jarvisTestReset(username)
      await refreshThink()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Reset failed')
    }
  }, [username, refreshThink])

  const dayPnl = sim.day_pnl ?? snapshot?.day_pnl ?? 0
  const uPnl = sim.unrealized_pnl ?? snapshot?.unrealized_pnl ?? 0

  const statusText = useMemo(() => {
    const exec = think.execution || []
    const lastExec = exec.length ? exec[exec.length - 1] : null
    if (lastExec?.message) {
      const step = lastExec.step ? `${String(lastExec.step).replace(/_/g, ' ')} · ` : ''
      return `${step}${lastExec.message}`.slice(0, 72)
    }
    const phase = (think.phase || '').toLowerCase()
    if (think.running) {
      if (phase === 'boot') return 'Booting pack…'
      if (phase === 'scan') return 'Scanning universe…'
      if (phase === 'decide') return 'Ranking candidates…'
      if (phase === 'claude') return 'Claude advising…'
      if (phase === 'risk') return 'Risk gate…'
      if (phase === 'exec') return 'Sending order…'
      if (phase === 'manage') return 'Managing position…'
      return think.title || 'Running…'
    }
    if (phase === 'done' && think.picked?.symbol) {
      return `Filled · ${think.picked.symbol} ${think.picked.side || ''}`.trim()
    }
    return packReady ? 'Ready' : 'Pack missing'
  }, [think.execution, think.phase, think.running, think.title, think.picked, packReady])

  useEffect(() => {
    setLabChrome({
      running: Boolean(think.running),
      packReady,
      dayPnl,
      unrealizedPnl: uPnl,
      statusText,
      onReset: () => {
        void onReset()
      },
      onRun: () => {
        void onRun()
      },
    })
    return () => setLabChrome(null)
  }, [setLabChrome, think.running, packReady, dayPnl, uPnl, statusText, onReset, onRun])

  useEffect(() => {
    jarvisTestPackInfo(username)
      .then((p) => setPackInfo(p as Record<string, unknown>))
      .catch(() => setPackInfo(null))
    refreshThink().catch((e) => setError(e instanceof Error ? e.message : 'Failed to load'))
  }, [username, refreshThink])

  useEffect(() => {
    if (!think.running) return
    const id = window.setInterval(() => {
      refreshThink().catch(() => undefined)
    }, 280)
    return () => window.clearInterval(id)
  }, [think.running, refreshThink])

  useEffect(() => {
    scanEndRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [think.scan_log?.length])

  useEffect(() => {
    execEndRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [think.execution?.length, think.timeline?.length])

  const scanLog = think.scan_log || []
  const decisions = think.decisions || []
  const execution = think.execution || []
  const timeline = think.timeline || []
  const positions = sim.paper_positions || []
  const running = Boolean(think.running)
  const quad = activeQuad(think.phase)

  const pickedRows = useMemo(() => {
    const fromDec = decisions.filter((d) => (d.verdict || '').toLowerCase() !== 'skip')
    if (fromDec.length) return fromDec.slice(0, 10)
    const shortlist = scanLog
      .filter((r) => r.status === 'keep' || (typeof r.score === 'number' && r.score >= 60))
      .slice(-10)
    return shortlist.map((r) => ({
      symbol: r.symbol,
      side: r.side,
      score: r.score ?? undefined,
      strategy: r.strategy,
      verdict: r.status || 'scan',
      why: r.reason,
    }))
  }, [decisions, scanLog])

  const pickCount = pickedRows.length || (think.picked ? 1 : 0)
  const headerPicks =
    pickCount > 0
      ? `Picked ${pickCount} stock${pickCount === 1 ? '' : 's'} for observation`
      : 'Scan stream · waiting for picks'

  const sparkScores = useMemo(() => {
    const feed = think.charts?.activity?.score_feed || []
    if (feed.length) return feed.slice(-48).map((f) => (f.side === 'SHORT' ? -Number(f.score) : Number(f.score)))
    return scanLog.slice(-48).map((r) => {
      const s = Number(r.score || 0)
      return r.side === 'SHORT' ? -s : s
    })
  }, [think.charts?.activity?.score_feed, scanLog])

  const focusChart = think.charts?.focus || null
  useEffect(() => {
    if (focusChart?.symbol && !chartFocus) setChartFocus(focusChart.symbol)
  }, [focusChart?.symbol, chartFocus])

  return (
    <div className={`inf-desk jv-lab jv-quad-desk${running ? ' is-running' : ''}`}>
      {error && <p className="jv-banner err">{error}</p>}

      <div className="jv-quad-grid">
        {/* Q1 — Scan */}
        <section className={`jv-quad q1${quad === 1 ? ' active' : ''}${running ? ' anim' : ''}`}>
          <header className="jv-quad-head">
            <h3>{headerPicks}</h3>
            <span className="jv-quad-tag">Q1 · Scan</span>
          </header>
          <div className="jv-quad-body">
            <ScanSpark scores={sparkScores} />
            <div className="jv-pick-chips">
              {pickedRows.length === 0 && <span className="jv-muted">No shortlist yet…</span>}
              {pickedRows.map((p, i) => (
                <button
                  key={`${p.symbol}-${i}`}
                  type="button"
                  className={`jv-watch-chip${chartFocus === p.symbol ? ' active' : ''}`}
                  onClick={() => setChartFocus(p.symbol || null)}
                >
                  {p.symbol} · {p.side || '—'} · {p.score ?? '—'}
                </button>
              ))}
            </div>
            <div className="jv-scan-stream jv-quad-scroll">
              {scanLog.length === 0 && <p className="jv-muted">Live score stream appears while JARVIS scans…</p>}
              {scanLog
                .slice(-36)
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

        {/* Q2 — Decision */}
        <section className={`jv-quad q2${quad === 2 ? ' active' : ''}${running ? ' anim' : ''}`}>
          <header className="jv-quad-head">
            <h3>Decision board</h3>
            <span className="jv-quad-tag">Q2 · Why · 30m watch</span>
          </header>
          <div className="jv-quad-body jv-quad-scroll">
            {decisions.length === 0 ? (
              <p className="jv-muted">Decision rationales stream here as the brain ranks…</p>
            ) : (
              <ul className="jv-decision-list">
                {decisions
                  .slice()
                  .reverse()
                  .map((d, i) => (
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
                          {d.strategy ? ` · ${d.strategy}` : ''}
                        </p>
                      )}
                    </li>
                  ))}
              </ul>
            )}
            {think.claude && (
              <div className="jv-ai" style={{ marginTop: 10 }}>
                <div className="jv-ai-meta">Claude · {think.claude.provider || '—'}</div>
                <p>{think.claude.summary}</p>
                {think.claude.why ? <p className="jv-muted">{think.claude.why}</p> : null}
              </div>
            )}
          </div>
        </section>

        {/* Q3 — Charts */}
        <section className={`jv-quad q3${quad === 3 ? ' active' : ''}${running ? ' anim' : ''}`}>
          <header className="jv-quad-head">
            <h3>Live candles · {chartFocus || focusChart?.symbol || '—'}</h3>
            <span className="jv-quad-tag">Q3 · Zerodha / Groww eyes</span>
          </header>
          <div className="jv-quad-body jv-quad-scroll">
            {focusChart ? (
              <PriceActionChart
                focus={
                  chartFocus && chartFocus !== focusChart.symbol
                    ? { ...focusChart, symbol: chartFocus }
                    : focusChart
                }
              />
            ) : (
              <p className="jv-muted">Candlesticks for picked symbols appear as the pack / live feed ticks…</p>
            )}
            {think.charts?.activity && (
              <div className="jv-brain-meta-row" style={{ marginTop: 8 }}>
                <span className="jv-muted">
                  Feed {think.charts.activity.scanned_ok ?? 0} ok · L {think.charts.activity.long_n ?? 0} / S{' '}
                  {think.charts.activity.short_n ?? 0}
                </span>
              </div>
            )}
          </div>
        </section>

        {/* Q4 — Execution */}
        <section className={`jv-quad q4${quad === 4 ? ' active' : ''}${running ? ' anim' : ''}`}>
          <header className="jv-quad-head">
            <h3>Execution engine</h3>
            <span className="jv-quad-tag">Q4 · Entry / Exit · {fmtPnl(dayPnl)}</span>
          </header>
          <div className="jv-quad-body jv-quad-scroll">
            <ul className="jv-exec-list">
              {execution.length === 0 && timeline.length === 0 && (
                <li className="jv-muted">Fills, marks, targets, and stops stream here…</li>
              )}
              {execution
                .slice()
                .reverse()
                .map((e, i) => (
                  <li key={`ex-${i}`} className="jv-exec-flash">
                    <span className="jv-tape-kind">{e.step || 'exec'}</span>
                    <span>{e.message}</span>
                  </li>
                ))}
            </ul>
            <h4 className="jv-subhead">Brain tape</h4>
            <ul className="jv-tape">
              {timeline
                .slice()
                .reverse()
                .slice(0, 24)
                .map((t, i) => (
                  <li key={`tl-${i}`}>
                    <span className="jv-tape-kind">{t.phase || '—'}</span>
                    <span>
                      <strong>{t.title}</strong>
                      {t.detail ? ` — ${t.detail}` : ''}
                    </span>
                  </li>
                ))}
              <div ref={execEndRef} />
            </ul>
            <h4 className="jv-subhead">Paper book</h4>
            {positions.length === 0 ? (
              <p className="jv-muted">No open paper position</p>
            ) : (
              <div className="jv-table-wrap">
                <table className="jv-table">
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Qty</th>
                      <th>Avg</th>
                      <th>LTP</th>
                      <th>uPNL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((p) => (
                      <tr key={String(p.trading_symbol)}>
                        <td>
                          <strong>{String(p.trading_symbol)}</strong>
                        </td>
                        <td>{String(p.quantity)}</td>
                        <td>{String(p.average_price)}</td>
                        <td>{String(p.ltp ?? '—')}</td>
                        <td>{fmtPnl(Number(p.unrealised_pnl ?? 0))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {think.picked && (
              <div className="jv-master-card" style={{ marginTop: 10 }}>
                <strong>
                  Primary · {think.picked.symbol} {think.picked.side}
                </strong>
                <div className="jv-master-grid">
                  <span>Score {think.picked.score}</span>
                  <span>Entry {think.picked.entry}</span>
                  <span>SL {think.picked.sl}</span>
                  <span>TP {think.picked.tp}</span>
                </div>
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

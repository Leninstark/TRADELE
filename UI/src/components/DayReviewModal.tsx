import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import {
  fetchDayReview,
  fetchDayReviewChart,
  type DayReviewChart,
  type DayReviewData,
  type DayReviewTicker,
} from '../api/client'
import { getAuthUser } from '../auth'

type Props = {
  date: string
  style?: 'intraday' | 'swing' | 'fno'
  onClose: () => void
}

type Bar = {
  t: number
  label: string
  open: number
  high: number
  low: number
  close: number
  vwap: number | null
  ema9: number | null
  ema20: number | null
  ema50: number | null
  bbU: number | null
  bbL: number | null
  rsi: number | null
  vol: number
  orHigh: number | null
  orLow: number | null
}

function fmtPnl(n: number | null | undefined) {
  if (n == null) return '—'
  const sign = n >= 0 ? '+' : '−'
  return `${sign}₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

function shortTime(iso: string) {
  const m = iso.match(/T(\d{2}:\d{2})/) || iso.match(/\s(\d{2}:\d{2})/)
  return m ? m[1] : iso.slice(11, 16)
}

function polyline(
  pts: { t: number; v: number }[],
  xy: (t: number, v: number) => { x: number; y: number },
) {
  return pts
    .filter((p) => Number.isFinite(p.v))
    .map((p) => {
      const { x, y } = xy(p.t, p.v)
      return `${x},${y}`
    })
    .join(' ')
}

function clampRange(start: number, end: number, n: number): [number, number] {
  const minBars = Math.min(20, n)
  let s = Math.max(0, Math.min(start, n - minBars))
  let e = Math.max(s + minBars, Math.min(end, n))
  if (e - s < minBars) {
    e = Math.min(n, s + minBars)
    s = Math.max(0, e - minBars)
  }
  return [s, e]
}

function MinuteChart({ chart }: { chart: DayReviewChart }) {
  const [expanded, setExpanded] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [view, setView] = useState({ start: 0, end: 0 })
  const dragRef = useRef<{ x: number; start: number; end: number } | null>(null)
  const svgRef = useRef<SVGSVGElement | null>(null)
  const viewRef = useRef(view)
  viewRef.current = view

  const series: Bar[] = useMemo(() => {
    return (chart.candles || []).map((c) => {
      const d = new Date(c.date)
      return {
        t: d.getTime(),
        label: c.date,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
        vwap: c.vwap ?? null,
        ema9: c.ema_9 ?? null,
        ema20: c.ema_20 ?? null,
        ema50: c.ema_50 ?? null,
        bbU: c.bb_upper ?? null,
        bbL: c.bb_lower ?? null,
        rsi: c.rsi ?? null,
        vol: c.volume ?? 0,
        orHigh: c.or_high ?? null,
        orLow: c.or_low ?? null,
      }
    })
  }, [chart.candles])

  useEffect(() => {
    setView({ start: 0, end: series.length })
  }, [series.length, chart.symbol])

  const n = series.length
  const [vStart, vEnd] = clampRange(view.start, view.end || n, Math.max(n, 1))
  const visible = series.slice(vStart, vEnd)
  const zoomed = vStart > 0 || vEnd < n

  const w = expanded ? 960 : 720
  const priceH = expanded ? 340 : 250
  const volH = expanded ? 70 : 56
  const rsiH = expanded ? 90 : 72
  const gap = 10
  const h = priceH + gap + volH + gap + rsiH
  const pad = { t: 14, r: 16, b: 18, l: 52 }

  const zoomBy = (factor: number, anchor = 0.5) => {
    if (n < 2) return
    const cur = viewRef.current
    const [vs, ve] = clampRange(cur.start, cur.end || n, n)
    const len = ve - vs
    const nextLen = Math.round(len * factor)
    const minBars = Math.min(20, n)
    const clampedLen = Math.max(minBars, Math.min(n, nextLen))
    const center = vs + len * anchor
    const start = Math.round(center - clampedLen * anchor)
    const [s, e] = clampRange(start, start + clampedLen, n)
    setView({ start: s, end: e })
  }

  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const onWheelNative = (e: WheelEvent) => {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      if (series.length < 2) return
      const relX = (e.clientX - rect.left) / rect.width
      const plotL = pad.l / w
      const plotR = (w - pad.r) / w
      const anchor = Math.min(1, Math.max(0, (relX - plotL) / (plotR - plotL || 1)))
      if (e.deltaY < 0) zoomBy(0.8, anchor)
      else zoomBy(1.25, anchor)
    }
    el.addEventListener('wheel', onWheelNative, { passive: false })
    return () => el.removeEventListener('wheel', onWheelNative)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series.length, w, pad.l, pad.r])

  const panByBars = (delta: number) => {
    if (!zoomed) return
    const len = vEnd - vStart
    const [s, e] = clampRange(vStart + delta, vStart + delta + len, n)
    setView({ start: s, end: e })
  }

  const onPointerDown = (e: ReactPointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return
    ;(e.currentTarget as Element).setPointerCapture(e.pointerId)
    dragRef.current = { x: e.clientX, start: vStart, end: vEnd }
    setDragging(true)
  }

  const onPointerMove = (e: ReactPointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current
    if (!drag || n < 2) return
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect) return
    const plotW = ((w - pad.l - pad.r) / w) * rect.width
    const barsVisible = Math.max(1, drag.end - drag.start)
    const barsPerPx = barsVisible / Math.max(plotW, 1)
    const dx = e.clientX - drag.x
    const shift = Math.round(-dx * barsPerPx)
    const [s, e2] = clampRange(drag.start + shift, drag.start + shift + barsVisible, n)
    setView({ start: s, end: e2 })
  }

  const onPointerUp = (e: ReactPointerEvent<SVGSVGElement>) => {
    dragRef.current = null
    setDragging(false)
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      /* ignore */
    }
  }

  if (!series.length) {
    const detail = chart.candle_error?.trim()
    return (
      <div className="mt-chart-empty" role="status">
        <p className="mt-chart-empty-title">Chart unavailable for {chart.symbol}</p>
        <p className="mt-chart-empty-body">
          {detail ||
            'No 1-min candles were returned. Connect Zerodha or Groww and retry this ticker.'}
        </p>
        {!detail && (
          <p className="mt-chart-empty-hint">
            Orders and AI coaching can still load without candles. Chart data is fetched separately
            from Groww/Zerodha historical APIs.
          </p>
        )}
        {detail && (
          <p className="mt-chart-empty-hint">
            Your Groww connection can work for orders while historical candles stay blocked (403) or
            rate-limited (429). Try Zerodha for charts, or check Groww API plan permissions.
          </p>
        )}
      </div>
    )
  }

  if (!visible.length) {
    return <p className="mt-empty">Zoom window empty — hit Reset.</p>
  }

  const priceVals = visible.flatMap((p) =>
    [p.open, p.high, p.low, p.close, p.vwap, p.ema9, p.ema20, p.ema50, p.bbU, p.bbL].filter(
      (v): v is number => v != null && Number.isFinite(v),
    ),
  )
  const minP = Math.min(...priceVals)
  const maxP = Math.max(...priceVals)
  const span = maxP - minP || 1
  const t0 = visible[0].t
  const t1 = visible[visible.length - 1].t
  const tSpan = t1 - t0 || 1
  const maxVol = Math.max(...visible.map((p) => p.vol), 1)
  const slotW = (w - pad.l - pad.r) / Math.max(visible.length, 1)
  const bodyW = Math.max(1.4, Math.min(8, slotW * 0.7))

  const xyPrice = (t: number, price: number) => {
    const x = pad.l + ((t - t0) / tSpan) * (w - pad.l - pad.r)
    const y = pad.t + (1 - (price - minP) / span) * (priceH - pad.t - pad.b)
    return { x, y }
  }

  const volTop = priceH + gap
  const rsiTop = volTop + volH + gap

  const xyRsi = (t: number, rsi: number) => {
    const x = pad.l + ((t - t0) / tSpan) * (w - pad.l - pad.r)
    const y = rsiTop + pad.t + (1 - rsi / 100) * (rsiH - pad.t - pad.b)
    return { x, y }
  }

  const vwapLine = polyline(
    visible.filter((p) => p.vwap != null).map((p) => ({ t: p.t, v: p.vwap as number })),
    xyPrice,
  )
  const ema9Line = polyline(
    visible.filter((p) => p.ema9 != null).map((p) => ({ t: p.t, v: p.ema9 as number })),
    xyPrice,
  )
  const ema20Line = polyline(
    visible.filter((p) => p.ema20 != null).map((p) => ({ t: p.t, v: p.ema20 as number })),
    xyPrice,
  )
  const ema50Line = polyline(
    visible.filter((p) => p.ema50 != null).map((p) => ({ t: p.t, v: p.ema50 as number })),
    xyPrice,
  )
  const bbULine = polyline(
    visible.filter((p) => p.bbU != null).map((p) => ({ t: p.t, v: p.bbU as number })),
    xyPrice,
  )
  const bbLLine = polyline(
    visible.filter((p) => p.bbL != null).map((p) => ({ t: p.t, v: p.bbL as number })),
    xyPrice,
  )
  const rsiLine = polyline(
    visible.filter((p) => p.rsi != null).map((p) => ({ t: p.t, v: p.rsi as number })),
    xyRsi,
  )

  const orHigh = series[0].orHigh
  const orLow = series[0].orLow
  const orHighY =
    orHigh != null && orHigh >= minP && orHigh <= maxP ? xyPrice(t0, orHigh).y : null
  const orLowY = orLow != null && orLow >= minP && orLow <= maxP ? xyPrice(t0, orLow).y : null

  const markers = (chart.markers || [])
    .map((m) => {
      const ts = new Date(m.time).getTime()
      if (ts < t0 - 60_000 || ts > t1 + 60_000) return null
      const price =
        m.price ??
        visible.reduce(
          (best, p) => (Math.abs(p.t - ts) < Math.abs(best.t - ts) ? p : best),
          visible[0],
        ).close
      const { x, y } = xyPrice(ts, price)
      return { ...m, x, y, price }
    })
    .filter((m): m is NonNullable<typeof m> => !!m && Number.isFinite(m.x) && Number.isFinite(m.y))

  const rsi30 = xyRsi(t0, 30)
  const rsi70 = xyRsi(t0, 70)
  const rsi50 = xyRsi(t0, 50)
  const windowLabel = `${shortTime(visible[0].label)} – ${shortTime(visible[visible.length - 1].label)} · ${visible.length}/${n} bars`

  return (
    <div className={`mt-day-chart-shell${expanded ? ' expanded' : ''}`}>
      <div className="mt-day-chart-toolbar">
        <div className="mt-day-chart-tools">
          <button type="button" className="mt-day-tool-btn" title="Zoom in" aria-label="Zoom in" onClick={() => zoomBy(0.7)}>
            +
          </button>
          <button type="button" className="mt-day-tool-btn" title="Zoom out" aria-label="Zoom out" onClick={() => zoomBy(1.4)}>
            −
          </button>
          <button type="button" className="mt-day-tool-btn" title="Pan left" aria-label="Pan left" onClick={() => panByBars(-Math.max(5, Math.floor((vEnd - vStart) * 0.25)))}>
            ‹
          </button>
          <button type="button" className="mt-day-tool-btn" title="Pan right" aria-label="Pan right" onClick={() => panByBars(Math.max(5, Math.floor((vEnd - vStart) * 0.25)))}>
            ›
          </button>
          <button
            type="button"
            className="mt-day-tool-btn"
            title="Reset view"
            aria-label="Reset view"
            onClick={() => setView({ start: 0, end: n })}
          >
            Reset
          </button>
          <button
            type="button"
            className="mt-day-tool-btn"
            title={expanded ? 'Compact chart' : 'Larger chart'}
            aria-label={expanded ? 'Compact chart' : 'Larger chart'}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? 'Compact' : 'Larger'}
          </button>
        </div>
        <span className="mt-day-chart-window">{windowLabel} · scroll to zoom · drag to pan</span>
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${w} ${h}`}
        className={`mt-day-svg${dragging ? ' dragging' : ''}`}
        role="img"
        aria-label={`${chart.symbol} 1-min chart`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <line x1={pad.l} y1={priceH - pad.b} x2={w - pad.r} y2={priceH - pad.b} className="mt-day-axis" />
        <line x1={pad.l} y1={pad.t} x2={pad.l} y2={priceH - pad.b} className="mt-day-axis" />
        <text x={pad.l - 6} y={pad.t + 4} className="mt-day-axis-label" textAnchor="end">
          {maxP.toFixed(1)}
        </text>
        <text x={pad.l - 6} y={priceH - pad.b} className="mt-day-axis-label" textAnchor="end">
          {minP.toFixed(1)}
        </text>

        {bbULine && <polyline points={bbULine} className="mt-day-ind bb" fill="none" />}
        {bbLLine && <polyline points={bbLLine} className="mt-day-ind bb" fill="none" />}
        {orHighY != null && (
          <line x1={pad.l} y1={orHighY} x2={w - pad.r} y2={orHighY} className="mt-day-ind or">
            <title>{`OR high ${orHigh}`}</title>
          </line>
        )}
        {orLowY != null && (
          <line x1={pad.l} y1={orLowY} x2={w - pad.r} y2={orLowY} className="mt-day-ind or">
            <title>{`OR low ${orLow}`}</title>
          </line>
        )}
        {ema50Line && <polyline points={ema50Line} className="mt-day-ind ema50" fill="none" />}
        {ema20Line && <polyline points={ema20Line} className="mt-day-ind ema20" fill="none" />}
        {vwapLine && <polyline points={vwapLine} className="mt-day-ind vwap" fill="none" />}
        {ema9Line && <polyline points={ema9Line} className="mt-day-ind ema9" fill="none" />}

        {visible.map((p) => {
          const { x } = xyPrice(p.t, p.close)
          const yHigh = xyPrice(p.t, p.high).y
          const yLow = xyPrice(p.t, p.low).y
          const yOpen = xyPrice(p.t, p.open).y
          const yClose = xyPrice(p.t, p.close).y
          const bull = p.close >= p.open
          const bodyTop = Math.min(yOpen, yClose)
          const bodyH = Math.max(Math.abs(yClose - yOpen), 1)
          return (
            <g key={`c-${p.t}`} className={bull ? 'mt-day-candle up' : 'mt-day-candle down'}>
              <line x1={x} y1={yHigh} x2={x} y2={yLow} className="mt-day-wick" />
              <rect x={x - bodyW / 2} y={bodyTop} width={bodyW} height={bodyH} className="mt-day-body">
                <title>{`${shortTime(p.label)} O ${p.open} H ${p.high} L ${p.low} C ${p.close}`}</title>
              </rect>
            </g>
          )
        })}

        {markers.map((m) => (
          <g key={`${m.order_id}-${m.time}`}>
            <circle
              cx={m.x}
              cy={m.y}
              r={6}
              className={m.side === 'BUY' ? 'mt-day-mark buy' : 'mt-day-mark sell'}
            >
              <title>{`${m.side} ${m.quantity} @ ₹${m.price} · ${shortTime(m.time)}`}</title>
            </circle>
            <text
              x={m.x}
              y={m.y - 10}
              className={m.side === 'BUY' ? 'mt-day-mark-label buy' : 'mt-day-mark-label sell'}
              textAnchor="middle"
            >
              {m.side === 'BUY' ? '▲' : '▼'}
            </text>
          </g>
        ))}

        <text x={pad.l} y={priceH - 4} className="mt-day-axis-label">
          {shortTime(visible[0].label)}
        </text>
        <text x={w - pad.r} y={priceH - 4} className="mt-day-axis-label" textAnchor="end">
          {shortTime(visible[visible.length - 1].label)}
        </text>

        <text x={pad.l + 4} y={volTop + 12} className="mt-day-axis-label">
          Vol
        </text>
        {visible.map((p, i) => {
          const x = pad.l + ((p.t - t0) / tSpan) * (w - pad.l - pad.r)
          const barH = (p.vol / maxVol) * (volH - 16)
          const up = i === 0 || p.close >= visible[i - 1].close
          return (
            <rect
              key={`v-${p.t}`}
              x={x - Math.max(bodyW * 0.45, 0.6)}
              y={volTop + volH - 4 - barH}
              width={Math.max(bodyW * 0.9, 1.2)}
              height={Math.max(barH, 0.5)}
              className={up ? 'mt-day-vol up' : 'mt-day-vol down'}
            />
          )
        })}

        <line x1={pad.l} y1={rsiTop + pad.t} x2={pad.l} y2={h - 6} className="mt-day-axis" />
        <line x1={pad.l} y1={h - 6} x2={w - pad.r} y2={h - 6} className="mt-day-axis" />
        <line x1={pad.l} y1={rsi70.y} x2={w - pad.r} y2={rsi70.y} className="mt-day-rsi-band" />
        <line x1={pad.l} y1={rsi30.y} x2={w - pad.r} y2={rsi30.y} className="mt-day-rsi-band" />
        <line x1={pad.l} y1={rsi50.y} x2={w - pad.r} y2={rsi50.y} className="mt-day-rsi-mid" />
        <text x={pad.l - 6} y={rsi70.y + 3} className="mt-day-axis-label" textAnchor="end">
          70
        </text>
        <text x={pad.l - 6} y={rsi30.y + 3} className="mt-day-axis-label" textAnchor="end">
          30
        </text>
        <text x={pad.l + 4} y={rsiTop + 12} className="mt-day-axis-label">
          RSI
        </text>
        {rsiLine && <polyline points={rsiLine} className="mt-day-ind rsi" fill="none" />}
      </svg>
    </div>
  )
}

export default function DayReviewModal({ date, style = 'intraday', onClose }: Props) {
  const username = getAuthUser()?.username || 'leninstark'
  const [data, setData] = useState<DayReviewData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [symbol, setSymbol] = useState('')
  const [chart, setChart] = useState<DayReviewChart | null>(null)
  const [chartLoading, setChartLoading] = useState(false)
  const [chartError, setChartError] = useState('')
  const [refreshingAi, setRefreshingAi] = useState(false)
  const [chartNonce, setChartNonce] = useState(0)

  const loadOverview = () => {
    setLoading(true)
    setError('')
    fetchDayReview(username, date, style)
      .then((res) => {
        setData(res)
        setSymbol((prev) => {
          if (prev && res.symbols.includes(prev)) return prev
          return res.symbols[0] || ''
        })
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : 'Failed to load day review')
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadOverview()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [username, date, style])

  useEffect(() => {
    if (!symbol) {
      setChart(null)
      return
    }
    let cancelled = false
    setChartLoading(true)
    setChartError('')
    setChart(null)
    fetchDayReviewChart(username, date, symbol, style, refreshingAi)
      .then((res) => {
        if (!cancelled) setChart(res)
      })
      .catch((e) => {
        if (!cancelled) {
          setChartError(e instanceof Error ? e.message : 'Failed to load chart')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setChartLoading(false)
          setRefreshingAi(false)
        }
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [username, date, style, symbol, chartNonce])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const tickers: DayReviewTicker[] = data?.tickers || []
  const activeTicker = tickers.find((t) => t.symbol === symbol) || tickers[0]
  const ai = chart?.ai
  const markers = chart?.markers || activeTicker?.markers || []

  return (
    <div className="mt-day-overlay" role="dialog" aria-modal="true" aria-label={`Day review ${date}`}>
      <button type="button" className="mt-day-backdrop" aria-label="Close" onClick={onClose} />
      <div className="mt-day-modal mt-day-modal-wide">
        <header className="mt-day-modal-head">
          <div>
            <h2>
              {symbol || 'Day'} review · {date}
            </h2>
            <p>
              {style === 'intraday'
                ? 'Equity Intraday (MIS)'
                : style === 'fno'
                  ? 'F&O'
                  : 'Swing'}{' '}
              · selected{' '}
              <strong>{symbol || '—'}</strong> {fmtPnl(chart?.pnl ?? activeTicker?.pnl)} · day P&amp;L{' '}
              <span className={(data?.day_pnl ?? 0) >= 0 ? 'up' : 'down'}>{fmtPnl(data?.day_pnl)}</span>
            </p>
          </div>
          <div className="mt-day-modal-actions">
            <button
              type="button"
              className="btn ghost small"
              disabled={chartLoading || refreshingAi || !symbol}
              onClick={() => {
                setRefreshingAi(true)
                setChartNonce((n) => n + 1)
              }}
            >
              Refresh coaching
            </button>
            <button
              type="button"
              className="mt-day-close-btn"
              aria-label="Close"
              title="Close"
              onClick={onClose}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  d="M6.4 6.4l11.2 11.2M17.6 6.4L6.4 17.6"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>
        </header>

        {loading && !data && <p className="mt-loading mt-day-scroll-pad">Loading tickers…</p>}
        {error && <p className="mt-banner err mt-day-scroll-pad">{error}</p>}

        {data && (
          <div className="mt-day-body">
            <aside className="mt-day-ticker-rail" aria-label="Symbols traded">
              <p className="mt-day-rail-label">Tickers</p>
              {tickers.map((t) => (
                <button
                  key={t.symbol}
                  type="button"
                  className={`mt-day-ticker-btn${t.symbol === symbol ? ' active' : ''}`}
                  onClick={() => setSymbol(t.symbol)}
                >
                  <span className="mt-day-ticker-sym">{t.symbol}</span>
                  <span className={(t.pnl ?? 0) >= 0 ? 'up' : 'down'}>{fmtPnl(t.pnl)}</span>
                  <em>{t.order_count} orders</em>
                </button>
              ))}
            </aside>

            <div className="mt-day-detail">
              <section className="mt-day-chart-block">
                <div className="mt-day-chart-meta">
                  <strong>{symbol || '—'}</strong>
                  <span>
                    {activeTicker?.order_count ?? '—'} orders
                    {chart
                      ? ` · ${chart.candle_source || '—'} · ${chart.candles?.length ?? 0} bars · full intraday pack`
                      : chartLoading
                        ? ' · fetching 1-min…'
                        : ''}
                    {chart && !chart.candles?.length && chart.candle_error ? ' · chart error' : ''}
                  </span>
                </div>

                {chartLoading && (
                  <p className="mt-loading">Fetching 1-min + coaching for {symbol}…</p>
                )}
                {chartError && <p className="mt-banner err">{chartError}</p>}
                {!chartLoading && chart && <MinuteChart chart={chart} />}

                <div className="mt-day-legend">
                  <span className="candle-up">▲ Candle</span>
                  <span className="candle-down">▼ Candle</span>
                  <span className="ema9">EMA9</span>
                  <span className="ema20">EMA20</span>
                  <span className="ema50">EMA50</span>
                  <span className="vwap">VWAP</span>
                  <span className="bb">BB</span>
                  <span className="or">OR H/L</span>
                  <span className="rsi">RSI</span>
                  <span className="vol">Vol</span>
                  <span className="buy">▲ BUY</span>
                  <span className="sell">▼ SELL</span>
                </div>

                <div className="mt-day-ind-guide">
                  <h4>How to read this (intraday)</h4>
                  <ul>
                    <li>
                      <strong>Candles</strong> — green = close ≥ open, red = close &lt; open (TradingView-style OHLC).
                    </li>
                    <li>
                      <strong>EMA9 / 20 / 50</strong> — short stack. Bullish when 9 &gt; 20 &gt; 50; longs prefer pullbacks to EMA9/20.
                    </li>
                    <li>
                      <strong>VWAP</strong> — session fair value. Bias long only above it; reclaim after dip is a classic entry.
                    </li>
                    <li>
                      <strong>OR H/L</strong> — first ~15 min high/low. Break + hold with rising volume = setup; chop inside OR = skip.
                    </li>
                    <li>
                      <strong>Bollinger</strong> — stretch meter. Tagging upper band without volume often means late chase.
                    </li>
                    <li>
                      <strong>Volume</strong> — confirm breakouts (want surge vs recent bars). Thin volume moves fade.
                    </li>
                    <li>
                      <strong>RSI</strong> — prefer 45–65 rising entries; avoid buying RSI &gt; 70. Coaching also uses ATR (stops) &amp; MACD hist.
                    </li>
                  </ul>
                </div>

                <div className="mt-table-wrap">
                  <table className="mt-table">
                    <thead>
                      <tr>
                        <th>Time</th>
                        <th>Side</th>
                        <th>Qty</th>
                        <th>Price</th>
                      </tr>
                    </thead>
                    <tbody>
                      {markers.map((m) => (
                        <tr key={`${m.order_id}-${m.time}`}>
                          <td>{shortTime(m.time)}</td>
                          <td className={m.side === 'BUY' ? 'up' : 'down'}>{m.side}</td>
                          <td>{m.quantity}</td>
                          <td>{m.price != null ? `₹${m.price.toLocaleString('en-IN')}` : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="mt-day-ai">
                <h3>{symbol} coaching</h3>
                {chartLoading && <p className="mt-loading">Building symbol coaching…</p>}
                {!chartLoading && ai?.summary && <p className="mt-day-ai-summary">{ai.summary}</p>}
                {!chartLoading && ai?.best_setup && (
                  <div className="mt-day-best-setup">
                    <h4>Best setup (VWAP · EMAs · OR · BB · RSI · ATR · Vol)</h4>
                    <p>{ai.best_setup}</p>
                  </div>
                )}
                <div className="mt-day-ai-grid">
                  <div>
                    <h4>Observations</h4>
                    <ul>{(ai?.observations || []).map((t) => <li key={t}>{t}</li>)}</ul>
                  </div>
                  <div>
                    <h4>Mistakes</h4>
                    <ul>
                      {(ai?.mistakes || (chart && !chartLoading ? ['None flagged'] : [])).map((t) => (
                        <li key={t}>{t}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <h4>What could have been done</h4>
                    <ul>
                      {(ai?.what_could_have_been_done || []).map((t) => (
                        <li key={t}>{t}</li>
                      ))}
                    </ul>
                  </div>
                </div>
                {ai?.engine && (
                  <p className="mt-day-ai-engine">
                    Engine: {ai.engine} · {symbol} only
                  </p>
                )}
              </section>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

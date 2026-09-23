import { useMemo } from 'react'

export type BrainCandle = {
  datetime?: string
  label?: string
  open: number
  high: number
  low: number
  close: number
  volume?: number
  ema9?: number | null
  ema20?: number | null
  mom15?: number | null
}

export type BrainFocusChart = {
  symbol?: string
  asof?: string
  candles?: BrainCandle[]
  orb_high?: number | null
  orb_low?: number | null
  orb_minutes?: number
  entry?: number | null
  sl?: number | null
  tp?: number | null
  side?: string | null
  score?: number | null
  strategy?: string | null
  reasons?: string[]
  last_close?: number | null
}

export type BrainActivity = {
  score_feed?: Array<{ symbol?: string; score: number; side?: string; strategy?: string }>
  histogram?: Array<{ bucket: string; count: number }>
  votes?: Array<{ strategy: string; count: number }>
  long_n?: number
  short_n?: number
  scanned_ok?: number
}

type Props = {
  focus?: BrainFocusChart | null
  activity?: BrainActivity | null
  mode?: string
}

export function PriceActionChart({ focus }: { focus: BrainFocusChart }) {
  const bars = focus.candles || []
  const layout = useMemo(() => {
    const w = 720
    const priceH = 220
    const volH = 48
    const momH = 56
    const gap = 8
    const pad = { t: 16, r: 54, b: 18, l: 48 }
    const h = priceH + gap + volH + gap + momH
    const plotW = w - pad.l - pad.r
    const n = Math.max(bars.length, 1)

    const highs = bars.map((b) => b.high)
    const lows = bars.map((b) => b.low)
    for (const v of [focus.orb_high, focus.orb_low, focus.entry, focus.sl, focus.tp]) {
      if (v != null && Number.isFinite(Number(v))) {
        highs.push(Number(v))
        lows.push(Number(v))
      }
    }
    const rawMax = Math.max(...highs, 1)
    const rawMin = Math.min(...lows, rawMax - 1)
    const padPx = (rawMax - rawMin) * 0.08 || 1
    const pMax = rawMax + padPx
    const pMin = rawMin - padPx
    const vMax = Math.max(...bars.map((b) => b.volume || 0), 1)
    const moms = bars.map((b) => b.mom15).filter((v): v is number => v != null && Number.isFinite(v))
    const mMax = Math.max(...moms.map(Math.abs), 0.5)

    const xAt = (i: number) => pad.l + ((i + 0.5) / n) * plotW
    const yAt = (p: number) => pad.t + ((pMax - p) / (pMax - pMin || 1)) * (priceH - 8)
    const yVol = (v: number) => pad.t + priceH + gap + volH - (v / vMax) * (volH - 4)
    const yMom = (m: number) => {
      const top = pad.t + priceH + gap + volH + gap
      return top + momH / 2 - (m / mMax) * ((momH - 8) / 2)
    }
    const candleW = Math.max(2, Math.min(8, (plotW / n) * 0.62))

    const emaPath = (key: 'ema9' | 'ema20') => {
      const pts: string[] = []
      bars.forEach((b, i) => {
        const v = b[key]
        if (v == null) return
        pts.push(`${pts.length ? 'L' : 'M'}${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`)
      })
      return pts.join(' ')
    }

    const momPath = () => {
      const pts: string[] = []
      bars.forEach((b, i) => {
        if (b.mom15 == null) return
        pts.push(`${pts.length ? 'L' : 'M'}${xAt(i).toFixed(1)},${yMom(b.mom15).toFixed(1)}`)
      })
      return pts.join(' ')
    }

    const levelLine = (price: number | null | undefined, color: string, label: string) => {
      if (price == null || !Number.isFinite(Number(price))) return null
      const y = yAt(Number(price))
      return { y, color, label, price: Number(price) }
    }

    return {
      w,
      h,
      pad,
      priceH,
      volH,
      momH,
      gap,
      xAt,
      yAt,
      yVol,
      yMom,
      candleW,
      ema9: emaPath('ema9'),
      ema20: emaPath('ema20'),
      mom: momPath(),
      levels: [
        levelLine(focus.orb_high, '#f59e0b', 'ORB H'),
        levelLine(focus.orb_low, '#f59e0b', 'ORB L'),
        levelLine(focus.entry, '#3b82f6', 'ENTRY'),
        levelLine(focus.sl, '#dc2626', 'SL'),
        levelLine(focus.tp, '#059669', 'TP'),
      ].filter(Boolean) as Array<{ y: number; color: string; label: string; price: number }>,
      momZeroY: pad.t + priceH + gap + volH + gap + momH / 2,
    }
  }, [bars, focus])

  if (!bars.length) {
    return <p className="jv-muted">No OHLC bars yet…</p>
  }

  return (
    <div className="jv-brain-chart">
      <div className="jv-brain-chart-head">
        <strong>
          {focus.symbol} · 1m OHLC
          {focus.side ? ` · ${focus.side}` : ''}
          {focus.score != null ? ` · score ${focus.score}` : ''}
        </strong>
        <span className="jv-muted">
          {focus.strategy || ''} · ORB {focus.orb_minutes || 15}m · {bars.length} bars
        </span>
      </div>
      <svg viewBox={`0 0 ${layout.w} ${layout.h}`} className="jv-brain-svg" role="img">
        {/* price pane */}
        {layout.levels.map((lv) => (
          <g key={lv.label}>
            <line
              x1={layout.pad.l}
              x2={layout.w - layout.pad.r}
              y1={lv.y}
              y2={lv.y}
              stroke={lv.color}
              strokeWidth={1}
              strokeDasharray="4 3"
              opacity={0.85}
            />
            <text x={layout.w - layout.pad.r + 4} y={lv.y + 3} fontSize="9" fill={lv.color}>
              {lv.label}
            </text>
          </g>
        ))}
        {layout.ema20 && <path d={layout.ema20} fill="none" stroke="#a855f7" strokeWidth={1.2} />}
        {layout.ema9 && <path d={layout.ema9} fill="none" stroke="#06b6d4" strokeWidth={1.2} />}
        {bars.map((b, i) => {
          const up = b.close >= b.open
          const color = up ? '#059669' : '#dc2626'
          const x = layout.xAt(i)
          const yHigh = layout.yAt(b.high)
          const yLow = layout.yAt(b.low)
          const yOpen = layout.yAt(b.open)
          const yClose = layout.yAt(b.close)
          const bodyTop = Math.min(yOpen, yClose)
          const bodyH = Math.max(1.5, Math.abs(yClose - yOpen))
          return (
            <g key={i}>
              <line x1={x} x2={x} y1={yHigh} y2={yLow} stroke={color} strokeWidth={1} />
              <rect
                x={x - layout.candleW / 2}
                y={bodyTop}
                width={layout.candleW}
                height={bodyH}
                fill={color}
              />
            </g>
          )
        })}
        {/* volume */}
        {bars.map((b, i) => {
          const up = b.close >= b.open
          const x = layout.xAt(i)
          const y0 = layout.pad.t + layout.priceH + layout.gap + layout.volH
          const y1 = layout.yVol(b.volume || 0)
          return (
            <rect
              key={`v-${i}`}
              x={x - layout.candleW / 2}
              y={y1}
              width={layout.candleW}
              height={Math.max(1, y0 - y1)}
              fill={up ? 'rgba(5,150,105,0.45)' : 'rgba(220,38,38,0.4)'}
            />
          )
        })}
        {/* momentum pane */}
        <line
          x1={layout.pad.l}
          x2={layout.w - layout.pad.r}
          y1={layout.momZeroY}
          y2={layout.momZeroY}
          stroke="#94a3b8"
          strokeWidth={1}
          strokeDasharray="2 2"
        />
        {layout.mom && <path d={layout.mom} fill="none" stroke="#2563eb" strokeWidth={1.5} />}
        <text x={layout.pad.l} y={layout.pad.t + layout.priceH + layout.gap + layout.volH + layout.gap + 10} fontSize="9" fill="#64748b">
          15m momentum % (brain ret15 path)
        </text>
        <text x={layout.pad.l} y={12} fontSize="9" fill="#06b6d4">
          EMA9
        </text>
        <text x={layout.pad.l + 36} y={12} fontSize="9" fill="#a855f7">
          EMA20
        </text>
      </svg>
      {!!(focus.reasons && focus.reasons.length) && (
        <p className="jv-brain-reasons">{focus.reasons.join(' · ')}</p>
      )}
    </div>
  )
}

function ScoreFeedChart({ activity }: { activity: BrainActivity }) {
  const feed = activity.score_feed || []
  const hist = activity.histogram || []
  const votes = activity.votes || []
  const w = 720
  const h = 120
  const pad = { t: 12, r: 12, b: 20, l: 28 }
  const plotW = w - pad.l - pad.r
  const plotH = h - pad.t - pad.b
  const n = Math.max(feed.length, 1)
  const maxScore = 100

  return (
    <div className="jv-brain-chart">
      <div className="jv-brain-chart-head">
        <strong>Brain score feed</strong>
        <span className="jv-muted">
          {activity.scanned_ok ?? feed.length} scored · L {activity.long_n ?? 0} / S {activity.short_n ?? 0}
        </span>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} className="jv-brain-svg">
        {feed.map((s, i) => {
          const x = pad.l + ((i + 0.5) / n) * plotW
          const barH = (s.score / maxScore) * plotH
          const y = pad.t + plotH - barH
          const color = s.side === 'SHORT' ? '#dc2626' : '#059669'
          return (
            <rect
              key={`${s.symbol}-${i}`}
              x={x - Math.max(1.5, plotW / n / 2.4)}
              y={y}
              width={Math.max(1.5, plotW / n / 1.2)}
              height={barH}
              fill={color}
              opacity={0.85}
            >
              <title>
                {s.symbol} {s.score} {s.side}
              </title>
            </rect>
          )
        })}
      </svg>
      <div className="jv-brain-meta-row">
        <div className="jv-hist">
          {hist.map((b) => (
            <div key={b.bucket} className="jv-hist-col" title={`${b.bucket}: ${b.count}`}>
              <div className="jv-hist-bar" style={{ height: `${Math.min(100, b.count * 8)}%` }} />
              <span>{b.bucket.split('-')[0]}</span>
            </div>
          ))}
        </div>
        <div className="jv-votes">
          {votes.map((v) => (
            <span key={v.strategy} className="jv-vote-chip">
              {v.strategy} · {v.count}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

export default function JarvisBrainCharts({ focus, activity }: Props) {
  return (
    <section className="jv-panel jv-brain-panel">
      <div className="jv-brain-grid">
        <div>{focus ? <PriceActionChart focus={focus} /> : <p className="jv-muted">Waiting for OHLC focus…</p>}</div>
        <div>{activity ? <ScoreFeedChart activity={activity} /> : <p className="jv-muted">Score feed fills during scan…</p>}</div>
      </div>
    </section>
  )
}

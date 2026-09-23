import { useMemo } from 'react'
import type { IntradaySetupChart as ChartPayload } from '../api/client'

type Props = {
  chart: ChartPayload
}

function num(v: unknown): number | null {
  if (v == null || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

export default function IntradaySetupChart({ chart }: Props) {
  const bars = chart.bars || []
  const levels = chart.levels || {}
  const callouts = chart.callouts || []

  const layout = useMemo(() => {
    const w = 720
    const priceH = 260
    const volH = 54
    const gap = 8
    const pad = { t: 18, r: 56, b: 22, l: 52 }
    const h = priceH + gap + volH
    const plotW = w - pad.l - pad.r
    const n = Math.max(bars.length, 1)

    const highs = bars.map((b) => b.high)
    const lows = bars.map((b) => b.low)
    for (const key of ['vwap', 'ema_9', 'ema_20', 'resistance', 'support', 'close'] as const) {
      const v = num(levels[key])
      if (v != null) {
        highs.push(v)
        lows.push(v)
      }
    }
    const rawMax = Math.max(...highs, 1)
    const rawMin = Math.min(...lows, rawMax - 1)
    const padPx = (rawMax - rawMin) * 0.08 || 1
    const pMax = rawMax + padPx
    const pMin = rawMin - padPx
    const vMax = Math.max(...bars.map((b) => b.volume || 0), 1)

    const xAt = (i: number) => pad.l + ((i + 0.5) / n) * plotW
    const yAt = (p: number) => pad.t + ((pMax - p) / (pMax - pMin || 1)) * (priceH - 8)
    const candleW = Math.max(2, Math.min(9, (plotW / n) * 0.62))

    const linePath = (key: 'vwap' | 'ema_9' | 'ema_20') => {
      const pts: string[] = []
      bars.forEach((b, i) => {
        const v = num(b[key])
        if (v == null) return
        pts.push(`${pts.length ? 'L' : 'M'}${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`)
      })
      return pts.join(' ')
    }

    const lateStart = bars.findIndex((b) => {
      const hh = Number(String(b.label || '').split(':')[0])
      return Number.isFinite(hh) && hh >= 14
    })

    const badgeAt = (price: number, preferRight = true) => {
      const y = yAt(price)
      const x = preferRight ? w - pad.r + 6 : pad.l - 6
      return { x, y }
    }

    const calloutPos = callouts.map((c) => {
      const last = bars[bars.length - 1]
      let price: number | null = null
      let x = xAt(bars.length - 1)
      let y = pad.t + priceH / 2

      if (c.kind === 'level' && c.level_key) {
        price = num(levels[c.level_key as keyof typeof levels])
      } else if (c.kind === 'ema_pair') {
        const a = num(levels.ema_9)
        const b = num(levels.ema_20)
        price = a != null && b != null ? (a + b) / 2 : a ?? b
      } else if (c.kind === 'last_price' || c.kind === 'day_path') {
        price = num(levels.close) ?? num(last?.close)
      } else if (c.kind === 'last_volume') {
        x = xAt(bars.length - 1)
        y = pad.t + priceH + gap + 8
        return { ...c, x, y, price: null as number | null }
      } else if (c.kind === 'late_zone' && lateStart >= 0) {
        x = xAt(Math.min(bars.length - 1, lateStart + Math.floor((bars.length - lateStart) / 2)))
        price = num(levels.close) ?? num(last?.close)
      }

      if (price != null) {
        const pos = badgeAt(price)
        return { ...c, x: pos.x, y: pos.y, price }
      }
      return { ...c, x, y, price }
    })

    return {
      w,
      h,
      pad,
      priceH,
      volH,
      gap,
      pMax,
      pMin,
      vMax,
      xAt,
      yAt,
      candleW,
      linePath,
      lateStart,
      calloutPos,
      yTicks: [pMax, (pMax + pMin) / 2, pMin],
    }
  }, [bars, levels, callouts])

  if (!bars.length) {
    return (
      <div className="idm-chart-empty" role="status">
        <p>{chart.message || 'No 5-minute bars for this setup chart.'}</p>
      </div>
    )
  }

  const {
    w,
    h,
    pad,
    priceH,
    volH,
    gap,
    pMax,
    pMin,
    vMax,
    xAt,
    yAt,
    candleW,
    linePath,
    lateStart,
    calloutPos,
    yTicks,
  } = layout

  const dirShort = chart.direction === 'short'
  const lateX = lateStart >= 0 ? xAt(lateStart) - candleW : null

  return (
    <div className="idm-chart">
      <div className="idm-chart-head">
        <div>
          <strong>Setup chart</strong>
          <span>
            {chart.interval || '5m'} · {chart.as_of || '—'}
            {chart.data_source ? ` · ${chart.data_source}` : ''}
          </span>
        </div>
        <div className="idm-chart-legend">
          <span className="lg-vwap">VWAP</span>
          <span className="lg-ema9">EMA9</span>
          <span className="lg-ema20">EMA20</span>
          {(num(levels.resistance) != null || num(levels.support) != null) && (
            <span className="lg-brk">{dirShort ? 'Support' : 'Resistance'}</span>
          )}
        </div>
      </div>

      <svg viewBox={`0 0 ${w} ${h}`} className="idm-chart-svg" role="img" aria-label={`${chart.symbol} setup chart`}>
        {/* late session zone */}
        {lateX != null && (
          <rect
            x={lateX}
            y={pad.t}
            width={w - pad.r - lateX}
            height={priceH - 4}
            className="idm-chart-late"
          />
        )}

        {/* grid + y labels */}
        {yTicks.map((p, i) => {
          const y = yAt(p)
          return (
            <g key={`yt-${i}`}>
              <line x1={pad.l} x2={w - pad.r} y1={y} y2={y} className="idm-chart-grid" />
              <text x={pad.l - 6} y={y + 3} textAnchor="end" className="idm-chart-axis">
                {p.toFixed(p >= 100 ? 1 : 2)}
              </text>
            </g>
          )
        })}

        {/* level lines */}
        {[
          { key: 'vwap', cls: 'idm-lvl-vwap' },
          { key: 'ema_9', cls: 'idm-lvl-ema9' },
          { key: 'ema_20', cls: 'idm-lvl-ema20' },
          { key: dirShort ? 'support' : 'resistance', cls: 'idm-lvl-brk' },
        ].map(({ key, cls }) => {
          const v = num(levels[key as keyof typeof levels])
          if (v == null) return null
          const y = yAt(v)
          return (
            <line
              key={key}
              x1={pad.l}
              x2={w - pad.r}
              y1={y}
              y2={y}
              className={cls}
            />
          )
        })}

        {/* continuous overlays */}
        <path d={linePath('vwap')} className="idm-path-vwap" fill="none" />
        <path d={linePath('ema_9')} className="idm-path-ema9" fill="none" />
        <path d={linePath('ema_20')} className="idm-path-ema20" fill="none" />

        {/* candles */}
        {bars.map((b, i) => {
          const x = xAt(i)
          const up = b.close >= b.open
          const yH = yAt(b.high)
          const yL = yAt(b.low)
          const yO = yAt(b.open)
          const yC = yAt(b.close)
          const top = Math.min(yO, yC)
          const body = Math.max(1.2, Math.abs(yC - yO))
          return (
            <g key={`c-${i}`} className={up ? 'idm-cndl up' : 'idm-cndl down'}>
              <line x1={x} x2={x} y1={yH} y2={yL} className="idm-cndl-wick" />
              <rect x={x - candleW / 2} y={top} width={candleW} height={body} className="idm-cndl-body" />
            </g>
          )
        })}

        {/* volume */}
        {bars.map((b, i) => {
          const x = xAt(i)
          const vh = ((b.volume || 0) / vMax) * (volH - 6)
          const y = pad.t + priceH + gap + (volH - vh)
          const up = b.close >= b.open
          return (
            <rect
              key={`v-${i}`}
              x={x - candleW / 2}
              y={y}
              width={candleW}
              height={Math.max(1, vh)}
              className={up ? 'idm-vol up' : 'idm-vol down'}
            />
          )
        })}

        {/* x labels */}
        {[0, Math.floor(bars.length / 2), bars.length - 1].map((i) => {
          if (i < 0 || i >= bars.length) return null
          return (
            <text key={`xl-${i}`} x={xAt(i)} y={h - 4} textAnchor="middle" className="idm-chart-axis">
              {bars[i].label}
            </text>
          )
        })}

        {/* numbered callout badges */}
        {calloutPos.map((c) => (
          <g key={`n-${c.n}`} className={c.passed ? 'idm-callout pass' : 'idm-callout fail'}>
            {c.price != null && (
              <line
                x1={w - pad.r}
                x2={c.x + 10}
                y1={yAt(c.price)}
                y2={c.y}
                className="idm-callout-lead"
              />
            )}
            <circle cx={c.x + 12} cy={c.y} r={9} />
            <text x={c.x + 12} y={c.y + 3.5} textAnchor="middle">
              {c.n}
            </text>
          </g>
        ))}

        {/* price range guard for empty scale */}
        {pMax === pMin && <text x={w / 2} y={h / 2} textAnchor="middle" className="idm-chart-axis">—</text>}
      </svg>

      {callouts.length > 0 && (
        <ol className="idm-chart-callouts">
          {callouts.map((c) => (
            <li key={c.check_id} className={c.passed ? 'pass' : 'fail'}>
              <span className="idm-callout-n">{c.n}</span>
              <div>
                <strong>{c.label}</strong>
                <p>{c.detail}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

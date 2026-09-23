type Point = { date: string; pnl: number }

type Props = {
  title: string
  data: Point[]
}

export function DailyPnlChart({ title, data }: Props) {
  if (!data.length) {
    return (
      <div className="mt-chart-card">
        <h3>{title}</h3>
        <p className="mt-empty">No daily data yet — sync Groww to build charts.</p>
      </div>
    )
  }

  const maxAbs = Math.max(...data.map((d) => Math.abs(d.pnl)), 1)
  const w = 100
  const barW = w / data.length

  return (
    <div className="mt-chart-card">
      <h3>{title}</h3>
      <svg viewBox={`0 0 ${w} 40`} className="mt-bar-chart" preserveAspectRatio="none">
        {data.map((d, i) => {
          const h = (Math.abs(d.pnl) / maxAbs) * 16
          const y = d.pnl >= 0 ? 20 - h : 20
          return (
            <rect
              key={d.date}
              x={i * barW + barW * 0.15}
              y={y}
              width={barW * 0.7}
              height={Math.max(h, 0.4)}
              className={d.pnl >= 0 ? 'bar-up' : 'bar-down'}
            >
              <title>{`${d.date}: ₹${d.pnl.toLocaleString('en-IN')}`}</title>
            </rect>
          )
        })}
        <line x1="0" y1="20" x2={w} y2="20" className="mt-chart-zero" />
      </svg>
      <div className="mt-chart-labels">
        <span>{data[0]?.date.slice(5)}</span>
        <span>{data[data.length - 1]?.date.slice(5)}</span>
      </div>
    </div>
  )
}

export function CumulativePnlChart({ title, data }: Props) {
  if (!data.length) {
    return (
      <div className="mt-chart-card">
        <h3>{title}</h3>
        <p className="mt-empty">No cumulative data yet.</p>
      </div>
    )
  }

  // With only 1 day, start from 0 so a line is still visible
  const series =
    data.length === 1
      ? [
          { date: data[0].date, pnl: 0 },
          { date: data[0].date, pnl: data[0].pnl },
        ]
      : data

  const values = series.map((d) => d.pnl)
  const latest = data[data.length - 1].pnl
  const min = Math.min(...values, 0)
  const max = Math.max(...values, 0)
  const pad = Math.max(Math.abs(max - min) * 0.15, 1)
  const lo = min - pad
  const hi = max + pad
  const range = hi - lo || 1
  const w = 100
  const h = 40

  const coords = series.map((d, i) => {
    const x = (i / Math.max(series.length - 1, 1)) * w
    const y = h - ((d.pnl - lo) / range) * (h - 8) - 4
    return { x, y, ...d }
  })
  const points = coords.map((c) => `${c.x},${c.y}`).join(' ')
  const areaPoints = `${points} ${w},${h} 0,${h}`
  const zeroY = h - ((0 - lo) / range) * (h - 8) - 4

  return (
    <div className="mt-chart-card">
      <h3>{title}</h3>
      <div className={`mt-cum-headline ${latest >= 0 ? 'up' : 'down'}`}>
        ₹{latest.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} className="mt-line-chart" preserveAspectRatio="none">
        <line x1="0" y1={zeroY} x2={w} y2={zeroY} className="mt-chart-zero" />
        <polygon points={areaPoints} className={latest >= 0 ? 'mt-cum-area up' : 'mt-cum-area down'} />
        <polyline points={points} className={`mt-cum-line ${latest >= 0 ? 'up' : 'down'}`} fill="none" />
        {coords
          .filter((_, i) => data.length > 1 || i === coords.length - 1)
          .map((c) => (
            <circle key={`${c.date}-${c.x}`} cx={c.x} cy={c.y} r="2.4" className="mt-cum-dot">
              <title>{`${c.date}: ₹${c.pnl.toLocaleString('en-IN')}`}</title>
            </circle>
          ))}
      </svg>
      <div className="mt-chart-footer">
        <span>{data[0]?.date.slice(5)}</span>
        <span className={latest >= 0 ? 'up' : 'down'}>
          Latest: ₹{latest.toLocaleString('en-IN')}
        </span>
        <span>{data[data.length - 1]?.date.slice(5)}</span>
      </div>
    </div>
  )
}

export function SymbolPnlChart({
  title,
  symbols,
}: {
  title: string
  symbols: Array<{ symbol: string; pnl: number }>
}) {
  if (!symbols.length) {
    return (
      <div className="mt-chart-card">
        <h3>{title}</h3>
        <p className="mt-empty">No symbol breakdown yet.</p>
      </div>
    )
  }

  const maxAbs = Math.max(...symbols.map((s) => Math.abs(s.pnl)), 1)

  return (
    <div className="mt-chart-card">
      <h3>{title}</h3>
      <ul className="mt-symbol-bars">
        {symbols.map((s) => (
          <li key={s.symbol}>
            <span className="mt-sym-name">{s.symbol}</span>
            <div className="mt-sym-track">
              <div
                className={`mt-sym-fill ${s.pnl >= 0 ? 'up' : 'down'}`}
                style={{ width: `${(Math.abs(s.pnl) / maxAbs) * 100}%` }}
              />
            </div>
            <span className={`mt-sym-val ${s.pnl >= 0 ? 'up' : 'down'}`}>
              ₹{s.pnl.toLocaleString('en-IN')}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function WinLossDonut({
  wins,
  losses,
}: {
  wins: number
  losses: number
}) {
  const total = wins + losses
  const winPct = total ? (wins / total) * 100 : 0
  const r = 16
  const c = 2 * Math.PI * r
  const winLen = (winPct / 100) * c

  return (
    <div className="mt-chart-card mt-donut-card">
      <h3>Win / loss days</h3>
      <div className="mt-donut-wrap">
        <svg viewBox="0 0 40 40" className="mt-donut">
          <circle cx="20" cy="20" r={r} className="mt-donut-bg" />
          <circle
            cx="20"
            cy="20"
            r={r}
            className="mt-donut-win"
            strokeDasharray={`${winLen} ${c - winLen}`}
            transform="rotate(-90 20 20)"
          />
        </svg>
        <div className="mt-donut-center">
          <strong>{total ? Math.round(winPct) : 0}%</strong>
          <span>green</span>
        </div>
      </div>
      <div className="mt-donut-legend">
        <span className="up">{wins} green</span>
        <span className="down">{losses} red</span>
      </div>
    </div>
  )
}

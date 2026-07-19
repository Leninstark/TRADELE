import type { IndexQuote } from '../types'

interface Props {
  indices: IndexQuote[]
  vix?: { value: number | null; level: string }
  pcr?: { value: number | null; signal: string }
  breadth?: { advance: number | null; decline: number | null }
}

function directionClass(direction: string) {
  if (direction === 'Bullish') return 'bullish'
  if (direction === 'Bearish') return 'bearish'
  return 'neutral'
}

export default function MarketOverview({ indices, vix, pcr, breadth }: Props) {
  return (
    <section className="panel market-overview">
      <h2>Market Overview</h2>
      <div className="index-grid">
        {indices.map((idx) => (
          <div key={idx.name} className={`index-card ${directionClass(idx.direction)}`}>
            <span className="index-name">{idx.name}</span>
            <span className={`index-direction ${directionClass(idx.direction)}`}>{idx.direction}</span>
            <span className="index-confidence">{idx.confidence}%</span>
            {idx.last != null && (
              <span className="index-price">
                {idx.last.toLocaleString('en-IN', { maximumFractionDigits: 2 })}
                <small className={idx.change_pct >= 0 ? 'up' : 'down'}>
                  {idx.change_pct >= 0 ? '+' : ''}
                  {idx.change_pct}%
                </small>
              </span>
            )}
          </div>
        ))}
      </div>
      <div className="market-meta">
        <div className="meta-item">
          <span>India VIX</span>
          <strong>{vix?.level ?? '—'}</strong>
        </div>
        <div className="meta-item">
          <span>PCR</span>
          <strong>{pcr?.value ?? pcr?.signal ?? '—'}</strong>
        </div>
        <div className="meta-item">
          <span>Market Breadth</span>
          <strong>
            {breadth?.advance != null && breadth?.decline != null
              ? `${breadth.advance} / ${breadth.decline}`
              : '—'}
          </strong>
        </div>
      </div>
    </section>
  )
}

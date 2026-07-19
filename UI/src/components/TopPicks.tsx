import type { ScanMatch } from '../types'

interface Props {
  title: string
  picks: ScanMatch[]
  max?: number
}

function stars(confidence: number) {
  const count = Math.min(5, Math.round(confidence / 20))
  return '★'.repeat(count) + '☆'.repeat(5 - count)
}

export default function TopPicks({ title, picks, max = 5 }: Props) {
  const items = picks.slice(0, max)

  return (
    <section className="panel top-picks">
      {title ? <h2>{title}</h2> : null}
      {items.length === 0 ? (
        <p className="empty">No matches yet. Connect Zerodha and run a scan.</p>
      ) : (
        <ol className="pick-list">
          {items.map((pick, i) => (
            <li key={`${pick.symbol}-${pick.strategy_id}`} className="pick-item">
              <div className="pick-rank">{i + 1}</div>
              <div className="pick-body">
                <div className="pick-header">
                  <strong>{pick.symbol}</strong>
                  <span className="stars">{stars(pick.confidence)}</span>
                  <span className="confidence">{pick.confidence}%</span>
                </div>
                <div className="pick-meta">
                  <span className={`rating ${pick.rating.toLowerCase().replace(' ', '-')}`}>{pick.rating}</span>
                  <span className="strategy">{pick.strategy_name}</span>
                </div>
                <ul className="reasons">
                  {pick.reasons.slice(0, 3).map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

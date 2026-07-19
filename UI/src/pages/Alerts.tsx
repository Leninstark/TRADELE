import { useEffect, useState } from 'react'
import { fetchLatestAlerts } from '../api/client'
import type { AlertItem } from '../types'

export default function Alerts() {
  const [alerts, setAlerts] = useState<{ long: AlertItem[]; short: AlertItem[] }>({ long: [], short: [] })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchLatestAlerts()
      .then(setAlerts)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="page-state">Loading alerts…</div>

  return (
    <div className="alerts-page">
      <header className="page-header">
        <h1>Alerts</h1>
        <p>Latest scan results from scheduled EOD and pre-market runs</p>
      </header>

      <div className="alerts-grid">
        <AlertColumn title="Top Long" items={alerts.long} direction="long" />
        <AlertColumn title="Top Short" items={alerts.short} direction="short" />
      </div>
    </div>
  )
}

function AlertColumn({
  title,
  items,
  direction,
}: {
  title: string
  items: AlertItem[]
  direction: 'long' | 'short'
}) {
  return (
    <section className={`panel alert-column ${direction}`}>
      <h2>{title}</h2>
      {items.length === 0 ? (
        <p className="empty">No alerts yet.</p>
      ) : (
        <ol>
          {items.map((a) => (
            <li key={`${a.symbol}-${a.rank}`}>
              <strong>{a.symbol}</strong>
              <span className="score">Score {a.score}</span>
              <ul>
                {a.reasons?.slice(0, 2).map((r, i) => (
                  <li key={i}>{r.reason}</li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

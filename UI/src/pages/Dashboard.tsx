import { useEffect, useState } from 'react'
import { fetchDashboard } from '../api/client'
import type { DashboardData } from '../types'
import MarketOverview from '../components/MarketOverview'
import TopPicks from '../components/TopPicks'
import ScannerPanel from '../components/ScannerPanel'

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchDashboard()
      .then(setData)
      .catch((e) => setError(e.message ?? 'Failed to load dashboard'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="page-state">Loading dashboard…</div>
  if (error) return <div className="page-state error">Error: {error}</div>
  if (!data) return null

  return (
    <div className="dashboard">
      <header className="page-header">
        <h1>Morning Dashboard</h1>
        <p>AI-ranked opportunities across intraday, swing, and positional styles</p>
      </header>

      <MarketOverview
        indices={data.market.indices}
        vix={data.market.india_vix}
        pcr={data.market.pcr}
        breadth={data.market.market_breadth}
      />

      <div className="dashboard-grid">
        <TopPicks title="Today's Top Swing" picks={data.top_swing} />
        <section className="panel portfolio-panel">
          <h2>Portfolio</h2>
          <div className="portfolio-stat">
            <span>Overall</span>
            <strong className={data.portfolio.overall_pnl_pct != null ? 'up' : ''}>
              {data.portfolio.overall_pnl_pct != null
                ? `${data.portfolio.overall_pnl_pct > 0 ? '+' : ''}${data.portfolio.overall_pnl_pct}%`
                : '—'}
            </strong>
          </div>
          <div className="portfolio-stat">
            <span>AI Rating</span>
            <strong>{data.portfolio.ai_rating}</strong>
          </div>
          <p className="hint">{data.portfolio.message}</p>
        </section>
      </div>

      <ScannerPanel
        title="Intraday Scanners"
        counts={data.intraday_scanners.counts}
        picks={data.intraday_scanners.top}
      />
    </div>
  )
}

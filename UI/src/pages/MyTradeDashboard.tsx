import { useEffect, useMemo, useState } from 'react'
import { fetchMyTradeDashboard, fetchMyTradeStatus, type MyTradeDashboardData } from '../api/client'
import { getAuthUser } from '../auth'
import KpiCard from '../components/KpiCard'
import {
  CumulativePnlChart,
  DailyPnlChart,
  SymbolPnlChart,
  WinLossDonut,
} from '../components/MyTradeCharts'
import {
  KPI_DEFS,
  KPI_SECTIONS,
  getKpiValue,
  type TradeStyle,
} from '../components/mytradeKpiHelp'

type Props = {
  refreshTick: number
  refreshError: string
  refreshNote: string
  refreshing: boolean
}

function fmtValue(format: string, value: number | null): string {
  if (value == null) {
    if (format === 'ratio') return '∞'
    return '—'
  }
  if (format === 'currency') {
    const sign = value >= 0 ? '+' : '−'
    return `${sign}₹${Math.abs(value).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
  }
  if (format === 'percent') return `${value.toFixed(1)}%`
  if (format === 'ratio') return value.toFixed(2)
  return value.toLocaleString('en-IN', { maximumFractionDigits: 1 })
}

function fmtOrderTime(iso: string | null | undefined, fallbackDate: string): string {
  if (!iso) return fallbackDate
  // Groww: 2026-08-13T09:15:22.47 or 2026-08-13T09:15:22
  const m = iso.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})/)
  if (m) return `${m[1]} ${m[2]}`
  return iso.replace('T', ' ').slice(0, 19)
}

export default function MyTradeDashboard({ refreshTick, refreshError, refreshNote, refreshing }: Props) {
  const username = getAuthUser()?.username || 'leninstark'
  const [style, setStyle] = useState<TradeStyle>('intraday')
  const [data, setData] = useState<MyTradeDashboardData | null>(null)
  const [status, setStatus] = useState<{ groww_connected: boolean; last_stored_date: string | null } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([fetchMyTradeDashboard(username), fetchMyTradeStatus(username)])
      .then(([dash, st]) => {
        if (cancelled) return
        setData(dash)
        setStatus(st)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load dashboard')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [username, refreshTick])

  const slice = data ? data[style] : null

  const filteredOrders = useMemo(() => {
    if (!data) return []
    return data.recent_orders.filter((o) => o.style === style)
  }, [data, style])

  if (loading && !data) {
    return <div className="mt-loading">Loading dashboard…</div>
  }

  return (
    <div className="mt-dashboard">
      <header className="mt-head">
        <div>
          <h1 className="mt-title">Performance dashboard</h1>
          <p className="mt-sub">
            {style === 'intraday' ? 'MIS intraday' : 'CNC / NRML swing'} metrics from Groww sync
            {status?.last_stored_date ? ` · last synced ${status.last_stored_date}` : ' · no data yet'}
          </p>
        </div>
        <div className="mt-style-toggle" role="group" aria-label="Trading style">
          <button
            type="button"
            className={`mt-style-btn${style === 'intraday' ? ' active' : ''}`}
            onClick={() => setStyle('intraday')}
          >
            Intraday
          </button>
          <button
            type="button"
            className={`mt-style-btn${style === 'swing' ? ' active' : ''}`}
            onClick={() => setStyle('swing')}
          >
            Swing
          </button>
        </div>
      </header>

      {!status?.groww_connected && (
        <p className="mt-banner warn">Connect Groww from the header, then click refresh.</p>
      )}
      {(refreshError || error) && <p className="mt-banner err">{refreshError || error}</p>}
      {refreshNote && <p className="mt-banner info">{refreshNote}</p>}
      {refreshing && <p className="mt-banner info">Syncing Groww data…</p>}

      {!slice ? (
        <p className="mt-empty">No data yet.</p>
      ) : (
        <>
          <div className="mt-hero-cards">
            <div className="mt-hero-card">
              <span className="mt-hero-label">Today</span>
              <span className={`mt-hero-value ${slice.pnl.today >= 0 ? 'up' : 'down'}`}>
                {fmtValue('currency', slice.pnl.today)}
              </span>
            </div>
            <div className="mt-hero-card">
              <span className="mt-hero-label">MTD</span>
              <span className={`mt-hero-value ${slice.pnl.mtd >= 0 ? 'up' : 'down'}`}>
                {fmtValue('currency', slice.pnl.mtd)}
              </span>
            </div>
            <div className="mt-hero-card">
              <span className="mt-hero-label">Total P&amp;L</span>
              <span className={`mt-hero-value ${slice.pnl.total >= 0 ? 'up' : 'down'}`}>
                {fmtValue('currency', slice.pnl.total)}
              </span>
            </div>
            <div className="mt-hero-card">
              <span className="mt-hero-label">Win rate</span>
              <span className="mt-hero-value">{fmtValue('percent', slice.quality.win_rate_pct)}</span>
            </div>
            <div className="mt-hero-card">
              <span className="mt-hero-label">Green days</span>
              <span className="mt-hero-value">{fmtValue('percent', slice.pnl.green_days_pct)}</span>
            </div>
          </div>

          <div className="mt-chart-grid">
            <DailyPnlChart title="Daily P&L (last 30 days)" data={slice.charts.daily_pnl} />
            <CumulativePnlChart title="Cumulative P&L" data={slice.charts.cumulative_pnl} />
            <SymbolPnlChart title="Top symbols by P&L" symbols={slice.concentration.top_symbols} />
            <WinLossDonut wins={slice.pnl.green_days} losses={slice.pnl.red_days} />
          </div>

          {KPI_SECTIONS.map((section) => {
            const defs = KPI_DEFS.filter((d) => d.section === section.key)
            return (
              <section key={section.key} className="mt-kpi-section">
                <h2>{section.title}</h2>
                <div className="mt-kpi-grid">
                  {defs.map((def) => {
                    const value = getKpiValue(slice, def.id)
                    const health = def.evaluate(value, style)
                    return (
                      <KpiCard
                        key={def.id}
                        def={def}
                        value={value}
                        health={health}
                        formatted={fmtValue(def.format, value)}
                        style={style}
                      />
                    )
                  })}
                </div>
              </section>
            )
          })}

          <section className="mt-section">
            <h2>Recent {style} orders</h2>
            {!filteredOrders.length ? (
              <p className="mt-empty">No {style} orders stored yet.</p>
            ) : (
              <div className="mt-table-wrap">
                <table className="mt-table">
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Side</th>
                      <th>Qty</th>
                      <th>Product</th>
                      <th>Status</th>
                      <th>Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredOrders.map((o) => (
                      <tr key={o.groww_order_id}>
                        <td><strong>{o.trading_symbol}</strong></td>
                        <td className={o.transaction_type === 'BUY' ? 'up' : 'down'}>{o.transaction_type}</td>
                        <td>{o.filled_quantity || o.quantity}</td>
                        <td>{o.product}</td>
                        <td>{o.order_status}</td>
                        <td className="mt-order-time">{fmtOrderTime(o.order_time, o.trade_date)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}

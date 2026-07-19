import { useEffect, useState } from 'react'
import { fetchLatestAlerts, fetchStrategies, runScanners } from '../api/client'
import type { ScanMatch, ScannerStrategy } from '../types'
import { StockRow, type StockCardItem } from '../components/StockCard'

type TradingStyle = 'intraday' | 'positional'

const PAGE_META: Record<TradingStyle, { title: string; subtitle: string }> = {
  intraday: {
    title: 'Intraday',
    subtitle: 'Monitor top intraday performers in real time',
  },
  positional: {
    title: 'Positional Trade',
    subtitle: '1–6 month setups — 200 EMA pullbacks, 52-week breakouts',
  },
}

function toCard(m: ScanMatch): StockCardItem {
  return {
    symbol: m.symbol,
    close: m.close,
    confidence: m.confidence,
    rating: m.rating,
    strategy_name: m.strategy_name,
    reasons: m.reasons,
  }
}

interface Props {
  style: TradingStyle
}

export default function TradingStylePage({ style }: Props) {
  const [strategies, setStrategies] = useState<ScannerStrategy[]>([])
  const [results, setResults] = useState<StockCardItem[]>([])
  const [loading, setLoading] = useState(true)
  const [alerts, setAlerts] = useState<{ long: StockCardItem[]; short: StockCardItem[] }>({
    long: [],
    short: [],
  })

  const meta = PAGE_META[style]

  useEffect(() => {
    setLoading(true)
    setResults([])

    const tasks: Promise<void>[] = [
      fetchStrategies(style).then(setStrategies),
      runScanners(style)
        .then((data) => setResults((data.top_picks ?? []).map(toCard)))
        .catch(() => setResults([])),
    ]

    if (style === 'intraday') {
      tasks.push(
        fetchLatestAlerts()
          .then((a) =>
            setAlerts({
              long: (a.long ?? []).map((x: { symbol: string; score: number; reasons?: { reason: string }[] }) => ({
                symbol: x.symbol,
                confidence: x.score,
                rating: 'Long',
                reasons: x.reasons?.map((r) => r.reason),
              })),
              short: (a.short ?? []).map((x: { symbol: string; score: number; reasons?: { reason: string }[] }) => ({
                symbol: x.symbol,
                confidence: x.score,
                rating: 'Short',
                reasons: x.reasons?.map((r) => r.reason),
              })),
            }),
          )
          .catch(() => setAlerts({ long: [], short: [] })),
      )
    }

    Promise.all(tasks).finally(() => setLoading(false))
  }, [style])

  return (
    <div className="explore-page">
      <header className="page-header">
        <h1>{meta.title}</h1>
        <p>{meta.subtitle}</p>
      </header>

      <section className="gw-section">
        <div className="gw-section-head">
          <h2>Strategies</h2>
        </div>
        <div className="strategy-chips">
          {strategies.map((s) => (
            <div key={s.id} className="strategy-chip">
              <strong>{s.name}</strong>
              <span>{s.description}</span>
            </div>
          ))}
          {strategies.length === 0 && !loading && (
            <p className="empty">No strategies configured. Check Admin.</p>
          )}
        </div>
      </section>

      <section className="gw-section">
        <div className="gw-section-head">
          <h2>Scanner results</h2>
        </div>
        {loading ? (
          <div className="gw-loading">
            <span className="gw-spinner" />
            Scanning…
          </div>
        ) : results.length === 0 ? (
          <div className="gw-empty">No matches yet. Connect Zerodha and run a scan.</div>
        ) : (
          <div className="gw-stock-list">
            {results.map((item) => (
              <StockRow key={`${item.symbol}-${item.strategy_name}`} item={item} />
            ))}
          </div>
        )}
      </section>

      {style === 'intraday' && (alerts.long.length > 0 || alerts.short.length > 0) && (
        <div className="alerts-grid">
          <section className="gw-section">
            <div className="gw-section-head">
              <h2>Top Long</h2>
            </div>
            <div className="gw-stock-list">
              {alerts.long.map((item) => (
                <StockRow key={`long-${item.symbol}`} item={item} />
              ))}
            </div>
          </section>
          <section className="gw-section">
            <div className="gw-section-head">
              <h2>Top Short</h2>
            </div>
            <div className="gw-stock-list">
              {alerts.short.map((item) => (
                <StockRow key={`short-${item.symbol}`} item={item} />
              ))}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

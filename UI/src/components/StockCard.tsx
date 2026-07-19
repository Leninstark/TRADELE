import { Link } from 'react-router-dom'

const LOGO_COLORS = [
  '#00b386', '#5367ff', '#eb5b3c', '#7b61ff', '#f5a623',
  '#00a8e8', '#e91e8c', '#2ecc71', '#9b59b6', '#e67e22',
]

function logoColor(symbol: string) {
  let hash = 0
  for (let i = 0; i < symbol.length; i++) hash = symbol.charCodeAt(i) + ((hash << 5) - hash)
  return LOGO_COLORS[Math.abs(hash) % LOGO_COLORS.length]
}

function initials(symbol: string) {
  return symbol.slice(0, 2).toUpperCase()
}

function formatPrice(n: number | null | undefined) {
  if (n == null) return '—'
  return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

export interface StockCardItem {
  symbol: string
  close?: number
  change_pct?: number
  confidence?: number
  rating?: string
  strategy_name?: string
  reasons?: string[]
}

interface CardProps {
  item: StockCardItem
  onClick?: () => void
}

export function StockCard({ item, onClick }: CardProps) {
  const pct = item.change_pct ?? (item.confidence != null ? item.confidence / 10 : undefined)
  const up = (pct ?? 0) >= 0

  return (
    <div className="gw-stock-card" onClick={onClick} role="button" tabIndex={0}>
      <div className="gw-stock-logo" style={{ background: logoColor(item.symbol) }}>
        {initials(item.symbol)}
      </div>
      <div>
        <div className="gw-stock-name">{item.symbol}</div>
        {item.strategy_name && <div className="gw-stock-meta">{item.strategy_name}</div>}
        {item.rating && !item.strategy_name && <div className="gw-stock-meta">{item.rating}</div>}
      </div>
      <div className="gw-stock-footer">
        <div className="gw-stock-price">{formatPrice(item.close)}</div>
        {pct != null && (
          <div className={`gw-stock-chg ${up ? 'up' : 'down'}`}>
            {item.change_pct != null
              ? `${up ? '+' : ''}${pct.toFixed(2)}%`
              : `Score ${item.confidence?.toFixed(0) ?? '—'}`}
          </div>
        )}
      </div>
    </div>
  )
}

interface RowProps {
  item: StockCardItem
  onClick?: () => void
}

export function StockRow({ item, onClick }: RowProps) {
  const pct = item.change_pct
  const up = (pct ?? 0) >= 0

  return (
    <div className="gw-stock-row" onClick={onClick} role="button" tabIndex={0}>
      <div className="gw-stock-logo" style={{ background: logoColor(item.symbol) }}>
        {initials(item.symbol)}
      </div>
      <div>
        <div className="gw-stock-name">{item.symbol}</div>
        <div className="gw-stock-meta">
          {item.strategy_name || item.rating || item.reasons?.[0] || '—'}
        </div>
      </div>
      <div className="right">
        <div className="price">{formatPrice(item.close)}</div>
        {pct != null ? (
          <div className={`chg ${up ? 'up' : 'down'}`}>
            {up ? '+' : ''}
            {pct.toFixed(2)}%
          </div>
        ) : item.confidence != null ? (
          <div className="chg up">Score {item.confidence.toFixed(0)}</div>
        ) : null}
      </div>
    </div>
  )
}

interface SectionProps {
  title: string
  items: StockCardItem[]
  seeAllTo?: string
  loading?: boolean
  emptyText?: string
}

export function StockSection({ title, items, seeAllTo, loading, emptyText }: SectionProps) {
  return (
    <section className="gw-section">
      <div className="gw-section-head">
        <h2>{title}</h2>
        {seeAllTo && (
          <Link className="gw-see-all" to={seeAllTo}>
            See all
          </Link>
        )}
      </div>
      {loading ? (
        <div className="gw-loading">
          <span className="gw-spinner" />
          Loading…
        </div>
      ) : items.length === 0 ? (
        <div className="gw-empty">{emptyText ?? 'No stocks yet. Connect Zerodha and run a scan.'}</div>
      ) : (
        <div className="gw-scroll-row">
          {items.map((item) => (
            <StockCard key={`${title}-${item.symbol}-${item.strategy_name ?? ''}`} item={item} />
          ))}
        </div>
      )}
    </section>
  )
}

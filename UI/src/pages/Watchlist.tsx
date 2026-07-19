export default function Watchlist() {
  return (
    <div className="explore-page">
      <header className="page-header">
        <h1>Watchlist</h1>
        <p>Track stocks you care about — add symbols from Explore and scanners</p>
      </header>

      <div className="gw-empty" style={{ padding: '48px 24px' }}>
        <p style={{ margin: '0 0 8px', fontWeight: 600, color: 'var(--gw-text-primary)' }}>
          Your watchlist is empty
        </p>
        <p style={{ margin: 0 }}>
          Save stocks from Explore, Swing, or Intraday to follow them here.
        </p>
      </div>
    </div>
  )
}

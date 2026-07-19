export default function Investments() {
  return (
    <div className="explore-page">
      <header className="page-header">
        <h1>Investment</h1>
        <p>Track returns on your stock holdings and view real-time P&amp;L</p>
      </header>

      <div className="gw-empty" style={{ padding: '48px 24px' }}>
        <p style={{ margin: '0 0 8px', fontWeight: 600, color: 'var(--gw-text-primary)' }}>
          No holdings yet
        </p>
        <p style={{ margin: 0 }}>
          Connect Zerodha holdings to import positions, track P&amp;L, and get AI hold / exit
          recommendations.
        </p>
      </div>

      <section className="gw-section">
        <div className="gw-section-head">
          <h2>Fundamental watchlist</h2>
        </div>
        <div className="strategy-chips">
          <div className="strategy-chip">
            <strong>High ROE + Growth</strong>
            <span>Quality compounders with strong fundamentals</span>
          </div>
          <div className="strategy-chip">
            <strong>Institutional Accumulation</strong>
            <span>FII/DII holding trends over quarters</span>
          </div>
          <div className="strategy-chip">
            <strong>52-Week Base</strong>
            <span>Long consolidation before breakout</span>
          </div>
        </div>
      </section>
    </div>
  )
}

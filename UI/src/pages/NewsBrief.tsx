import { useEffect, useState } from 'react'
import { fetchMarketBrief, runMarketBrief, type MarketBriefReport } from '../api/client'
import MarketBriefPanel from '../components/MarketBriefPanel'

export default function NewsBrief() {
  const [brief, setBrief] = useState<MarketBriefReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchMarketBrief()
      .then((res) => {
        if (!cancelled) setBrief(res)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load brief')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function onBuild() {
    setRunning(true)
    setError(null)
    try {
      // On-demand only; notifications deferred
      const res = await runMarketBrief('manual', false)
      setBrief(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to build News Brief')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="nb-page">
      <header className="nb-toolbar">
        <div>
          <h1>News Brief</h1>
          <p>
            Overnight / pre-open risk regime — global + India news → Nifty, Bank Nifty &amp; sector verdict.
            Scheduled ~11:00 PM and ~8:15 AM IST, or build on demand.
          </p>
        </div>
        <button type="button" className="btn primary" onClick={onBuild} disabled={running}>
          {running ? 'Building brief…' : 'Build brief now'}
        </button>
      </header>

      {error && (
        <div className="mn-error" role="alert">
          {error}
          <button type="button" onClick={() => setError(null)} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}

      <main className="nb-main">
        {(loading || running) && !brief?.ok && (
          <div className="mn-status">
            <span className="wl-spinner" />
            {running ? 'Harvesting headlines and synthesizing verdict…' : 'Loading last brief…'}
          </div>
        )}
        {!loading && !running && !brief?.ok && (
          <p className="mb-empty-copy nb-hint">
            {brief?.message ||
              'No brief yet. Click Build brief now, or wait for the night (~11:00 PM) / morning (~8:15 AM IST) job.'}
          </p>
        )}
        {brief?.ok && (
          <MarketBriefPanel brief={brief} loading={running} onRefresh={onBuild} showActions={false} />
        )}
      </main>
    </div>
  )
}

import { useEffect, useMemo, useState } from 'react'
import {
  fetchIntradaySetupChart,
  runTomorrowMomentumScan,
  type IntradayCandidate,
  type IntradaySetupChart as SetupChartPayload,
  type TomorrowMomentumScan,
} from '../api/client'
import { getAuthUser } from '../auth'
import IntradaySetupChart from '../components/IntradaySetupChart'
import { exportIntradayMomentumPdf } from '../utils/exportPdf'

type TradingStyle = 'intraday' | 'positional'

const PAGE_META: Record<TradingStyle, { title: string; subtitle: string }> = {
  intraday: {
    title: 'Equity Intraday',
    subtitle: 'Late-session momentum → tomorrow’s Long / Short candidates',
  },
  positional: {
    title: 'F&O',
    subtitle: 'Futures & Options — premiums, OI, and expiry setups',
  },
}

interface Props {
  style: TradingStyle
}

function byConviction(a: IntradayCandidate, b: IntradayCandidate) {
  const c = (b.conviction || 0) - (a.conviction || 0)
  if (c !== 0) return c
  return (Number(b.score) || 0) - (Number(a.score) || 0)
}

function fmt(n: number | null | undefined, d = 2) {
  if (n == null || Number.isNaN(n)) return '—'
  return Number(n).toLocaleString('en-IN', { maximumFractionDigits: d })
}

function CandidateCard({
  c,
  active,
  onSelect,
}: {
  c: IntradayCandidate
  active: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      className={`idm-card ${c.direction === 'long' ? 'is-long' : 'is-short'} ${active ? 'is-active' : ''}`}
      onClick={onSelect}
    >
      <div className="idm-card-top">
        <span className="idm-sym">{c.symbol}</span>
        <span className="idm-conv">{c.conviction}%</span>
      </div>
      <div className="idm-card-meta">
        <span className={c.can_trade_tomorrow ? 'idm-yes' : 'idm-wait'}>
          {c.can_trade_tomorrow ? 'Ready tomorrow' : 'Needs confirmation'}
        </span>
        <span>
          {c.checks_passed}/{c.checks_total} checks
        </span>
      </div>
      <p className="idm-card-snip">{c.reasons.slice(0, 2).join(' · ') || 'Partial setup'}</p>
    </button>
  )
}

function ConvictionPanel({
  c,
  asOf,
}: {
  c: IntradayCandidate
  asOf?: string | null
}) {
  const m = c.metrics || {}
  const [chart, setChart] = useState<SetupChartPayload | null>(null)
  const [chartLoading, setChartLoading] = useState(false)
  const [chartError, setChartError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const user = getAuthUser()
    setChart(null)
    setChartError(null)
    setChartLoading(true)
    fetchIntradaySetupChart({
      symbol: c.symbol,
      direction: c.direction,
      username: user?.username || 'leninstark',
      as_of: asOf || undefined,
    })
      .then((data) => {
        if (cancelled) return
        if (data.error && !(data.bars || []).length) {
          setChartError(data.message || data.error)
          setChart(data)
          return
        }
        setChart(data)
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setChartError(e instanceof Error ? e.message : 'Failed to load chart')
      })
      .finally(() => {
        if (!cancelled) setChartLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [c.symbol, c.direction, asOf])

  const calloutByCheck = useMemo(() => {
    const map = new Map<string, number>()
    for (const co of chart?.callouts || []) map.set(co.check_id, co.n)
    return map
  }, [chart?.callouts])

  return (
    <div className="idm-detail">
      <header className="idm-detail-head">
        <div>
          <h2>
            {c.symbol}{' '}
            <span className={c.direction === 'long' ? 'idm-pill long' : 'idm-pill short'}>
              {c.direction.toUpperCase()}
            </span>
          </h2>
          <p className="idm-verdict">{c.verdict}</p>
        </div>
        <div className={`idm-score ${c.can_trade_tomorrow ? 'ok' : ''}`}>
          <strong>{c.conviction}</strong>
          <span>conviction</span>
        </div>
      </header>

      <p className="idm-narrative">{c.narrative}</p>
      <p className="idm-plan">{c.plan}</p>

      <div className="idm-metrics">
        <div>
          <span>Close</span>
          <strong>{fmt(m.close as number | undefined)}</strong>
        </div>
        <div>
          <span>VWAP</span>
          <strong>{fmt(m.vwap as number | undefined)}</strong>
        </div>
        <div>
          <span>EMA9 / 20</span>
          <strong>
            {fmt(m.ema_9 as number | undefined)} / {fmt(m.ema_20 as number | undefined)}
          </strong>
        </div>
        <div>
          <span>RCI</span>
          <strong>{fmt(m.rci as number | undefined, 3)}</strong>
        </div>
        <div>
          <span>Vol ratio</span>
          <strong>{fmt(m.volume_ratio as number | undefined)}×</strong>
        </div>
        <div>
          <span>Day %</span>
          <strong>{fmt(m.day_return_pct as number | undefined)}%</strong>
        </div>
      </div>

      <section className="idm-section idm-chart-section">
        <h3>Chart — points on the session</h3>
        {chartLoading && <p className="idm-chart-status">Loading 5m setup chart…</p>}
        {!chartLoading && chartError && !(chart?.bars || []).length && (
          <p className="idm-chart-status err">{chartError}</p>
        )}
        {!chartLoading && chart && (chart.bars || []).length > 0 && (
          <IntradaySetupChart chart={chart} />
        )}
      </section>

      <section className="idm-section">
        <h3>Checklist — why this name</h3>
        <ul className="idm-checks">
          {(c.checks || []).map((ch) => {
            const n = calloutByCheck.get(ch.id)
            return (
              <li key={ch.id} className={ch.passed ? 'pass' : 'fail'}>
                {n != null ? (
                  <span className="idm-mark idm-mark-n">{n}</span>
                ) : (
                  <span className="idm-mark">{ch.passed ? '✓' : '✗'}</span>
                )}
                <div>
                  <strong>{ch.label}</strong>
                  <p>{ch.detail}</p>
                </div>
              </li>
            )
          })}
        </ul>
      </section>

      {(c.news?.headlines?.length || 0) > 0 && (
        <section className="idm-section">
          <h3>News</h3>
          <ul className="idm-news">
            {c.news!.headlines.map((h, i) => (
              <li key={`${h.title}-${i}`}>
                <a href={h.link} target="_blank" rel="noreferrer">
                  {h.title}
                </a>
                <span>
                  {h.source}
                  {h.published ? ` · ${h.published.slice(0, 10)}` : ''}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="idm-section idm-ext">
        <h3>External checks</h3>
        <p>
          <strong>NSE:</strong> {(c.nse?.notes || []).join(' · ') || '—'}
        </p>
        <p>
          <strong>Yahoo:</strong> {(c.yahoo?.notes || []).join(' · ') || '—'}
        </p>
        {c.data_source && (
          <p className="idm-src">
            Bars: <code>{c.data_source}</code>
          </p>
        )}
      </section>
    </div>
  )
}

function IntradayMomentumPage() {
  const [scan, setScan] = useState<TomorrowMomentumScan | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)

  const longs = useMemo(
    () => [...(scan?.longs || [])].sort(byConviction),
    [scan?.longs],
  )
  const shorts = useMemo(
    () => [...(scan?.shorts || [])].sort(byConviction),
    [scan?.shorts],
  )

  const selected: IntradayCandidate | null = (() => {
    if (!selectedKey) return null
    const [dir, sym] = selectedKey.split(':')
    const list = dir === 'short' ? shorts : longs
    return list.find((c) => c.symbol === sym) || null
  })()

  async function onScan(forceRefresh = false) {
    setLoading(true)
    setError(null)
    try {
      const user = getAuthUser()
      const data = await runTomorrowMomentumScan({
        username: user?.username || 'leninstark',
        top_n: 3,
        max_symbols: 40,
        force_refresh: forceRefresh,
      })
      if (data.error && !data.longs?.length && !data.shorts?.length) {
        setError(data.message || data.error)
        setScan(data)
        setSelectedKey(null)
        return
      }
      const sortedLongs = [...(data.longs || [])].sort(byConviction)
      const sortedShorts = [...(data.shorts || [])].sort(byConviction)
      setScan({ ...data, longs: sortedLongs, shorts: sortedShorts })
      const first = sortedLongs[0] || sortedShorts[0]
      setSelectedKey(first ? `${first.direction}:${first.symbol}` : null)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Scan failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  function onDownloadPdf() {
    if (!scan) return
    exportIntradayMomentumPdf({
      ...scan,
      longs,
      shorts,
    })
  }

  return (
    <div className="explore-page idm-page">
      <header className="page-header idm-header">
        <div>
          <h1>{PAGE_META.intraday.title}</h1>
          <p>{PAGE_META.intraday.subtitle}</p>
        </div>
        <div className="idm-header-actions">
          {scan && !loading && (
            <button type="button" className="btn secondary" onClick={onDownloadPdf}>
              Download PDF
            </button>
          )}
          {scan && !loading && (
            <button
              type="button"
              className="btn secondary"
              onClick={() => onScan(true)}
              title="Recompute and overwrite today's saved conviction"
            >
              Rescan
            </button>
          )}
          <button type="button" className="btn primary" onClick={() => onScan(false)} disabled={loading}>
            {loading ? 'Loading…' : 'Load / Scan'}
          </button>
        </div>
      </header>

      {!scan && !loading && !error && (
        <div className="page-state idm-blank">
          Blank until you scan. No API calls on open.
          <br />
          Looks for compression → volume expansion → breakout with VWAP / EMA / RCI —
          then News + Yahoo + NSE checks for Top 3 Long & Top 3 Short.
        </div>
      )}

      {loading && <div className="page-state">Scanning movers (Zerodha → Groww)… this can take a minute.</div>}
      {error && <div className="page-state error">{error}</div>}

      {scan && !loading && (
        <>
          <div className="idm-meta-row">
            <span>As of {scan.as_of}</span>
            <span>
              Prefill {scan.prefiltered ?? 0} · Scanned {scan.scanned ?? 0}
            </span>
            {scan.sources?.length ? <span>Sources: {scan.sources.join(', ')}</span> : null}
            {scan.rate_limited ? <span className="idm-warn">Rate-limited mid-run</span> : null}
            {scan.saved && scan.run_id ? (
              <span className="idm-yes">
                {scan.from_cache ? 'Saved day cache' : 'Saved'} · run #{scan.run_id}
              </span>
            ) : scan.saved === false ? (
              <span className="idm-warn">Not saved</span>
            ) : null}
          </div>
          {scan.message && <p className="idm-banner">{scan.message}</p>}

          <div className="idm-layout">
            <aside className="idm-rail">
              <div className="idm-rail-block">
                <h3>Top 3 Long</h3>
                {longs.length === 0 && <p className="idm-empty">No long setups</p>}
                {longs.map((c) => (
                  <CandidateCard
                    key={`long-${c.symbol}`}
                    c={c}
                    active={selectedKey === `long:${c.symbol}`}
                    onSelect={() => setSelectedKey(`long:${c.symbol}`)}
                  />
                ))}
              </div>
              <div className="idm-rail-block">
                <h3>Top 3 Short</h3>
                {shorts.length === 0 && <p className="idm-empty">No short setups</p>}
                {shorts.map((c) => (
                  <CandidateCard
                    key={`short-${c.symbol}`}
                    c={c}
                    active={selectedKey === `short:${c.symbol}`}
                    onSelect={() => setSelectedKey(`short:${c.symbol}`)}
                  />
                ))}
              </div>
            </aside>
            <main className="idm-main">
              {selected ? (
                <ConvictionPanel c={selected} asOf={scan?.as_of} />
              ) : (
                <div className="page-state">Select a candidate for full conviction.</div>
              )}
            </main>
          </div>
        </>
      )}
    </div>
  )
}

/** Trade Assist style pages — positional blank; intraday is on-demand scan only. */
export default function TradingStylePage({ style }: Props) {
  if (style === 'intraday') {
    return <IntradayMomentumPage />
  }

  const meta = PAGE_META[style]
  return (
    <div className="explore-page">
      <header className="page-header">
        <h1>{meta.title}</h1>
        <p>{meta.subtitle}</p>
      </header>
    </div>
  )
}

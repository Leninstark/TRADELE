import { useCallback, useEffect, useState } from 'react'
import Box from '@mui/material/Box'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import {
  fetchSwingResults,
  runSwingScan,
  type SwingScanResult,
  type SwingStock,
  type SwingTabId,
} from '../api/client'
import SwingDataGrid from '../components/SwingDataGrid'
import { getSwingColumns } from '../components/swingColumns'
import { TAB_HELP } from '../components/swingTabHelp'
import { exportSwingToExcel } from '../utils/exportExcel'

interface SwingTab {
  id: SwingTabId
  label: string
  filterTitle: string
  conditions: string[]
}

const SWING_TABS: SwingTab[] = [
  {
    id: 'dashboard',
    label: 'Dashboard',
    filterTitle: 'Dashboard',
    conditions: [
      'Full metrics for Universe stocks',
      'Zerodha: LTP, Change %, Company',
      'Calculated: Returns, RSI, ADX, EMAs, Breakout, Rel Strength',
      'AI trade levels for top picks',
      'Scan: Universe → all filter tabs → Stock Score → Dashboard',
    ],
  },
  {
    id: 'stock_score',
    label: 'Stock Score',
    filterTitle: 'Stock Score weights',
    conditions: [
      'Recalculates from saved DB data (no live fetch)',
      'Price Momentum — 20, Volume — 15, Delivery — 15',
      'Relative Strength — 10, EMA Alignment — 10',
      'RSI — 5, ADX — 5, Breakout — 10',
      'Sector Strength — 5, News — 5',
      'Weights adjust to available data only',
    ],
  },
  {
    id: 'universe',
    label: 'Universe',
    filterTitle: 'Universe filters',
    conditions: [
      'Mid cap & Small cap only',
      'Price > ₹100',
      'Market Cap > ₹3,000 Cr',
      'Avg Daily Volume > 5 lakh shares',
      'Delivery % > 35%',
      'Circuit stocks excluded',
    ],
  },
  {
    id: 'price_momentum',
    label: 'Price Momentum',
    filterTitle: 'Price Momentum filters',
    conditions: [
      '5 Day Return > 5%',
      '10 Day Return > 8%',
      '20 Day Return > 15%',
      'Current Price above 20 EMA',
      'Current Price above 50 EMA',
      'Close near 52 Week High (<10% away)',
      'Runs on Universe scan symbols',
    ],
  },
  {
    id: 'volume_explosion',
    label: 'Volume Explosion',
    filterTitle: 'Volume Explosion filters',
    conditions: [
      "Today's Volume / 20 Day Avg Volume > 2x",
      '3x volume flagged as strong',
      '5 Day Avg Volume > 20 Day Avg Volume',
      'Runs on Universe scan symbols',
    ],
  },
  {
    id: 'institutional_buying',
    label: 'Institutional Buying',
    filterTitle: 'Institutional Buying filters',
    conditions: [
      'Delivery % > 40% (NSE bhavcopy)',
      'Chaikin Money Flow (CMF) > 0',
      'Price above 20 EMA',
      'Volume ratio > 1.2x',
      'FII / MF / Promoter / OI: NSE feeds pending',
    ],
  },
  {
    id: 'news_sentiment',
    label: 'News Sentiment',
    filterTitle: 'News Sentiment',
    conditions: [
      'Moneycontrol, Economic Times, Business Standard, Livemint',
      'Results, bulk/block deals, policy (via headlines)',
      'LLM score: Positive / Neutral / Negative',
      'Runs on Universe scan symbols',
    ],
  },
  {
    id: 'delivery_percentage',
    label: 'Delivery Percentage',
    filterTitle: 'Delivery Percentage filters',
    conditions: [
      'Today delivery % > yesterday',
      'Today volume > yesterday (bullish accumulation)',
      'Delivery % today ≥ 35%',
      'Relative Strength: Stock 20D % − Nifty 20D % ≥ 5%',
      'Perfect trend: Price > EMA20 > EMA50 > EMA200',
      'Runs on Universe scan symbols',
    ],
  },
  {
    id: 'sector_strength',
    label: 'Sector Strength',
    filterTitle: 'Sector Strength filters',
    conditions: [
      'Sector 10-day return from Industry grouping',
      'Only stocks in top-performing sectors',
      'Avoid best stock in worst sector',
      'Runs on Universe scan symbols',
    ],
  },
]

function FilterTooltip({ title, conditions }: { title: string; conditions: string[] }) {
  return (
    <Box sx={{ p: 0.5, maxWidth: 280 }}>
      <Typography variant="subtitle2" sx={{ mb: 0.75, fontWeight: 700 }}>
        {title}
      </Typography>
      <Typography variant="body2" component="div" sx={{ lineHeight: 1.7 }}>
        {conditions.map((c) => (
          <span key={c}>
            {c}
            <br />
          </span>
        ))}
      </Typography>
    </Box>
  )
}

function TabHelpTooltip({ tabId }: { tabId: SwingTabId }) {
  const help = TAB_HELP[tabId]
  return (
    <Box sx={{ p: 0.5, maxWidth: 320 }}>
      <Typography variant="subtitle2" sx={{ mb: 0.75, fontWeight: 700 }}>
        {help.summary}
      </Typography>
      {help.metrics.map((m) => (
        <Typography key={m.term} variant="body2" sx={{ mb: 0.5, lineHeight: 1.55 }}>
          <Box component="span" sx={{ fontWeight: 600 }}>
            {m.term}:
          </Box>{' '}
          {m.meaning}
        </Typography>
      ))}
    </Box>
  )
}

function ScanIcon({ spinning }: { spinning?: boolean }) {
  return (
    <svg
      className={`swing-scan-icon${spinning ? ' spinning' : ''}`}
      viewBox="0 0 24 24"
      width="16"
      height="16"
      aria-hidden
    >
      <path
        fill="currentColor"
        d="M12 2a10 10 0 0 0-7.35 16.76l1.42-1.42A8 8 0 1 1 12 20v2A10 10 0 0 0 12 2zm-1 5v5.17l3.59 2.08.71-1.22-2.8-1.62V7H11z"
      />
    </svg>
  )
}

export default function Swing() {
  const [activeTab, setActiveTab] = useState<SwingTabId>('dashboard')
  const [stocks, setStocks] = useState<SwingStock[]>([])
  const [meta, setMeta] = useState<Record<string, unknown>>({})
  const [runInfo, setRunInfo] = useState<SwingScanResult['run']>(null)
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [scanStatus, setScanStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const applyPayload = useCallback((data: SwingScanResult) => {
    const err = data.meta?.error
    if (err === 'not_connected' || err === 'no_universe' || err === 'nse_data' || err === 'refresh_failed') {
      setError(String(data.meta.message ?? 'Scan unavailable.'))
      setStocks([])
      setMeta(data.meta ?? {})
      setRunInfo(data.run ?? null)
      return
    }
    setError(null)
    setStocks(data.stocks ?? [])
    setMeta(data.meta ?? {})
    setRunInfo(data.run ?? null)
  }, [])

  const loadResults = useCallback(async (tab: SwingTabId) => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchSwingResults(tab)
      applyPayload(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load results')
      setStocks([])
    } finally {
      setLoading(false)
    }
  }, [applyPayload])

  useEffect(() => {
    loadResults(activeTab)
  }, [activeTab, loadResults])

  async function handleScan(tab: SwingTab) {
    setScanning(true)
    setError(null)
    if (tab.id === 'dashboard') {
      setScanStatus('Running Universe, then all tabs, Stock Score, and Dashboard…')
    } else if (tab.id === 'stock_score') {
      setScanStatus('Calculating scores from saved DB data…')
    } else {
      setScanStatus(null)
    }
    try {
      const data = await runSwingScan(tab.id)
      applyPayload(data)
      if (tab.id === 'dashboard' && data.meta?.refresh_status) {
        const steps = data.meta.refresh_steps as Record<string, unknown> | undefined
        const stepCount = steps ? Object.keys(steps).length : 0
        const failed = data.meta.failed_steps as string[] | undefined
        setScanStatus(
          `Updated ${stepCount} steps${failed?.length ? ` (${failed.length} warnings)` : ''}`,
        )
      } else if (tab.id === 'stock_score') {
        setScanStatus(`Scored ${data.stocks?.length ?? 0} stocks from DB`)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Scan failed')
      setScanStatus(null)
    } finally {
      setScanning(false)
    }
  }

  const columns = getSwingColumns(activeTab)
  const busy = loading || scanning

  const activeTabLabel =
    SWING_TABS.find((t) => t.id === activeTab)?.label ?? 'Swing'

  function handleExportExcel() {
    if (stocks.length === 0) return
    const stamp = new Date().toISOString().slice(0, 10)
    exportSwingToExcel(
      columns,
      stocks,
      activeTabLabel,
      `${activeTab}_${stamp}.xlsx`,
    )
  }

  return (
    <div className="swing-page">
      <header className="swing-page-header">
        <h1>Swing Trade</h1>
        <button
          type="button"
          className="swing-export-btn"
          onClick={handleExportExcel}
          disabled={stocks.length === 0 || busy}
          title="Export the current table to an Excel (.xlsx) file"
        >
          Export to Excel
        </button>
      </header>

      {scanStatus && (
        <Typography variant="body2" sx={{ px: 2, pb: 1, color: '#00b386' }}>
          {scanStatus}
        </Typography>
      )}

      <div className="swing-tabs" role="tablist">
        {SWING_TABS.map((tab) => (
          <div
            key={tab.id}
            className={`swing-tab${activeTab === tab.id ? ' active' : ''}`}
            role="tab"
            aria-selected={activeTab === tab.id}
          >
            <Tooltip
              title={<TabHelpTooltip tabId={tab.id} />}
              placement="bottom"
              arrow
              enterDelay={400}
            >
              <button
                type="button"
                className="swing-tab-label"
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
              </button>
            </Tooltip>
            <Tooltip
              title={<FilterTooltip title={tab.filterTitle} conditions={tab.conditions} />}
              placement="bottom"
              arrow
              enterDelay={200}
            >
              <span className="swing-tab-scan-wrap">
                <button
                  type="button"
                  className="swing-tab-scan"
                  disabled={busy}
                  onClick={(e) => {
                    e.stopPropagation()
                    handleScan(tab)
                  }}
                >
                  <ScanIcon spinning={scanning && activeTab === tab.id} />
                </button>
              </span>
            </Tooltip>
          </div>
        ))}
      </div>

      <div className="swing-tab-panel" role="tabpanel">
        {error && <div className="page-state error swing-error">{error}</div>}

        {!error && !loading && stocks.length === 0 ? (
          <div className="gw-empty swing-empty">
            {activeTab === 'stock_score' ? (
              <>
                No scores yet. Run <strong>Universe</strong> (and other tabs if you want), then click the{' '}
                <strong>scan icon</strong> here to calculate from saved DB data.
              </>
            ) : activeTab === 'dashboard' ? (
              <>
                No dashboard data yet. Click the <strong>scan icon</strong> on the Dashboard tab to
                run Universe → all filters → Stock Score → Dashboard.
              </>
            ) : (
              <>
                No saved results yet. Hover the scan icon for filters, then click to run.
                {activeTab !== 'universe' && (
                  <>
                    <br />
                    <br />
                    Run <strong>Universe</strong> scan first if you have not already.
                  </>
                )}
              </>
            )}
          </div>
        ) : (
          (stocks.length > 0 || loading || scanning) && (
            <SwingDataGrid
              stocks={stocks}
              columns={columns}
              meta={meta}
              runFinishedAt={runInfo?.finished_at ?? null}
              loading={busy}
            />
          )
        )}
      </div>
    </div>
  )
}

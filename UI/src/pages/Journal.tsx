import { useEffect, useRef, useState } from 'react'
import {
  fetchMyTradeJournal,
  fetchTraderDna,
  runTraderDna,
  uploadJournalExcel,
  type MyTradeJournalData,
  type TraderDnaReport,
} from '../api/client'
import { getAuthUser } from '../auth'
import TraderDnaReportView from '../components/TraderDnaReport'

type Props = {
  refreshTick: number
  refreshError: string
  refreshNote: string
}

type Tab = 'trades' | 'orders' | 'dna'

export default function Journal({ refreshTick, refreshError, refreshNote }: Props) {
  const username = getAuthUser()?.username || 'leninstark'
  const [tab, setTab] = useState<Tab>('trades')
  const [data, setData] = useState<MyTradeJournalData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [dna, setDna] = useState<TraderDnaReport | null>(null)
  const [dnaLoading, setDnaLoading] = useState(false)
  const [uploadNote, setUploadNote] = useState('')
  const fileRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    fetchMyTradeJournal(username)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load journal')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [username, refreshTick])

  useEffect(() => {
    let cancelled = false
    fetchTraderDna(username)
      .then((res) => {
        if (!cancelled && res.ok) setDna(res)
      })
      .catch(() => {
        /* no report yet */
      })
    return () => {
      cancelled = true
    }
  }, [username, refreshTick])

  async function onUpload(file: File | null) {
    if (!file) return
    setUploadNote('')
    setError('')
    try {
      const res = await uploadJournalExcel(username, file)
      setUploadNote(
        `Upload: +${res.added ?? 0} new · ${res.skipped_before_cutoff ?? 0} before cutoff · ${res.duplicates ?? 0} dupes · total fills ${res.fills_total ?? 0}`,
      )
      setTab('dna')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function onRunDna(force: boolean) {
    setDnaLoading(true)
    setError('')
    setUploadNote('')
    try {
      const res = await runTraderDna(username, force)
      setDna(res)
      setTab('dna')
      if (res.from_cache) {
        setUploadNote(res.message || 'Loaded cached Trader DNA (no new fills).')
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Trader DNA failed')
    } finally {
      setDnaLoading(false)
    }
  }

  return (
    <div className="mt-journal">
      <header className="mt-head">
        <div>
          <h1 className="mt-title">Journal</h1>
          <p className="mt-sub">
            Groww fills, Excel upload, and Trader DNA audit. Re-uploads only add trades after your last saved fill.
          </p>
        </div>
        <div className="mt-journal-actions">
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            className="dna-file-input"
            onChange={(e) => onUpload(e.target.files?.[0] || null)}
          />
          <button type="button" className="mt-style-btn" onClick={() => fileRef.current?.click()}>
            Upload Excel / CSV
          </button>
          <button
            type="button"
            className="mt-style-btn active"
            disabled={dnaLoading}
            onClick={() => onRunDna(false)}
          >
            {dnaLoading ? 'Running…' : 'Run Trader DNA'}
          </button>
          {dna?.ok && (
            <button type="button" className="mt-style-btn" disabled={dnaLoading} onClick={() => onRunDna(true)}>
              Force rebuild
            </button>
          )}
        </div>
      </header>

      <div className="mt-tabs">
        <button
          type="button"
          className={`mt-tab${tab === 'trades' ? ' active' : ''}`}
          onClick={() => setTab('trades')}
        >
          Trades ({data?.trades.length ?? 0})
        </button>
        <button
          type="button"
          className={`mt-tab${tab === 'orders' ? ' active' : ''}`}
          onClick={() => setTab('orders')}
        >
          Orders ({data?.orders.length ?? 0})
        </button>
        <button
          type="button"
          className={`mt-tab${tab === 'dna' ? ' active' : ''}`}
          onClick={() => setTab('dna')}
        >
          Trader DNA
        </button>
      </div>

      {(refreshError || error) && <p className="mt-banner err">{refreshError || error}</p>}
      {refreshNote && <p className="mt-banner info">{refreshNote}</p>}
      {uploadNote && <p className="mt-banner info">{uploadNote}</p>}

      {tab === 'dna' ? (
        dnaLoading && !dna ? (
          <div className="mt-loading">Building Trader DNA (FIFO + stats + AI narrative)…</div>
        ) : dna?.ok && dna.stats ? (
          <TraderDnaReportView report={dna as Record<string, unknown>} />
        ) : (
          <div className="mt-empty dna-empty">
            <p>No Trader DNA report yet.</p>
            <p>
              Upload a full Groww/broker Excel or CSV (for history — Groww API alone is today-only), then click{' '}
              <strong>Run Trader DNA</strong>.
            </p>
          </div>
        )
      ) : loading && !data ? (
        <div className="mt-loading">Loading journal…</div>
      ) : tab === 'trades' ? (
        !data?.trades.length ? (
          <p className="mt-empty">No Groww trades yet. Sync Groww or upload Excel for DNA history.</p>
        ) : (
          <div className="mt-table-wrap">
            <table className="mt-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th>Qty</th>
                  <th>Price</th>
                  <th>Value</th>
                  <th>Segment</th>
                  <th>Product</th>
                </tr>
              </thead>
              <tbody>
                {data.trades.map((t) => (
                  <tr key={t.id}>
                    <td>{t.trade_date}</td>
                    <td>{t.trading_symbol}</td>
                    <td className={t.transaction_type === 'BUY' ? 'side-buy' : 'side-sell'}>
                      {t.transaction_type}
                    </td>
                    <td>{t.quantity}</td>
                    <td>₹{t.price.toLocaleString('en-IN')}</td>
                    <td>₹{t.value.toLocaleString('en-IN')}</td>
                    <td>{t.segment}</td>
                    <td>{t.product}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : !data?.orders.length ? (
        <p className="mt-empty">No orders yet. Sync Groww to populate the journal.</p>
      ) : (
        <div className="mt-table-wrap">
          <table className="mt-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Filled</th>
                <th>Status</th>
                <th>Type</th>
                <th>Segment</th>
              </tr>
            </thead>
            <tbody>
              {data.orders.map((o) => (
                <tr key={o.id}>
                  <td>{o.trade_date}</td>
                  <td>{o.trading_symbol}</td>
                  <td className={o.transaction_type === 'BUY' ? 'side-buy' : 'side-sell'}>
                    {o.transaction_type}
                  </td>
                  <td>{o.quantity}</td>
                  <td>{o.filled_quantity}</td>
                  <td>{o.order_status}</td>
                  <td>{o.order_type}</td>
                  <td>{o.segment}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

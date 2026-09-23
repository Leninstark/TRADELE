import { useEffect, useMemo, useState } from 'react'
import { fetchMyTradeCalendar, type MyTradeCalendarData } from '../api/client'
import { getAuthUser } from '../auth'
import DayReviewModal from '../components/DayReviewModal'

type Props = {
  refreshTick: number
  refreshError: string
  refreshNote: string
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function fmtPnl(n: number | null | undefined) {
  if (n == null) return '—'
  const sign = n >= 0 ? '+' : ''
  return `${sign}₹${Math.abs(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

function pnlClass(n: number | null | undefined) {
  if (n == null) return ''
  if (n > 0) return 'up'
  if (n < 0) return 'down'
  return 'flat'
}

export default function PLCalendar({ refreshTick, refreshError, refreshNote }: Props) {
  const username = getAuthUser()?.username || 'leninstark'
  const now = new Date()
  const [month, setMonth] = useState(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`,
  )
  const [data, setData] = useState<MyTradeCalendarData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedDate, setSelectedDate] = useState<string | null>(null)
  const [reviewStyle, setReviewStyle] = useState<'intraday' | 'swing' | 'fno'>('intraday')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    fetchMyTradeCalendar(username, month, reviewStyle)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load calendar')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [username, month, refreshTick, reviewStyle])

  const grid = useMemo(() => {
    if (!data?.days?.length) return []
    const [y, m] = month.split('-').map(Number)
    const firstWeekday = new Date(y, m - 1, 1).getDay()
    const offset = firstWeekday === 0 ? 6 : firstWeekday - 1
    const cells: (MyTradeCalendarData['days'][0] | null)[] = Array(offset).fill(null)
    cells.push(...data.days)
    while (cells.length % 7 !== 0) cells.push(null)
    return cells
  }, [data, month])

  const shiftMonth = (delta: number) => {
    const [y, m] = month.split('-').map(Number)
    const d = new Date(y, m - 1 + delta, 1)
    setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
  }

  const monthLabel = useMemo(() => {
    const [y, m] = month.split('-').map(Number)
    return new Date(y, m - 1, 1).toLocaleString('en-IN', { month: 'long', year: 'numeric' })
  }, [month])

  const styleHint =
    reviewStyle === 'intraday'
      ? 'Equity MIS (cash) realised P&L'
      : reviewStyle === 'swing'
        ? 'Equity CNC / NRML realised P&L'
        : 'F&O segment realised P&L'

  return (
    <div className="mt-calendar">
      <header className="mt-head">
        <div>
          <h1 className="mt-title">P&amp;L Calendar</h1>
          <p className="mt-sub">
            {styleHint} from Groww sync · click a day for 1-min review
          </p>
        </div>
        <div className="mt-head-actions">
          <div className="mt-style-toggle" role="tablist" aria-label="Trading type">
            <button
              type="button"
              role="tab"
              aria-selected={reviewStyle === 'intraday'}
              className={`mt-style-btn${reviewStyle === 'intraday' ? ' active' : ''}`}
              onClick={() => {
                setSelectedDate(null)
                setReviewStyle('intraday')
              }}
            >
              Equity Intraday
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={reviewStyle === 'swing'}
              className={`mt-style-btn${reviewStyle === 'swing' ? ' active' : ''}`}
              onClick={() => {
                setSelectedDate(null)
                setReviewStyle('swing')
              }}
            >
              Swing
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={reviewStyle === 'fno'}
              className={`mt-style-btn${reviewStyle === 'fno' ? ' active' : ''}`}
              onClick={() => {
                setSelectedDate(null)
                setReviewStyle('fno')
              }}
            >
              F&amp;O
            </button>
          </div>
          <div className="mt-cal-nav">
            <button type="button" className="btn ghost small" onClick={() => shiftMonth(-1)} aria-label="Previous month">
              ‹
            </button>
            <span className="mt-cal-month">{monthLabel}</span>
            <button type="button" className="btn ghost small" onClick={() => shiftMonth(1)} aria-label="Next month">
              ›
            </button>
          </div>
        </div>
      </header>

      {(refreshError || error) && <p className="mt-banner err">{refreshError || error}</p>}
      {refreshNote && <p className="mt-banner info">{refreshNote}</p>}

      {data && (
        <p className={`mt-month-pnl ${pnlClass(data.month_pnl)}`}>
          Month total: {fmtPnl(data.month_pnl)}
        </p>
      )}

      {loading && !data ? (
        <div className="mt-loading">Loading calendar…</div>
      ) : (
        <div className="mt-cal-grid">
          {WEEKDAYS.map((w) => (
            <div key={w} className="mt-cal-weekday">
              {w}
            </div>
          ))}
          {grid.map((cell, i) => {
            const clickable = Boolean(cell?.has_data && (cell.order_count > 0 || cell.realised_pnl != null))
            const tone =
              cell?.realised_pnl != null && cell.has_data ? pnlClass(cell.realised_pnl) : ''
            return (
              <button
                key={i}
                type="button"
                disabled={!clickable}
                className={`mt-cal-cell${cell ? '' : ' empty'}${cell?.has_data ? ' has-data' : ''}${
                  tone ? ` ${tone}` : ''
                }${clickable ? ' clickable' : ''}${selectedDate === cell?.date ? ' selected' : ''}`}
                onClick={() => {
                  if (cell?.date && clickable) setSelectedDate(cell.date)
                }}
              >
                {cell && (
                  <>
                    <span className="mt-cal-day">{cell.date.slice(-2)}</span>
                    <span className={`mt-cal-pnl ${pnlClass(cell.realised_pnl)}`}>
                      {fmtPnl(cell.realised_pnl)}
                    </span>
                    {cell.order_count > 0 && (
                      <span className="mt-cal-meta">{cell.order_count} orders</span>
                    )}
                  </>
                )}
              </button>
            )
          })}
        </div>
      )}

      {selectedDate && (
        <DayReviewModal
          date={selectedDate}
          style={reviewStyle}
          onClose={() => setSelectedDate(null)}
        />
      )}
    </div>
  )
}

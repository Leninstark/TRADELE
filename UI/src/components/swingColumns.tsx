import Tooltip from '@mui/material/Tooltip'
import type { GridColDef, GridColumnHeaderParams } from '@mui/x-data-grid'
import type { SwingStock, SwingTabId } from '../api/client'
import { COLUMN_HELP } from './swingTabHelp'

function formatCr(value: number | null | undefined) {
  if (value == null) return '—'
  return `₹${value.toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr`
}

function formatVolume(value: number | null | undefined) {
  if (value == null) return '—'
  if (value >= 100_000) return `${(value / 100_000).toFixed(1)}L`
  return value.toLocaleString('en-IN')
}

function headerWithHelp(params: GridColumnHeaderParams<SwingStock>, helpText: string) {
  return (
    <Tooltip title={helpText} arrow placement="top" enterDelay={300}>
      <span className="swing-col-header">{params.colDef.headerName}</span>
    </Tooltip>
  )
}

function extraField(
  field: string,
  header: string,
  fmt?: (v: unknown) => string,
): GridColDef<SwingStock> {
  return {
    field: `extra_${field}`,
    headerName: header,
    minWidth: 110,
    flex: 0.7,
    valueGetter: (_v, row) => row.extra?.[field],
    valueFormatter: (value) => (fmt ? fmt(value) : value != null ? String(value) : '—'),
  }
}

const BASE_COLUMNS: Record<SwingTabId, GridColDef<SwingStock>[]> = {
  dashboard: [
    extraField('rank', 'Rank'),
    { field: 'symbol', headerName: 'Symbol', minWidth: 110, flex: 0.7 },
    extraField('company', 'Company', (v) => String(v ?? '').slice(0, 40)),
    extraField('expected_move_pct', '% of profit', (v) => (v != null ? `+${Number(v).toFixed(1)}%` : '—')),
    extraField('ltp', 'LTP', (v) => (v != null ? `₹${Number(v).toFixed(2)}` : '—')),
    extraField('change_pct', 'Change %', (v) => (v != null ? `${v}%` : '—')),
    extraField('return_5d_pct', '5D Return', (v) => (v != null ? `${v}%` : '—')),
    extraField('return_10d_pct', '10D Return', (v) => (v != null ? `${v}%` : '—')),
    extraField('return_20d_pct', '20D Return', (v) => (v != null ? `${v}%` : '—')),
    extraField('volume_ratio', 'Vol Ratio', (v) => (v != null ? `${v}x` : '—')),
    {
      field: 'delivery_pct',
      headerName: 'Delivery %',
      minWidth: 100,
      flex: 0.6,
      valueFormatter: (v) => (v != null ? `${Number(v).toFixed(1)}%` : '—'),
    },
    {
      field: 'avg_daily_volume',
      headerName: 'Avg Volume',
      minWidth: 100,
      flex: 0.6,
      valueFormatter: (v) => formatVolume(v as number | null),
    },
    extraField('confidence', 'Confidence %', (v) => (v != null ? `${v}%` : '—')),
  ],
  stock_score: [
    extraField('rank', 'Rank'),
    { field: 'symbol', headerName: 'Stock', minWidth: 120, flex: 0.8 },
    extraField('score', 'Score'),
    extraField('return_20d_pct', '20D %', (v) => `${v}%`),
    extraField('relative_strength_pct', 'Rel Str', (v) => `${v}%`),
    extraField('volume_ratio', 'Vol Ratio', (v) => `${v}x`),
    {
      field: 'delivery_pct',
      headerName: 'Delivery %',
      minWidth: 110,
      flex: 0.7,
      valueFormatter: (v) => (v != null ? `${Number(v).toFixed(1)}%` : '—'),
    },
    extraField('sector_rank', 'Sector #'),
    extraField('news_sentiment', 'News'),
    extraField('score_components', 'Breakdown', (v) => {
      if (!v || typeof v !== 'object') return '—'
      const parts = Object.entries(v as Record<string, number>)
        .slice(0, 4)
        .map(([k, n]) => `${k.slice(0, 4)}:${n}`)
      return parts.join(' ')
    }),
  ],
  universe: [
    { field: 'symbol', headerName: 'Symbol', minWidth: 120, flex: 0.8 },
    {
      field: 'price',
      headerName: 'Price',
      type: 'number',
      minWidth: 110,
      flex: 0.7,
      valueFormatter: (v) => (v != null ? `₹${Number(v).toFixed(2)}` : '—'),
    },
    {
      field: 'market_cap_cr',
      headerName: 'Market Cap',
      type: 'number',
      minWidth: 130,
      flex: 0.9,
      valueFormatter: (v) => formatCr(v as number | null),
    },
    {
      field: 'avg_daily_volume',
      headerName: 'Avg Vol',
      type: 'number',
      minWidth: 110,
      flex: 0.7,
      valueFormatter: (v) => formatVolume(v as number | null),
    },
    {
      field: 'delivery_pct',
      headerName: 'Delivery %',
      type: 'number',
      minWidth: 110,
      flex: 0.7,
      valueFormatter: (v) => (v != null ? `${Number(v).toFixed(1)}%` : '—'),
    },
    {
      field: 'is_circuit',
      headerName: 'Circuit',
      type: 'boolean',
      minWidth: 90,
      flex: 0.5,
      valueFormatter: (v) => (v ? 'yes' : 'NO'),
    },
  ],
  price_momentum: [
    { field: 'symbol', headerName: 'Symbol', minWidth: 120, flex: 0.8 },
    {
      field: 'price',
      headerName: 'Price',
      minWidth: 100,
      flex: 0.6,
      valueFormatter: (v) => (v != null ? `₹${Number(v).toFixed(2)}` : '—'),
    },
    extraField('return_5d_pct', '5D %', (v) => `${v}%`),
    extraField('return_10d_pct', '10D %', (v) => `${v}%`),
    extraField('return_20d_pct', '20D %', (v) => `${v}%`),
    extraField('dist_52w_high_pct', 'From 52W H', (v) => `${v}%`),
    extraField('ema_20', 'EMA 20', (v) => `₹${Number(v).toFixed(2)}`),
    extraField('ema_50', 'EMA 50', (v) => `₹${Number(v).toFixed(2)}`),
  ],
  volume_explosion: [
    { field: 'symbol', headerName: 'Symbol', minWidth: 120, flex: 0.8 },
    {
      field: 'price',
      headerName: 'Price',
      minWidth: 100,
      flex: 0.6,
      valueFormatter: (v) => (v != null ? `₹${Number(v).toFixed(2)}` : '—'),
    },
    extraField('volume_ratio', 'Vol Ratio', (v) => `${v}x`),
    extraField('volume_trend', 'Vol Trend', (v) => `${v}x`),
    extraField('today_volume', 'Today Vol', (v) => formatVolume(Number(v))),
    extraField('vol_5d_avg', '5D Avg', (v) => formatVolume(Number(v))),
    extraField('vol_20d_avg', '20D Avg', (v) => formatVolume(Number(v))),
    extraField('strong_3x', '3x+', (v) => (v ? 'yes' : 'NO')),
  ],
  institutional_buying: [
    { field: 'symbol', headerName: 'Symbol', minWidth: 120, flex: 0.8 },
    {
      field: 'price',
      headerName: 'Price',
      minWidth: 100,
      flex: 0.6,
      valueFormatter: (v) => (v != null ? `₹${Number(v).toFixed(2)}` : '—'),
    },
    {
      field: 'delivery_pct',
      headerName: 'Delivery %',
      minWidth: 110,
      flex: 0.7,
      valueFormatter: (v) => (v != null ? `${Number(v).toFixed(1)}%` : '—'),
    },
    extraField('cmf', 'CMF'),
    extraField('volume_ratio', 'Vol Ratio', (v) => `${v}x`),
    extraField('ema_20', 'EMA 20', (v) => `₹${Number(v).toFixed(2)}`),
  ],
  news_sentiment: [
    { field: 'symbol', headerName: 'Symbol', minWidth: 120, flex: 0.8 },
    extraField('sentiment', 'Sentiment'),
    extraField('score', 'Score'),
    extraField('summary', 'Summary', (v) => String(v).slice(0, 120)),
    extraField('sources', 'Sources', (v) =>
      Array.isArray(v) ? (v as string[]).join(', ') : '—',
    ),
  ],
  delivery_percentage: [
    { field: 'symbol', headerName: 'Symbol', minWidth: 120, flex: 0.8 },
    {
      field: 'price',
      headerName: 'Price',
      minWidth: 100,
      flex: 0.6,
      valueFormatter: (v) => (v != null ? `₹${Number(v).toFixed(2)}` : '—'),
    },
    {
      field: 'delivery_pct',
      headerName: 'Delivery %',
      minWidth: 110,
      flex: 0.7,
      valueFormatter: (v) => (v != null ? `${Number(v).toFixed(1)}%` : '—'),
    },
    extraField('delivery_yesterday_pct', 'Del Yest', (v) => `${v}%`),
    extraField('delivery_change_pct', 'Del Δ', (v) => `+${v}%`),
    extraField('volume_today', 'Vol Today', (v) => formatVolume(Number(v))),
    extraField('volume_yesterday', 'Vol Yest', (v) => formatVolume(Number(v))),
    extraField('relative_strength_pct', 'Rel Str', (v) => `+${v}%`),
    extraField('stock_return_20d_pct', 'Stock 20D', (v) => `${v}%`),
    extraField('nifty_return_20d_pct', 'Nifty 20D', (v) => `${v}%`),
    extraField('perfect_trend', 'Trend', (v) => (v ? 'Perfect' : '—')),
  ],
  sector_strength: [
    { field: 'symbol', headerName: 'Symbol', minWidth: 120, flex: 0.8 },
    {
      field: 'price',
      headerName: 'Price',
      minWidth: 100,
      flex: 0.6,
      valueFormatter: (v) => (v != null ? `₹${Number(v).toFixed(2)}` : '—'),
    },
    extraField('sector', 'Sector'),
    extraField('sector_return_10d_pct', 'Sector 10D', (v) => `${v}%`),
    extraField('stock_return_10d_pct', 'Stock 10D', (v) => `${v}%`),
    extraField('sector_rank', 'Sector #'),
  ],
}

function helpKeyForColumn(field: string): string {
  if (field.startsWith('extra_')) return field.slice(6)
  return field
}

/** Columns with header tooltips for metric explanations */
export function getSwingColumns(tab: SwingTabId): GridColDef<SwingStock>[] {
  const cols = BASE_COLUMNS[tab] ?? BASE_COLUMNS.universe
  const helpMap = COLUMN_HELP[tab] ?? {}

  return cols.map((col) => {
    const key = helpKeyForColumn(col.field as string)
    const tip = helpMap[key]
    if (!tip) return col
    return {
      ...col,
      renderHeader: (params) => headerWithHelp(params, tip),
    }
  })
}

/** @deprecated use getSwingColumns */
export const SWING_TAB_COLUMNS = BASE_COLUMNS

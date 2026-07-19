import * as XLSX from 'xlsx'
import type { GridColDef } from '@mui/x-data-grid'
import type { SwingStock } from '../api/client'

/** Read the raw value for a column from a stock row (handles extra_ fields). */
function rawValue(row: SwingStock, field: string): unknown {
  if (field.startsWith('extra_')) {
    return row.extra?.[field.slice(6)]
  }
  return (row as unknown as Record<string, unknown>)[field]
}

function cellValue(value: unknown): string | number | boolean {
  if (value == null) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  if (typeof value === 'number' || typeof value === 'boolean') return value
  return String(value)
}

/**
 * Export the currently displayed swing rows to a real .xlsx file.
 * Headers follow the visible column headers; values are exported raw
 * (numbers stay numeric) so they remain sortable/filterable in Excel.
 */
export function exportSwingToExcel(
  columns: GridColDef<SwingStock>[],
  stocks: SwingStock[],
  sheetName: string,
  filename: string,
): void {
  const cols = columns.map((c) => ({
    field: c.field,
    header: c.headerName || c.field,
  }))

  const rows = stocks.map((stock) => {
    const record: Record<string, string | number | boolean> = {}
    for (const col of cols) {
      record[col.header] = cellValue(rawValue(stock, col.field))
    }
    return record
  })

  const worksheet = XLSX.utils.json_to_sheet(rows, {
    header: cols.map((c) => c.header),
  })

  worksheet['!cols'] = cols.map((c) => ({
    wch: Math.max(10, Math.min(40, c.header.length + 4)),
  }))

  const workbook = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(workbook, worksheet, sheetName.slice(0, 31))
  XLSX.writeFile(workbook, filename)
}

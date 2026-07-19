import { useMemo } from 'react'
import { AgGridReact } from 'ag-grid-react'
import type { ColDef } from 'ag-grid-community'
import type { ScanMatch } from '../types'

import 'ag-grid-community/styles/ag-grid.css'
import 'ag-grid-community/styles/ag-theme-alpine.css'

interface Props {
  title: string
  counts: Record<string, number>
  picks: ScanMatch[]
}

export default function ScannerPanel({ title, counts, picks }: Props) {
  const columnDefs = useMemo<ColDef<ScanMatch>[]>(
    () => [
      { field: 'symbol', headerName: 'Symbol', width: 110 },
      { field: 'strategy_name', headerName: 'Strategy', flex: 1 },
      { field: 'confidence', headerName: 'Conf %', width: 90 },
      { field: 'rating', headerName: 'Rating', width: 110 },
      {
        field: 'reasons',
        headerName: 'Reasons',
        flex: 2,
        valueFormatter: (p) => (p.value as string[])?.join(' · ') ?? '',
      },
    ],
    [],
  )

  return (
    <section className="panel scanner-panel">
      <h2>{title}</h2>
      <div className="scanner-counts">
        {Object.entries(counts).map(([id, count]) => (
          <span key={id} className="count-chip">
            {id.replace(/_/g, ' ')}: <strong>{count}</strong>
          </span>
        ))}
      </div>
      <div className="ag-theme-alpine-dark grid-wrap">
        <AgGridReact<ScanMatch>
          rowData={picks}
          columnDefs={columnDefs}
          domLayout="autoHeight"
          defaultColDef={{ sortable: true, resizable: true }}
        />
      </div>
    </section>
  )
}

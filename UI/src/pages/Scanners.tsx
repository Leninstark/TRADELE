import { useEffect, useState } from 'react'
import { fetchStrategies, runScanners } from '../api/client'
import type { ScannerStrategy, ScanMatch } from '../types'
import { AgGridReact } from 'ag-grid-react'
import type { ColDef } from 'ag-grid-community'

import 'ag-grid-community/styles/ag-grid.css'
import 'ag-grid-community/styles/ag-theme-alpine.css'

const STYLES = ['intraday', 'swing', 'positional'] as const

export default function Scanners() {
  const [style, setStyle] = useState<(typeof STYLES)[number]>('swing')
  const [strategies, setStrategies] = useState<ScannerStrategy[]>([])
  const [results, setResults] = useState<ScanMatch[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetchStrategies(style).then(setStrategies)
  }, [style])

  useEffect(() => {
    setLoading(true)
    runScanners(style)
      .then((data) => setResults(data.top_picks ?? []))
      .catch(() => setResults([]))
      .finally(() => setLoading(false))
  }, [style])

  const columnDefs: ColDef<ScanMatch>[] = [
    { field: 'symbol', width: 100 },
    { field: 'strategy_name', flex: 1 },
    { field: 'confidence', headerName: 'Confidence', width: 110 },
    { field: 'rating', width: 120 },
    {
      field: 'reasons',
      flex: 2,
      valueFormatter: (p) => (p.value as string[])?.join(' · ') ?? '',
    },
  ]

  return (
    <div className="scanners-page">
      <header className="page-header">
        <h1>AI Scanners</h1>
        <p>Rule-engine powered scans across three trading styles</p>
      </header>

      <div className="style-tabs">
        {STYLES.map((s) => (
          <button
            key={s}
            type="button"
            className={`style-tab ${s} ${style === s ? 'active' : ''}`}
            onClick={() => setStyle(s)}
          >
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      <section className="panel">
        <h2>Strategies ({strategies.length})</h2>
        <div className="strategy-chips">
          {strategies.map((s) => (
            <div key={s.id} className="strategy-chip">
              <strong>{s.name}</strong>
              <span>{s.description}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>Results {loading && <small>— scanning…</small>}</h2>
        <div className="ag-theme-alpine-dark grid-wrap tall">
          <AgGridReact<ScanMatch>
            rowData={results}
            columnDefs={columnDefs}
            defaultColDef={{ sortable: true, resizable: true }}
            pagination
            paginationPageSize={15}
          />
        </div>
      </section>
    </div>
  )
}

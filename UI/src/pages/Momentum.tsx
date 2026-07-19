import { useEffect, useState } from 'react'
import { runMomentumAgent } from '../api/client'
import { AgGridReact } from 'ag-grid-react'
import type { ColDef } from 'ag-grid-community'

import 'ag-grid-community/styles/ag-grid.css'
import 'ag-grid-community/styles/ag-theme-alpine.css'

interface MomentumPick {
  symbol: string
  confidence: number
  rating: string
  reasons: string[]
  risk: string
  return_30d_pct: number
  return_5d_pct?: number
  volume_trend?: number
  rsi?: number
  momentum_score?: number
  hold_period?: string
  close?: number
}

export default function Momentum() {
  const [picks, setPicks] = useState<MomentumPick[]>([])
  const [summary, setSummary] = useState('')
  const [meta, setMeta] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    runMomentumAgent({ lookback_days: 30, top_n: 15, max_symbols: 50 })
      .then((data) => {
        setPicks(data.picks ?? [])
        setSummary(data.ai_summary ?? '')
        setMeta(data.meta ?? {})
      })
      .catch((e) => setError(e.message ?? 'Momentum scan failed'))
      .finally(() => setLoading(false))
  }, [])

  const columnDefs: ColDef<MomentumPick>[] = [
    { field: 'symbol', width: 100 },
    { field: 'confidence', headerName: 'Conf %', width: 90 },
    { field: 'rating', width: 140 },
    { field: 'return_30d_pct', headerName: '30d %', width: 80 },
    { field: 'return_5d_pct', headerName: '5d %', width: 70 },
    { field: 'volume_trend', headerName: 'Vol', width: 70 },
    { field: 'rsi', width: 60 },
    {
      field: 'reasons',
      flex: 1,
      valueFormatter: (p) => (p.value as string[])?.join(' · ') ?? '',
    },
    { field: 'risk', flex: 1 },
  ]

  if (loading) return <div className="page-state">Running 30-day momentum agent…</div>
  if (error) return <div className="page-state error">Error: {error}</div>

  return (
    <div className="momentum-page">
      <header className="page-header">
        <h1>30-Day Momentum Agent</h1>
        <p>LangGraph pipeline: fetch → score → Gemini analysis</p>
      </header>

      {summary && (
        <section className="panel ai-summary">
          <h2>AI Summary</h2>
          <p>{summary}</p>
        </section>
      )}

      <div className="scanner-counts">
        {meta.universe_size != null && (
          <span className="count-chip">Universe: <strong>{meta.universe_size}</strong></span>
        )}
        {meta.scored_count != null && (
          <span className="count-chip">Scored: <strong>{meta.scored_count}</strong></span>
        )}
      </div>

      <section className="panel">
        <h2>Top Momentum Picks</h2>
        <div className="ag-theme-alpine-dark grid-wrap tall">
          <AgGridReact<MomentumPick>
            rowData={picks}
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

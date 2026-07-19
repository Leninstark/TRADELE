export interface IndexQuote {
  name: string
  last: number | null
  change_pct: number
  direction: string
  confidence: number
}

export interface ScanMatch {
  symbol: string
  strategy_id: string
  strategy_name: string
  style: string
  confidence: number
  rating: string
  reasons: string[]
  close?: number
}

export interface DashboardData {
  market: {
    indices: IndexQuote[]
    india_vix: { value: number | null; level: string }
    pcr: { value: number | null; signal: string }
    market_breadth: {
      advance: number | null
      decline: number | null
      unchanged: number | null
      adr_ratio: number | null
    }
  }
  top_swing: ScanMatch[]
  intraday_scanners: { counts: Record<string, number>; top: ScanMatch[] }
  positional_scanners: { counts: Record<string, number>; top: ScanMatch[] }
  alerts: { long: AlertItem[]; short: AlertItem[] }
  portfolio: { overall_pnl_pct: number | null; ai_rating: string; message: string }
}

export interface AlertItem {
  symbol: string
  direction: string
  rank: number
  score: number
  reasons: { reason: string; source: string }[]
}

export interface ScannerStrategy {
  id: string
  name: string
  style: string
  description: string
  condition_count: number
  min_confidence?: number
  enabled?: boolean
}

export interface RuleCondition {
  id: string
  label: string
  field: string
  operator: string
  value?: number | boolean | [number, number] | null
  ref_field?: string | null
  weight: number
  reason_template: string
}

export interface RuleStrategy {
  id: string
  name: string
  style: 'intraday' | 'swing' | 'positional'
  description: string
  min_confidence: number
  enabled: boolean
  conditions: RuleCondition[]
}

export interface RulesConfig {
  version: number
  updated_at?: string
  file_path?: string
  strategies: RuleStrategy[]
}

export interface RulesSchema {
  version: number
  styles: string[]
  operators: { value: string; label: string }[]
  fields: string[]
  ref_operators: string[]
  value_operators: string[]
}

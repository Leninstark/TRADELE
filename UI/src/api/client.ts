import axios from 'axios'
import type { DashboardData, RulesConfig, RulesSchema, ScannerStrategy } from '../types'

// Local: Vite proxies /api → localhost:8000
// Production: prefer VITE_API_URL; fall back to Railway (or same-origin /api via Vercel rewrite)
const PROD_API = 'https://tradele-api-production.up.railway.app'
const configured = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '')
const apiBase = configured || (import.meta.env.PROD ? PROD_API : '')
const api = axios.create({ baseURL: apiBase ? `${apiBase}/api` : '/api' })

export async function fetchDashboard(): Promise<DashboardData> {
  const { data } = await api.get<DashboardData>('/dashboard')
  return data
}

export async function fetchStrategies(style?: string): Promise<ScannerStrategy[]> {
  const { data } = await api.get<ScannerStrategy[]>('/scanners/strategies', {
    params: style ? { style } : {},
  })
  return data
}

export async function runScanners(style: string) {
  const { data } = await api.get('/scanners/run', { params: { style, top_n: 20 } })
  return data
}

export async function fetchLatestAlerts() {
  const { data } = await api.get('/alerts/latest')
  return data
}

export async function fetchMarket() {
  const { data } = await api.get('/dashboard/market')
  return data
}

export async function runMomentumAgent(params?: {
  lookback_days?: number
  top_n?: number
  max_symbols?: number
}) {
  const { data } = await api.get('/agents/momentum', { params, timeout: 120_000 })
  return data
}

export interface SymbolSuggestion {
  symbol: string
  company: string
}

export async function fetchExploreSymbols(q: string): Promise<SymbolSuggestion[]> {
  const { data } = await api.get<{ symbols: SymbolSuggestion[] }>('/explore/symbols', {
    params: { q },
  })
  return data.symbols
}

export interface HorizonOutlook {
  bias?: string
  expected_range?: string
  confidence?: number
  rationale?: string
}

export interface StockReport {
  verdict?: string
  conviction?: number
  summary?: string
  fundamental?: { rating?: string; points?: string[]; risks?: string[] }
  technical?: {
    rating?: string
    trend?: string
    points?: string[]
    key_levels?: { support?: number | null; resistance?: number | null }
  }
  sentiment?: { rating?: string; points?: string[]; industry_impact?: string }
  outlook?: {
    next_week?: HorizonOutlook
    next_month?: HorizonOutlook
    next_3_months?: HorizonOutlook
  }
  entry?: {
    buy_zone?: string
    stop_loss?: number
    target_1?: number
    target_2?: number
    risk_reward?: string
  }
  catalysts?: string[]
  red_flags?: string[]
  conclusion?: string
  engine?: string
  parse_note?: string
}

export interface NewsHeadline {
  title: string
  source: string
  published: string | null
  summary: string
  link: string
}

export interface StockAnalysis {
  symbol: string
  company: string
  sector?: string
  metrics: Record<string, number | boolean | null>
  fundamentals: Record<string, unknown>
  news: NewsHeadline[]
  industry_news: NewsHeadline[]
  report: StockReport
  generated_at: string
  error?: string
  message?: string
}

export async function analyzeStock(symbol: string): Promise<StockAnalysis> {
  const { data } = await api.get<StockAnalysis>('/explore/analyze', {
    params: { symbol },
    timeout: 300_000,
  })
  return data
}

export async function fetchRulesSchema(): Promise<RulesSchema> {
  const { data } = await api.get<RulesSchema>('/admin/rules/schema')
  return data
}

export async function fetchRulesConfig(): Promise<RulesConfig> {
  const { data } = await api.get<RulesConfig>('/admin/rules')
  return data
}

export async function saveRulesConfig(config: RulesConfig): Promise<RulesConfig> {
  const { data } = await api.put<{ config: RulesConfig }>('/admin/rules', {
    version: config.version,
    strategies: config.strategies,
  })
  return data.config
}

export async function resetRulesConfig(): Promise<RulesConfig> {
  const { data } = await api.post<{ config: RulesConfig }>('/admin/rules/reset')
  return data.config
}

export interface ZerodhaStatus {
  connected: boolean
  status: 'connected' | 'not_connected' | string
  message: string
  expires_at: string | null
  username: string
  login_url?: string | null
  api_key_set?: boolean
}

export async function fetchZerodhaStatus(username: string): Promise<ZerodhaStatus> {
  const { data } = await api.get<ZerodhaStatus>('/zerodha/status', {
    params: { username, live_check: true },
  })
  return data
}

export async function fetchZerodhaLoginUrl(): Promise<string> {
  const { data } = await api.get<{ login_url: string }>('/zerodha/login-url')
  return data.login_url
}

export async function saveZerodhaToken(username: string, access_token: string): Promise<ZerodhaStatus> {
  const { data } = await api.post<ZerodhaStatus>('/zerodha/token', {
    username,
    access_token,
  })
  return data
}

export interface SwingStock {
  symbol: string
  price?: number | null
  market_cap_cr?: number | null
  avg_daily_volume?: number | null
  delivery_pct?: number | null
  is_circuit?: boolean
  extra?: Record<string, unknown>
}

export type UniverseStock = SwingStock

export interface SwingScanResult {
  tab: string
  filter: Record<string, unknown>
  stocks: SwingStock[]
  meta: Record<string, unknown>
  run: {
    id: number
    tab: string
    started_at: string | null
    finished_at: string | null
    status: string
    error_message: string | null
  } | null
}

export type UniverseScanResult = SwingScanResult

export type SwingTabId =
  | 'dashboard'
  | 'stock_score'
  | 'universe'
  | 'price_momentum'
  | 'volume_explosion'
  | 'institutional_buying'
  | 'news_sentiment'
  | 'delivery_percentage'
  | 'sector_strength'

export async function fetchSwingResults(tab: SwingTabId): Promise<SwingScanResult> {
  const { data } = await api.get<SwingScanResult>(`/swing/${tab}/results`)
  return data
}

export async function runSwingScan(tab: SwingTabId, max_symbols = 400): Promise<SwingScanResult> {
  const timeout = tab === 'dashboard' ? 1_800_000 : 600_000
  const { data } = await api.post<SwingScanResult>(`/swing/${tab}/scan`, null, {
    params: tab === 'universe' || tab === 'dashboard' ? { max_symbols } : {},
    timeout,
  })
  return data
}

export async function fetchUniverseResults(): Promise<SwingScanResult> {
  return fetchSwingResults('universe')
}

export async function runUniverseScan(max_symbols = 400): Promise<SwingScanResult> {
  return runSwingScan('universe', max_symbols)
}

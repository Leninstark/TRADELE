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
  const { data } = await api.get('/scanners/run', {
    params: { style, top_n: 20 },
    timeout: 45_000,
  })
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

export interface ExploreRecentItem {
  symbol: string
  company: string
  analysis_date?: string
  accessed_at?: string
}

export async function fetchExploreRecent(limit = 30): Promise<ExploreRecentItem[]> {
  const { data } = await api.get<{ items: ExploreRecentItem[] }>('/explore/recent', {
    params: { limit },
  })
  return data.items || []
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
  from_cache?: boolean
  cached_date?: string
  error?: string
  message?: string
}

export async function analyzeStock(
  symbol: string,
  forceRefresh = false,
): Promise<StockAnalysis> {
  const { data } = await api.get<StockAnalysis>('/explore/analyze', {
    params: { symbol, force_refresh: forceRefresh },
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

export interface GrowwStatus {
  connected: boolean
  status: string
  message: string
  expires_at: string | null
  username: string
  can_refresh?: boolean
  api_key_set?: boolean
  api_secret_set?: boolean
  keys_page_url?: string
}

export async function fetchGrowwStatus(username: string): Promise<GrowwStatus> {
  const { data } = await api.get<GrowwStatus>('/groww/status', {
    params: { username, live_check: true },
  })
  return data
}

export async function fetchGrowwLoginInfo(): Promise<{ docs_url: string; keys_page_url: string; message: string }> {
  const { data } = await api.get('/groww/login-info')
  return data
}

export async function saveGrowwToken(username: string, access_token: string): Promise<GrowwStatus> {
  const { data } = await api.post<GrowwStatus>('/groww/token', { username, access_token })
  return data
}

export async function saveGrowwCredentials(username: string, api_key: string, api_secret: string) {
  const { data } = await api.post('/groww/credentials', { username, api_key, api_secret })
  return data
}

export async function refreshGrowwToken(username: string): Promise<GrowwStatus> {
  const { data } = await api.post<GrowwStatus>('/groww/refresh', null, { params: { username } })
  return data
}

export interface MyTradeStatus {
  groww_connected: boolean
  groww_message?: string
  username: string
  today: string
  first_stored_date: string | null
  last_stored_date: string | null
  trading_days_stored: number
  last_sync_at: string | null
  last_sync_orders: number
  last_sync_trades: number
}

export interface MyTradeRefreshResult {
  ok: boolean
  dates_synced: string[]
  orders_added: number
  trades_added: number
  last_stored_before: string | null
  today: string
  gap_days_not_backfilled?: number
  note?: string
  error?: string
}

export interface MyTradeStyleDashboard {
  style: 'intraday' | 'swing'
  pnl: {
    today: number
    mtd: number
    total: number
    avg_daily: number
    best_day: number
    worst_day: number
    green_days_pct: number
    green_days: number
    red_days: number
    max_drawdown: number
    profit_factor_days: number | null
  }
  activity: {
    symbols_today: number
    hits_today: number
    avg_hits_per_day: number
    total_hits: number
    fills_today?: number
    total_fills?: number
    hits_breakdown_today?: Array<{ trade_date: string; symbol: string; hits: number; fills: number }>
    trades_today: number
    trades_mtd: number
    total_trades: number
    avg_trades_per_day: number
    total_orders: number
    fill_rate_pct: number
    active_trading_days: number
  }
  quality: {
    win_rate_pct: number
    avg_win: number
    avg_loss: number
    profit_factor: number | null
    expectancy: number
    round_trips: number
  }
  risk: {
    max_daily_loss: number
    max_drawdown: number
    largest_daily_gain: number
  }
  concentration: {
    top_symbol_pct: number
    top_symbols: Array<{ symbol: string; pnl: number }>
  }
  charts: {
    daily_pnl: Array<{ date: string; pnl: number }>
    cumulative_pnl: Array<{ date: string; pnl: number }>
  }
}

export interface MyTradeDashboardData {
  username: string
  today: string
  intraday: MyTradeStyleDashboard
  swing: MyTradeStyleDashboard
  recent_orders: Array<{
    groww_order_id: string
    trade_date: string
    order_time?: string | null
    trading_symbol: string
    transaction_type: string
    quantity: number
    filled_quantity: number
    order_status: string
    segment: string
    product: string | null
    style: 'intraday' | 'swing' | null
  }>
}

export interface MyTradeCalendarData {
  username: string
  month: string
  month_pnl: number
  days: Array<{
    date: string
    weekday: number
    realised_pnl: number | null
    order_count: number
    trade_count: number
    has_data: boolean
  }>
}

export interface MyTradeJournalData {
  username: string
  from: string | null
  to: string | null
  orders: Array<{
    id: number
    trade_date: string
    groww_order_id: string
    trading_symbol: string
    transaction_type: string
    quantity: number
    filled_quantity: number
    price: number | null
    average_fill_price: number | null
    order_status: string
    order_type: string | null
    segment: string
    exchange: string | null
    product: string | null
    synced_at: string | null
  }>
  trades: Array<{
    id: number
    trade_date: string
    groww_trade_id: string
    groww_order_id: string
    trading_symbol: string
    transaction_type: string
    quantity: number
    price: number
    value: number
    segment: string
    exchange: string | null
    product: string | null
    synced_at: string | null
  }>
}

export async function fetchMyTradeStatus(username: string): Promise<MyTradeStatus> {
  const { data } = await api.get<MyTradeStatus>('/mytrade/status', { params: { username } })
  return data
}

export async function refreshMyTrade(username: string): Promise<MyTradeRefreshResult> {
  const { data } = await api.post<MyTradeRefreshResult>('/mytrade/refresh', null, {
    params: { username },
    timeout: 120_000,
  })
  return data
}

export async function fetchMyTradeDashboard(username: string): Promise<MyTradeDashboardData> {
  const { data } = await api.get<MyTradeDashboardData>('/mytrade/dashboard', { params: { username } })
  return data
}

export async function fetchMyTradeCalendar(
  username: string,
  month: string,
  style: 'intraday' | 'swing' | 'fno' = 'intraday',
): Promise<MyTradeCalendarData> {
  const { data } = await api.get<MyTradeCalendarData>('/mytrade/calendar', {
    params: { username, month, style },
  })
  return data
}

export interface DayReviewMarker {
  time: string
  side: string
  kind: string
  price: number | null
  quantity: number
  order_id: string
  status: string
}

export interface DayReviewCandle {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  vwap?: number | null
  ema_9?: number | null
  ema_20?: number | null
  ema_50?: number | null
  bb_upper?: number | null
  bb_mid?: number | null
  bb_lower?: number | null
  rsi?: number | null
  atr?: number | null
  macd_hist?: number | null
  vol_sma?: number | null
  vol_ratio?: number | null
  or_high?: number | null
  or_low?: number | null
}

export interface DayReviewTicker {
  symbol: string
  pnl: number | null
  order_count: number
  markers: DayReviewMarker[]
}

export interface DayReviewAi {
  summary?: string
  observations?: string[]
  mistakes?: string[]
  best_setup?: string
  what_could_have_been_done?: string[]
  engine?: string
}

export interface DayReviewChart {
  ok?: boolean
  symbol: string
  pnl: number | null
  order_count: number
  markers: DayReviewMarker[]
  candles: DayReviewCandle[]
  candle_source: string
  candle_count?: number
  candle_error?: string | null
  ai?: DayReviewAi
}

export interface DayReviewData {
  ok: boolean
  date: string
  style: string
  day_pnl: number
  order_count: number
  symbols: string[]
  tickers: DayReviewTicker[]
  error?: string
}

export async function fetchDayReview(
  username: string,
  date: string,
  style: 'intraday' | 'swing' | 'fno' = 'intraday',
  forceRefresh = false,
): Promise<DayReviewData> {
  const { data } = await api.get<DayReviewData>('/mytrade/day-review', {
    params: { username, date, style, force_refresh: forceRefresh },
    timeout: 60_000,
  })
  return data
}

export async function fetchDayReviewChart(
  username: string,
  date: string,
  symbol: string,
  style: 'intraday' | 'swing' | 'fno' = 'intraday',
  forceRefresh = false,
): Promise<DayReviewChart> {
  const { data } = await api.get<DayReviewChart>('/mytrade/day-review/chart', {
    params: { username, date, symbol, style, force_refresh: forceRefresh },
    timeout: 180_000,
  })
  return data
}

export async function fetchMyTradeJournal(
  username: string,
  from?: string,
  to?: string,
): Promise<MyTradeJournalData> {
  const { data } = await api.get<MyTradeJournalData>('/mytrade/journal', {
    params: { username, from, to },
  })
  return data
}

export interface JournalUploadResult {
  ok: boolean
  filename?: string
  parsed_rows?: number
  added?: number
  skipped_before_cutoff?: number
  duplicates?: number
  cutoff?: string | null
  fills_total?: number
}

export async function uploadJournalExcel(
  username: string,
  file: File,
): Promise<JournalUploadResult> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post<JournalUploadResult>('/mytrade/journal/upload', form, {
    params: { username },
    timeout: 120_000,
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export interface TraderDnaReport {
  ok?: boolean
  id?: number
  username?: string
  generated_at?: string | null
  fills_through?: string | null
  fill_count?: number
  stats?: Record<string, unknown>
  narrative?: Record<string, unknown>
  llm_provider?: string | null
  llm_used?: boolean
  status?: string
  error_message?: string | null
  from_cache?: boolean
  message?: string
  error?: string
  groww_sync?: Record<string, unknown>
}

export async function fetchTraderDna(username: string): Promise<TraderDnaReport> {
  const { data } = await api.get<TraderDnaReport>('/mytrade/journal/dna', {
    params: { username },
  })
  return data
}

export async function runTraderDna(
  username: string,
  force = false,
): Promise<TraderDnaReport> {
  const { data } = await api.post<TraderDnaReport>('/mytrade/journal/dna', null, {
    params: { username, force },
    timeout: 600_000,
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

/* ── Tomorrow intraday momentum scanner ─────────────────────────── */

export interface IntradayCheck {
  id: string
  label: string
  passed: boolean
  detail: string
}

export interface IntradayCandidate {
  symbol: string
  direction: 'long' | 'short' | string
  conviction: number
  can_trade_tomorrow: boolean
  verdict: string
  narrative: string
  plan: string
  checks: IntradayCheck[]
  checks_passed: number
  checks_total: number
  reasons: string[]
  misses: string[]
  metrics: Record<string, number | null | undefined>
  news?: {
    count: number
    tone: string
    headlines: { title: string; source: string; link: string; published?: string | null }[]
    ok_for_long?: boolean
    ok_for_short?: boolean
  }
  nse?: {
    delivery_pct?: number | null
    market_cap_cr?: number | null
    notes?: string[]
    intraday_friendly?: boolean
  }
  yahoo?: {
    available?: boolean
    market_cap_cr?: number | null
    avg_volume?: number | null
    recommendation?: string | null
    headline?: string | null
    notes?: string[]
  }
  data_source?: string
  score?: number
}

export interface TomorrowMomentumScan {
  as_of?: string
  scanned?: number
  prefiltered?: number
  sources?: string[]
  rate_limited?: boolean
  pattern?: string
  longs: IntradayCandidate[]
  shorts: IntradayCandidate[]
  message?: string | null
  error?: string
  run_id?: number
  saved?: boolean
  from_cache?: boolean
  target_date?: string
}

export async function runTomorrowMomentumScan(params?: {
  username?: string
  top_n?: number
  max_symbols?: number
  force_refresh?: boolean
}): Promise<TomorrowMomentumScan> {
  const { data } = await api.get<TomorrowMomentumScan>('/intraday/tomorrow-momentum', {
    params: {
      username: params?.username || 'leninstark',
      top_n: params?.top_n ?? 3,
      max_symbols: params?.max_symbols ?? 40,
      force_refresh: params?.force_refresh ?? false,
    },
    timeout: 300_000,
  })
  return data
}

export interface IntradaySetupBar {
  t: string
  label: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  ema_9?: number | null
  ema_20?: number | null
  vwap?: number | null
}

export interface IntradaySetupCallout {
  n: number
  check_id: string
  title: string
  kind: string
  level_key?: string | null
  passed: boolean
  label: string
  detail: string
}

export interface IntradaySetupChart {
  symbol: string
  direction?: string
  as_of?: string
  interval?: string
  data_source?: string
  bars: IntradaySetupBar[]
  levels: Record<string, number | null | undefined>
  callouts: IntradaySetupCallout[]
  checks?: IntradayCheck[]
  error?: string
  message?: string
}

export async function fetchIntradaySetupChart(params: {
  symbol: string
  direction?: string
  username?: string
  as_of?: string
}): Promise<IntradaySetupChart> {
  const { data } = await api.get<IntradaySetupChart>('/intraday/tomorrow-momentum/chart', {
    params: {
      symbol: params.symbol,
      direction: params.direction || 'long',
      username: params.username || 'leninstark',
      as_of: params.as_of || undefined,
    },
    timeout: 90_000,
  })
  return data
}

/* ── Watchlist + Analyst chat ───────────────────────────────────── */

export interface WatchlistItemRow {
  id: number
  symbol: string
  company: string
  sector?: string | null
  notes?: string | null
  added_at?: string | null
}

export interface WatchlistCitation {
  source: string
  detail: string
}

export interface WatchlistAnswerBlock {
  type: 'paragraph' | 'bullets' | 'table' | 'kv' | 'bars' | string
  title?: string
  text?: string
  items?: Array<string | { label?: string; value?: string | number }>
  columns?: string[]
  rows?: Array<Array<string | number>>
}

export interface WatchlistAnalystAnswer {
  summary_plain?: string
  summary_technical?: string
  technical_metrics?: { label: string; value: string; hint?: string }[]
  blocks?: WatchlistAnswerBlock[]
  verdict?: string
  conviction?: number
  key_levels?: { support?: unknown[]; resistance?: unknown[] }
  catalysts?: string[]
  risks?: string[]
  citations?: WatchlistCitation[]
  blocked?: boolean
  engine?: string
  answered_question?: string
}

export interface WatchlistChatResult {
  symbol?: string
  company?: string
  question?: string
  answer?: WatchlistAnalystAnswer
  sources?: string[]
  analysis_id?: number
  from_cache?: boolean
}

export interface WatchlistHistoryEntry {
  id: number
  symbol?: string
  question?: string
  payload: WatchlistAnalystAnswer
  sources?: string[]
  created_at?: string
}

export async function fetchWatchlist(username?: string): Promise<WatchlistItemRow[]> {
  const { data } = await api.get<{ items: WatchlistItemRow[] }>('/watchlist/items', {
    params: { username: username || 'leninstark' },
  })
  return data.items || []
}

export async function addWatchlistSymbol(
  symbol: string,
  username?: string,
  company?: string,
): Promise<WatchlistItemRow> {
  const { data } = await api.post<WatchlistItemRow>('/watchlist/items', {
    symbol,
    username: username || 'leninstark',
    company,
  })
  return data
}

export async function removeWatchlistSymbol(symbol: string, username?: string): Promise<void> {
  await api.delete(`/watchlist/items/${encodeURIComponent(symbol)}`, {
    params: { username: username || 'leninstark' },
  })
}

export async function watchlistChat(params: {
  symbol: string
  message: string
  username?: string
  force_refresh?: boolean
}): Promise<WatchlistChatResult> {
  const { data } = await api.post<WatchlistChatResult>(
    '/watchlist/chat',
    {
      symbol: params.symbol,
      message: params.message,
      username: params.username || 'leninstark',
      force_refresh: params.force_refresh ?? false,
    },
    { timeout: 180_000 },
  )
  return data
}

export async function fetchWatchlistHistory(
  symbol?: string,
  username?: string,
  limit = 30,
): Promise<WatchlistHistoryEntry[]> {
  const { data } = await api.get<{ history: WatchlistHistoryEntry[] }>('/watchlist/chat/history', {
    params: { username: username || 'leninstark', symbol, limit },
  })
  return data.history || []
}

/* ── Market News watch + live feed ──────────────────────────────── */

export interface NewsWatchItem {
  id: number
  symbol: string
  company: string
  sector?: string | null
  added_at?: string | null
}

export interface NewsHeadlineItem {
  title?: string
  link?: string
  source?: string
  published?: string | null
  summary?: string
}

export interface NewsSymbolAnalysis {
  verdict?: string
  sentiment_score?: number
  impact_summary?: string
  sector_note?: string
  highlights?: { title?: string; link?: string; source?: string; impact?: string }[]
}

export interface NewsSymbolFeedPayload {
  company_news?: NewsHeadlineItem[]
  sector_news?: NewsHeadlineItem[]
  rss_hits?: NewsHeadlineItem[]
  analysis?: NewsSymbolAnalysis
  has_new?: boolean
  new_count?: number
  updated_at?: string
}

export interface NewsSymbolFeedGroup {
  symbol: string
  company?: string
  sector?: string | null
  added_at?: string | null
  feed?: NewsSymbolFeedPayload | null
  updated_at?: string | null
}

export function getNewsWsUrl(username?: string): string {
  const user = encodeURIComponent(username || 'leninstark')
  const configured = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '')
  const prodApi = 'https://tradele-api-production.up.railway.app'
  const base = configured || (import.meta.env.PROD ? prodApi : '')
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  if (base) {
    try {
      const u = new URL(base)
      return `${proto}//${u.host}/api/news/ws?username=${user}`
    } catch {
      /* fall through */
    }
  }
  return `${proto}//${window.location.host}/api/news/ws?username=${user}`
}

export async function fetchNewsWatch(username?: string): Promise<NewsWatchItem[]> {
  const { data } = await api.get<{ items: NewsWatchItem[] }>('/news/watch', {
    params: { username: username || 'leninstark' },
  })
  return data.items || []
}

export async function addNewsWatchSymbol(
  symbol: string,
  username?: string,
  company?: string,
): Promise<{ item: NewsWatchItem; feed: unknown }> {
  const { data } = await api.post('/news/watch', {
    symbol,
    username: username || 'leninstark',
    company,
  }, { timeout: 120_000 })
  return data
}

export async function removeNewsWatchSymbol(symbol: string, username?: string): Promise<void> {
  await api.delete(`/news/watch/${encodeURIComponent(symbol)}`, {
    params: { username: username || 'leninstark' },
  })
}

export async function fetchNewsFeed(username?: string, q?: string): Promise<NewsSymbolFeedGroup[]> {
  const { data } = await api.get<{ feeds: NewsSymbolFeedGroup[] }>('/news/feed', {
    params: { username: username || 'leninstark', q: q || undefined },
  })
  return data.feeds || []
}

export async function refreshNewsFeed(username?: string, symbol?: string): Promise<void> {
  await api.post('/news/feed/refresh', null, {
    params: { username: username || 'leninstark', symbol },
    timeout: 120_000,
  })
}

export async function acknowledgeNewsFeed(symbol: string, username?: string): Promise<void> {
  await api.post(`/news/feed/${encodeURIComponent(symbol)}/ack`, null, {
    params: { username: username || 'leninstark' },
  })
}

export interface MarketBriefSector {
  sector: string
  bias: string
  reason?: string
  rule_hits?: number
  note?: string
}

export interface MarketBriefIndex {
  index: string
  bias: string
  confidence?: number
  note?: string
}

export interface MarketBriefReport {
  ok?: boolean
  id?: number
  brief_type?: string
  as_of?: string | null
  stance?: string
  confidence?: number
  headline_count?: number
  llm_used?: boolean
  llm_provider?: string | null
  alerted?: boolean
  market_summary?: string
  indices?: MarketBriefIndex[]
  sectors?: MarketBriefSector[]
  catalysts?: Array<{ title?: string; why?: string; source?: string; severity?: string }>
  invalidate_if?: string[]
  action_card?: {
    guidance?: string
    max_risk_today?: string
    avoid_sectors?: string[]
    watch_sectors?: string[]
    wait_first_hour?: boolean
  }
  crosscheck?: {
    available?: boolean
    notes?: string[]
    series?: Record<string, { last?: number; chg_pct?: number; ticker?: string }>
  }
  headlines?: Array<{ title?: string; source?: string; link?: string }>
  disclaimer?: string
  generated_at_ist?: string
  message?: string
  error?: string
}

export async function fetchMarketBrief(briefType?: string): Promise<MarketBriefReport> {
  const { data } = await api.get<MarketBriefReport>('/news/brief', {
    params: briefType ? { brief_type: briefType } : undefined,
  })
  return data
}

export async function runMarketBrief(
  briefType: 'night' | 'morning' | 'manual' = 'manual',
  sendAlert = false,
): Promise<MarketBriefReport> {
  const { data } = await api.post<MarketBriefReport>('/news/brief/run', null, {
    params: { brief_type: briefType, send_alert: sendAlert },
    timeout: 300_000,
  })
  return data
}

/* ─── JARVIS / INFINITY ─────────────────────────────────────────── */

export type JarvisConfig = Record<string, string | number | boolean | null | undefined>

export type JarvisObserveState = {
  active?: boolean
  lane?: 'time' | 'mind' | string
  status?: string
  message?: string
  zerodha_connected?: boolean
  universe?: number
  candidates?: Array<Record<string, unknown>>
  observed_symbols?: string[]
  entries?: Array<Record<string, unknown>>
  alerts?: Array<{
    symbol?: string
    side?: string
    last?: number
    entry?: number
    message?: string
    at?: number
  }>
  round?: number
  observe_until?: number | null
  started_at?: number | null
  updated_at?: number | null
  error?: string | null
  live_ui?: {
    running?: boolean
    phase?: string
    progress?: number
    title?: string
    detail?: string
    scan_log?: Array<Record<string, unknown>>
    decisions?: Array<Record<string, unknown>>
    alerts?: Array<{
      symbol?: string
      side?: string
      last?: number
      entry?: number
      message?: string
      at?: number
    }>
    picked?: Record<string, unknown> | null
    charts?: {
      focus?: Record<string, unknown>
      activity?: Record<string, unknown>
      mode?: string
    } | null
    execution?: Array<{ step?: string; message?: string }>
  }
}

export interface JarvisSnapshot {
  mode?: string
  day_pnl?: number
  unrealized_pnl?: number
  groww?: {
    connected?: boolean
    positions?: unknown[]
    orders?: unknown[]
    updated_at?: number | null
    error?: string
    position_count?: number
    order_count?: number
  }
  last_run?: JarvisRunResult | null
  candidates?: { longs?: JarvisCandidate[]; shorts?: JarvisCandidate[]; regime?: string }
  tape?: Array<Record<string, unknown>>
  config?: JarvisConfig
  observe?: JarvisObserveState
}

export interface JarvisCandidate {
  symbol?: string
  side?: string
  score?: number
  strategy?: string
  label?: string
  entry?: number
  sl?: number
  tp?: number
  rr?: number
  atr_pct?: number
  verdict?: string
}

export interface JarvisRunResult {
  agent?: string
  regime?: string
  ai_summary?: string
  claude_provider?: string
  candidates?: { longs?: JarvisCandidate[]; shorts?: JarvisCandidate[]; regime?: string }
  intents?: JarvisCandidate[]
  groww?: JarvisSnapshot['groww']
  errors?: string[]
  meta?: Record<string, unknown>
  parallel?: string
  elapsed_ms?: number
  config?: JarvisConfig
}

export async function fetchJarvisStatus(username: string) {
  const { data } = await api.get<{ ok: boolean; snapshot: JarvisSnapshot; config: JarvisConfig }>(
    '/jarvis/status',
    { params: { username } },
  )
  return data
}

export async function fetchJarvisConfig(username: string) {
  const { data } = await api.get<{ ok: boolean; config: JarvisConfig }>('/jarvis/config', {
    params: { username },
  })
  return data
}

export async function updateJarvisConfig(username: string, patch: JarvisConfig) {
  const { data } = await api.put<{ ok: boolean; config: JarvisConfig }>(
    '/jarvis/config',
    { patch },
    { params: { username } },
  )
  return data
}

export async function runJarvisAgent(username: string) {
  const { data } = await api.post<JarvisRunResult & { ok: boolean }>('/jarvis/run', null, {
    params: { username },
    timeout: 300_000,
  })
  return data
}

export async function refreshJarvisGroww(username: string) {
  const { data } = await api.post<{ ok: boolean; groww: JarvisSnapshot['groww'] }>(
    '/jarvis/groww/refresh',
    null,
    { params: { username } },
  )
  return data
}

export function getJarvisWsUrl(username?: string): string {
  const user = encodeURIComponent(username || 'leninstark')
  const base = api.defaults.baseURL || '/api'
  try {
    if (base.startsWith('http')) {
      const u = new URL(base)
      const proto = u.protocol === 'https:' ? 'wss:' : 'ws:'
      return `${proto}//${u.host}/api/jarvis/ws?username=${user}`
    }
  } catch {
    /* fall through */
  }
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/api/jarvis/ws?username=${user}`
}

export async function fetchJarvisTestState(username: string) {
  const { data } = await api.get<{
    ok: boolean
    sim: Record<string, unknown>
    graph: Array<{ id: string; label: string }>
    snapshot: JarvisSnapshot
    config: JarvisConfig
  }>('/jarvis/test/state', { params: { username } })
  return data
}

export async function jarvisTestReset(username: string) {
  const { data } = await api.post('/jarvis/test/reset', null, { params: { username } })
  return data
}

export async function jarvisTestArm(username: string, mode = 'PAPER') {
  const { data } = await api.post('/jarvis/test/arm', { mode }, { params: { username } })
  return data
}

export async function jarvisTestMockGroww(username: string) {
  const { data } = await api.post('/jarvis/test/mock-groww', null, { params: { username } })
  return data
}

export async function jarvisTestRunAgent(username: string) {
  const { data } = await api.post<JarvisRunResult & { ok: boolean; sim?: Record<string, unknown> }>(
    '/jarvis/test/run-agent',
    null,
    { params: { username }, timeout: 300_000 },
  )
  return data
}

export async function jarvisTestPaperExec(username: string, side: 'LONG' | 'SHORT' = 'LONG') {
  const { data } = await api.post('/jarvis/test/paper-exec', { side }, { params: { username } })
  return data
}

export async function jarvisTestHitSl(username: string, symbol?: string) {
  const { data } = await api.post('/jarvis/test/hit-sl', { symbol: symbol || null }, { params: { username } })
  return data
}

export async function jarvisTestHitTp(username: string, symbol?: string) {
  const { data } = await api.post('/jarvis/test/hit-tp', { symbol: symbol || null }, { params: { username } })
  return data
}

export async function jarvisTestScenario(username: string) {
  const { data } = await api.post('/jarvis/test/scenario', null, {
    params: { username },
    timeout: 300_000,
  })
  return data
}

export async function jarvisTestPackInfo(username: string) {
  const { data } = await api.get('/jarvis/test/pack', { params: { username } })
  return data
}

export async function jarvisTestPackLoad(username: string) {
  const { data } = await api.post('/jarvis/test/pack/load', null, { params: { username } })
  return data
}

export async function jarvisTestPackReplaySample(username: string) {
  const { data } = await api.post('/jarvis/test/pack/replay-sample', null, {
    params: { username },
    timeout: 120_000,
  })
  return data
}

export async function jarvisTestPackRun(
  username: string,
  opts?: { use_claude?: boolean; pace?: number },
) {
  const { data } = await api.post(
    '/jarvis/test/pack/run',
    { use_claude: opts?.use_claude ?? true, pace: opts?.pace ?? 0.08 },
    { params: { username } },
  )
  return data
}

export async function fetchJarvisThink(username: string) {
  const { data } = await api.get<{
    ok: boolean
    think: Record<string, unknown>
    sim: Record<string, unknown>
    snapshot: JarvisSnapshot
    watch?: { symbols?: string[]; plans?: Record<string, unknown> }
  }>('/jarvis/test/think', { params: { username } })
  return data
}

export async function jarvisWatchAdd(username: string, symbol: string) {
  const { data } = await api.post('/jarvis/watch/add', { symbol }, { params: { username } })
  return data
}

export async function jarvisWatchRemove(username: string, symbol: string) {
  const { data } = await api.post('/jarvis/watch/remove', { symbol }, { params: { username } })
  return data
}

export async function jarvisWatchAnalyse(username: string, mode: 'both' | 'user' | 'pack' = 'both') {
  const { data } = await api.post('/jarvis/watch/analyse', null, {
    params: { username, mode },
    timeout: 300_000,
  })
  return data
}

export async function fetchJarvisObserve(username: string) {
  const { data } = await api.get<{ ok: boolean; observe: JarvisObserveState }>('/jarvis/observe', {
    params: { username },
  })
  return data
}

export async function startJarvisObserve(
  username: string,
  lane: 'time' | 'mind',
  symbols?: string[],
) {
  const { data } = await api.post<{ ok: boolean; error?: string; observe: JarvisObserveState }>(
    '/jarvis/observe/start',
    { lane, symbols: symbols || [] },
    { params: { username }, timeout: 300_000 },
  )
  return data
}

export async function stopJarvisObserve(username: string) {
  const { data } = await api.post<{ ok: boolean; observe: JarvisObserveState }>(
    '/jarvis/observe/stop',
    null,
    { params: { username } },
  )
  return data
}

export async function focusJarvisObserve(username: string, symbol: string) {
  const { data } = await api.post<{ ok: boolean; observe: JarvisObserveState }>(
    '/jarvis/observe/focus',
    { symbol },
    { params: { username }, timeout: 60_000 },
  )
  return data
}

export async function fetchJarvisMemorySessions(username: string, limit = 40) {
  const { data } = await api.get<{ ok: boolean; sessions: Array<Record<string, unknown>> }>(
    '/jarvis/memory/sessions',
    { params: { username, limit } },
  )
  return data
}

export async function fetchJarvisMemorySession(username: string, sessionId: string, limit = 2000) {
  const { data } = await api.get<{
    ok: boolean
    session_id?: string
    events?: Array<Record<string, unknown>>
    count?: number
    error?: string
  }>(`/jarvis/memory/sessions/${encodeURIComponent(sessionId)}`, {
    params: { username, limit },
  })
  return data
}

/* ─── F&O index study ─── */

export type FnoIndexId = 'NIFTY' | 'BANKNIFTY' | 'SENSEX'

export interface FnoDayRow {
  date: string
  weekday: string
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  volume: number
  change: number | null
  change_pct: number | null
  range_pts: number | null
  gap_pts?: number | null
  gap_pct?: number | null
  metric?: number | null
  metric_name?: string
}

export interface FnoKpi {
  key: string
  label: string
  value: number | null
  display: string
  unit: string
  hint: string
}

export interface FnoPattern {
  id: string
  type: string
  severity: string
  title: string
  summary: string
  day: FnoDayRow | null
  metrics: Record<string, unknown>
}

export interface FnoInterestingNote {
  key: string
  title: string
  text: string
  context: Record<string, unknown>
}

export interface FnoIndexAnalytics {
  id: FnoIndexId
  label: string
  lot_hint: string
  from_date: string
  to_date: string
  sessions: number
  last: FnoDayRow
  period_change_pct: number | null
  kpis: FnoKpi[]
  extremes: Record<string, FnoDayRow | null>
  weekday: Array<{
    weekday: string
    sessions: number
    avg_change_pct: number | null
    avg_range_pts: number | null
    avg_volume: number | null
    green_pct: number | null
  }>
  streaks: {
    longest_green: number
    longest_red: number
    current: { direction: string; length: number } | null
  }
  pattern_counts: Record<string, number>
  patterns: FnoPattern[]
  interesting: FnoInterestingNote[]
  series: Array<{
    date: string
    close: number | null
    volume: number
    change_pct: number | null
    range_pts: number | null
  }>
}

export async function fetchFnoIndex(indexId: FnoIndexId): Promise<FnoIndexAnalytics> {
  const { data } = await api.get<FnoIndexAnalytics>(`/fno/index/${indexId}`, { timeout: 60_000 })
  return data
}

export async function explainFnoMetric(body: {
  index: FnoIndexId
  topic: string
  title?: string
  payload?: Record<string, unknown>
}): Promise<{
  index: string
  topic: string
  title: string
  explanation: string
  source: 'llm' | 'rules'
  provider: string | null
  error: string | null
}> {
  const { data } = await api.post('/fno/explain', body, { timeout: 120_000 })
  return data
}

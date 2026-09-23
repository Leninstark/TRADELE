import type { MyTradeStyleDashboard } from '../api/client'

export type TradeStyle = 'intraday' | 'swing'

export type KpiHealth = 'good' | 'warn' | 'bad' | 'neutral'

export type StyleDashboardSlice = MyTradeStyleDashboard

export type StyleText = string | { intraday: string; swing: string }

export interface KpiDef {
  id: string
  label: string
  section: 'pnl' | 'activity' | 'quality' | 'risk' | 'concentration'
  format: 'currency' | 'percent' | 'number' | 'ratio'
  description: string
  good: StyleText
  warn: StyleText
  bad: StyleText
  evaluate: (value: number | null | undefined, style: TradeStyle) => KpiHealth
}

export function resolveStyleText(text: StyleText, style: TradeStyle): string {
  if (typeof text === 'string') return text
  return text[style]
}

function pnlHealth(v: number): KpiHealth {
  if (v > 0) return 'good'
  if (v === 0) return 'neutral'
  if (v > -1000) return 'warn'
  return 'bad'
}

function higherGood(v: number, goodMin: number, warnMin: number): KpiHealth {
  if (v >= goodMin) return 'good'
  if (v >= warnMin) return 'warn'
  return 'bad'
}

function lowerGood(v: number, goodMax: number, warnMax: number): KpiHealth {
  if (v <= goodMax) return 'good'
  if (v <= warnMax) return 'warn'
  return 'bad'
}

export const KPI_DEFS: KpiDef[] = [
  {
    id: 'today',
    label: 'Today P&L',
    section: 'pnl',
    format: 'currency',
    description: 'Profit or loss from closed trades today for this style.',
    good: 'Positive — you finished green today.',
    warn: 'Small loss — review if rules were followed.',
    bad: 'Large loss — pause and check position size / stop-loss.',
    evaluate: (v, style) => {
      const n = v ?? 0
      const limit = style === 'intraday' ? -1500 : -3000
      if (n > 0) return 'good'
      if (n === 0) return 'neutral'
      if (n > limit) return 'warn'
      return 'bad'
    },
  },
  {
    id: 'mtd',
    label: 'MTD P&L',
    section: 'pnl',
    format: 'currency',
    description: 'Month-to-date profit or loss.',
    good: 'Positive MTD — on track this month.',
    warn: 'Flat or small red — recoverable with discipline.',
    bad: 'Deep red MTD — reduce size or take a break.',
    evaluate: (v) => pnlHealth(v ?? 0),
  },
  {
    id: 'total',
    label: 'Total P&L',
    section: 'pnl',
    format: 'currency',
    description: 'All-time synced P&L for this style since you started daily sync.',
    good: 'Positive overall — edge may exist.',
    warn: 'Near breakeven — need more data or tighter rules.',
    bad: 'Negative overall — strategy or execution needs change.',
    evaluate: (v) => pnlHealth(v ?? 0),
  },
  {
    id: 'avg_daily',
    label: 'Avg daily P&L',
    section: 'pnl',
    format: 'currency',
    description: 'Average P&L per active trading day.',
    good: 'Positive average — consistency building.',
    warn: 'Near zero — break-even trader.',
    bad: 'Negative average — losing day after day.',
    evaluate: (v) => pnlHealth(v ?? 0),
  },
  {
    id: 'best_day',
    label: 'Best day',
    section: 'pnl',
    format: 'currency',
    description: 'Your largest single-day gain.',
    good: 'Healthy wins exist — don’t get overconfident.',
    warn: 'Moderate best day.',
    bad: 'No green days yet.',
    evaluate: (v) => ((v ?? 0) > 0 ? 'good' : 'neutral'),
  },
  {
    id: 'worst_day',
    label: 'Worst day',
    section: 'pnl',
    format: 'currency',
    description:
      'Lowest single-day P&L. If you have no red days yet, this equals your best (or only) day — not a loss.',
    good: 'No losing day yet, or loss stayed small.',
    warn: 'Moderate red day — tighten daily stop.',
    bad: 'Very large loss day — cut size immediately.',
    evaluate: (v, style) => {
      const n = v ?? 0
      // Positive/flat "worst" day = no losses recorded yet
      if (n >= 0) return 'good'
      const loss = Math.abs(n)
      const goodMax = style === 'intraday' ? 800 : 2000
      const warnMax = style === 'intraday' ? 2000 : 5000
      return lowerGood(loss, goodMax, warnMax)
    },
  },
  {
    id: 'green_days_pct',
    label: 'Green days %',
    section: 'pnl',
    format: 'percent',
    description: 'Share of trading days that closed profitable.',
    good: '≥55% — more winning days than losing.',
    warn: '45–54% — okay if wins are bigger than losses.',
    bad: '<45% — too many red days.',
    evaluate: (v) => higherGood(v ?? 0, 55, 45),
  },
  {
    id: 'profit_factor_days',
    label: 'Profit factor (days)',
    section: 'pnl',
    format: 'ratio',
    description: 'Gross profit days ÷ gross loss days. Above 1 means net positive.',
    good: '≥1.5 — strong edge. ∞ = no losing days yet.',
    warn: '1.0–1.5 — barely profitable.',
    bad: '<1.0 — losing overall.',
    evaluate: (v) => {
      if (v == null) return 'good'
      return higherGood(v, 1.5, 1.0)
    },
  },
  {
    id: 'max_drawdown_pnl',
    label: 'Max drawdown',
    section: 'pnl',
    format: 'currency',
    description: 'Largest peak-to-trough drop in cumulative P&L.',
    good: 'Small drawdown — capital preserved.',
    warn: 'Moderate — watch recovery time.',
    bad: 'Large — risk too high for your capital.',
    evaluate: (v, style) => {
      const n = Math.abs(v ?? 0)
      const goodMax = style === 'intraday' ? 3000 : 8000
      const warnMax = style === 'intraday' ? 8000 : 20000
      return lowerGood(n, goodMax, warnMax)
    },
  },
  {
    id: 'symbols_today',
    label: 'Symbols today',
    section: 'activity',
    format: 'number',
    description:
      'How many different stocks you traded today (unique positions). Partial fills of the same stock count as one symbol.',
    good: styleNote('1–5 symbols', '1–3 symbols'),
    warn: styleNote('6–8 symbols', '4–6 symbols'),
    bad: styleNote('>8 — too many names', '>6 — scattered focus'),
    evaluate: (v, style) => {
      const n = v ?? 0
      if (style === 'intraday') return lowerGood(n, 5, 8)
      return lowerGood(n, 3, 6)
    },
  },
  {
    id: 'hits_today',
    label: 'Hits today',
    section: 'activity',
    format: 'number',
    description:
      'How many times you opened & closed a position today. Example: CUPID traded twice = 2 hits. Partial fills do not add hits.',
    good: styleNote('≤5 hits', '≤3 hits'),
    warn: styleNote('6–8 hits', '4–6 hits'),
    bad: styleNote('>8 — overtrading', '>6 — too active'),
    evaluate: (v, style) => {
      const n = v ?? 0
      if (style === 'intraday') return lowerGood(n, 5, 8)
      return lowerGood(n, 3, 6)
    },
  },
  {
    id: 'avg_hits_per_day',
    label: 'Avg hits / day',
    section: 'activity',
    format: 'number',
    description: 'Average position hits per active trading day (not exchange fills).',
    good: styleNote('≤5', '≤2'),
    warn: styleNote('6–8', '3–5'),
    bad: styleNote('>8 overtrading', '>6 too active'),
    evaluate: (v, style) => {
      const n = v ?? 0
      if (style === 'intraday') return lowerGood(n, 5, 8)
      return lowerGood(n, 2, 5)
    },
  },
  {
    id: 'total_hits',
    label: 'Total hits',
    section: 'activity',
    format: 'number',
    description: 'All position hits synced for this style (sum of daily hits).',
    good: 'Enough history to judge patterns.',
    warn: 'Limited sample — don’t over-read stats.',
    bad: 'Very few hits — sync daily to build data.',
    evaluate: (v) => {
      const n = v ?? 0
      if (n >= 10) return 'good'
      if (n >= 3) return 'warn'
      return 'bad'
    },
  },
  {
    id: 'win_rate_pct',
    label: 'Win rate',
    section: 'quality',
    format: 'percent',
    description: '% of closed round-trips that made money.',
    good: styleNote('≥50%', '≥45%'),
    warn: styleNote('40–49%', '35–44%'),
    bad: 'Low win rate — okay only if avg win ≫ avg loss.',
    evaluate: (v, style) => {
      const n = v ?? 0
      if (style === 'intraday') return higherGood(n, 50, 40)
      return higherGood(n, 45, 35)
    },
  },
  {
    id: 'avg_win',
    label: 'Avg win',
    section: 'quality',
    format: 'currency',
    description: 'Average profit on winning closed trades.',
    good: 'Healthy winners — let them run per plan.',
    warn: 'Small winners — targets may be too tight.',
    bad: 'Tiny wins — fees eat your edge.',
    evaluate: (v) => ((v ?? 0) > 200 ? 'good' : (v ?? 0) > 0 ? 'warn' : 'neutral'),
  },
  {
    id: 'avg_loss',
    label: 'Avg loss',
    section: 'quality',
    format: 'currency',
    description: 'Average loss on losing closed trades (negative number).',
    good: 'Small controlled losses.',
    warn: 'Losses growing — review stops.',
    bad: 'Large losses — risk/reward broken.',
    evaluate: (v) => {
      const n = Math.abs(v ?? 0)
      return lowerGood(n, 400, 1000)
    },
  },
  {
    id: 'profit_factor',
    label: 'Profit factor (trades)',
    section: 'quality',
    format: 'ratio',
    description: 'Gross wins ÷ gross losses on closed round-trips.',
    good: '≥1.5 — solid system.',
    warn: '1.0–1.5 — fragile edge.',
    bad: '<1.0 — losing system.',
    evaluate: (v) => {
      if (v == null) return 'good'
      return higherGood(v, 1.5, 1.0)
    },
  },
  {
    id: 'expectancy',
    label: 'Expectancy',
    section: 'quality',
    format: 'currency',
    description: 'Expected ₹ per trade: (win% × avg win) + (loss% × avg loss).',
    good: 'Positive — each trade has positive expectation.',
    warn: 'Near zero — no real edge yet.',
    bad: 'Negative — stop and revisit strategy.',
    evaluate: (v) => pnlHealth(v ?? 0),
  },
  {
    id: 'max_daily_loss',
    label: 'Max daily loss',
    section: 'risk',
    format: 'currency',
    description:
      'Most negative day P&L. Shows ₹0 (or a positive) when you have no red days yet.',
    good: 'No big red day — risk contained.',
    warn: 'Set a hard daily stop below this.',
    bad: 'Blow-up day — mandatory risk review.',
    evaluate: (v, style) => {
      const n = v ?? 0
      if (n >= 0) return 'good'
      const loss = Math.abs(n)
      const goodMax = style === 'intraday' ? 800 : 2000
      const warnMax = style === 'intraday' ? 2000 : 5000
      return lowerGood(loss, goodMax, warnMax)
    },
  },
  {
    id: 'largest_daily_gain',
    label: 'Largest daily gain',
    section: 'risk',
    format: 'currency',
    description: 'Best single day — check if one day drives all profits.',
    good: 'Good days without absurd outliers.',
    warn: 'One big day — verify it’s repeatable.',
    bad: 'No green days recorded.',
    evaluate: (v) => ((v ?? 0) > 0 ? 'good' : 'neutral'),
  },
  {
    id: 'top_symbol_pct',
    label: 'Top symbol concentration',
    section: 'concentration',
    format: 'percent',
    description: '% of total P&L from your best/worst single symbol.',
    good: '≤40% — diversified results.',
    warn: '41–70% — one stock dominates.',
    bad: '>70% — lottery ticket, not a system.',
    evaluate: (v) => lowerGood(Math.abs(v ?? 0), 40, 70),
  },
]

function styleNote(intraday: string, swing: string): StyleText {
  return { intraday, swing }
}

export function getKpiValue(
  data: StyleDashboardSlice,
  kpiId: string,
): number | null {
  const map: Record<string, number | null | undefined> = {
    today: data.pnl.today,
    mtd: data.pnl.mtd,
    total: data.pnl.total,
    avg_daily: data.pnl.avg_daily,
    best_day: data.pnl.best_day,
    worst_day: data.pnl.worst_day,
    green_days_pct: data.pnl.green_days_pct,
    profit_factor_days: data.pnl.profit_factor_days,
    max_drawdown_pnl: data.pnl.max_drawdown,
    trades_today: data.activity.hits_today ?? data.activity.trades_today,
    avg_trades_per_day: data.activity.avg_hits_per_day ?? data.activity.avg_trades_per_day,
    total_trades: data.activity.total_hits ?? data.activity.total_trades,
    symbols_today: data.activity.symbols_today,
    hits_today: data.activity.hits_today,
    avg_hits_per_day: data.activity.avg_hits_per_day,
    total_hits: data.activity.total_hits,
    fill_rate_pct: data.activity.fill_rate_pct,
    win_rate_pct: data.quality.win_rate_pct,
    avg_win: data.quality.avg_win,
    avg_loss: data.quality.avg_loss,
    profit_factor: data.quality.profit_factor,
    expectancy: data.quality.expectancy,
    max_daily_loss: data.risk.max_daily_loss,
    largest_daily_gain: data.risk.largest_daily_gain,
    top_symbol_pct: data.concentration.top_symbol_pct,
  }
  const v = map[kpiId]
  return v == null ? null : v
}

export const KPI_SECTIONS: { key: KpiDef['section']; title: string }[] = [
  { key: 'pnl', title: 'P&L performance' },
  { key: 'activity', title: 'Activity' },
  { key: 'quality', title: 'Trade quality' },
  { key: 'risk', title: 'Risk' },
  { key: 'concentration', title: 'Concentration' },
]

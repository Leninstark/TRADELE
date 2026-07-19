import type { SwingTabId } from '../api/client'

export interface TabHelp {
  summary: string
  metrics: { term: string; meaning: string }[]
}

export const TAB_HELP: Record<SwingTabId, TabHelp> = {
  dashboard: {
    summary:
      'Master view of every Universe stock — live quotes, technicals, delivery, sector rank, and AI trade levels for top picks.',
    metrics: [
      { term: 'Scan', meaning: 'Runs Universe first, then all filter tabs in parallel, then Stock Score, then rebuilds this dashboard.' },
      { term: 'Momentum Score', meaning: 'Weighted 0–100 composite (same formula as Stock Score tab).' },
      { term: 'Rel Strength', meaning: 'Stock 20D return minus Nifty 20D return.' },
      { term: 'AI Remarks', meaning: 'LLM rationale plus entry, stop, and targets for top-ranked stocks.' },
    ],
  },
  stock_score: {
    summary:
      'Composite ranking from saved scan data. Click scan to recalculate — no live fetch, uses whatever tab results exist in DB.',
    metrics: [
      { term: 'Score', meaning: '0–100 weighted total. Only factors with data are included; weights renormalize automatically.' },
      { term: 'Rank', meaning: 'Position vs all Universe stocks by total score.' },
      { term: 'Breakdown', meaning: 'Per-factor sub-scores (0–100) from available tab data.' },
    ],
  },
  universe: {
    summary:
      'Your starting watchlist. Scans mid & small cap stocks that pass quality filters — liquid, sizeable, and actively traded.',
    metrics: [
      { term: 'Market Cap', meaning: 'Total company value in ₹ Crore. Filters out very small companies.' },
      { term: 'Avg Vol', meaning: 'Average shares traded per day (20 days). Higher = easier to buy/sell.' },
      { term: 'Delivery %', meaning: 'Share of volume taken as delivery (not intraday). Higher often means investors are holding.' },
      { term: 'Circuit', meaning: 'Stock hit upper/lower price limit today. Excluded — hard to trade.' },
    ],
  },
  price_momentum: {
    summary:
      'Finds stocks already moving up strongly. Price is above key averages and near its yearly high — trend is your friend.',
    metrics: [
      { term: '5D / 10D / 20D %', meaning: 'Price gain over the last 5, 10, or 20 trading days.' },
      { term: 'EMA 20 / 50', meaning: '20- or 50-day exponential moving average. Price above = short-term uptrend.' },
      { term: 'From 52W H', meaning: 'How far below the 52-week high. Under 10% = trading near its yearly peak.' },
    ],
  },
  volume_explosion: {
    summary:
      'Spots unusual trading activity — where momentum often starts. Today’s volume is much higher than normal.',
    metrics: [
      { term: 'Vol Ratio', meaning: "Today's volume ÷ 20-day average. 2x = double normal; 3x+ = very strong interest." },
      { term: 'Vol Trend', meaning: '5-day average volume ÷ 20-day average. Above 1 = volume is building up.' },
      { term: 'Today Vol', meaning: 'Shares traded today.' },
      { term: '5D / 20D Avg', meaning: 'Average daily volume over the last 5 or 20 days.' },
      { term: '3x+', meaning: 'Yes if volume ratio is 3× or more — a strong surge.' },
    ],
  },
  institutional_buying: {
    summary:
      'Looks for signs that big players are accumulating — high delivery, positive money flow, and price holding above trend.',
    metrics: [
      { term: 'Delivery %', meaning: 'NSE delivery share. Above 40% suggests more delivery-based (investor) buying.' },
      { term: 'CMF', meaning: 'Chaikin Money Flow. Above 0 = buying pressure; below 0 = selling pressure.' },
      { term: 'Vol Ratio', meaning: "Today's volume vs 20-day average. Above 1.2x = above-normal activity." },
      { term: 'EMA 20', meaning: '20-day average price. Stock above it = short-term trend is up.' },
    ],
  },
  news_sentiment: {
    summary:
      'Scores news headlines (Moneycontrol, ET, etc.) with AI for each stock — Positive, Neutral, or Negative.',
    metrics: [
      { term: 'Sentiment', meaning: 'AI label: Positive (bullish news), Neutral, or Negative (bearish news).' },
      { term: 'Score', meaning: '0–100 confidence. Higher = stronger signal from headlines.' },
      { term: 'Summary', meaning: 'One-line reason from the news scan.' },
      { term: 'Sources', meaning: 'News outlets that mentioned this stock.' },
    ],
  },
  delivery_percentage: {
    summary:
      'Very underrated signal — rising delivery with higher volume means investors are accumulating, not just day-trading.',
    metrics: [
      { term: 'Delivery %', meaning: 'Today’s NSE delivery share. Must be higher than yesterday and ≥ 35%.' },
      { term: 'Del Δ', meaning: 'Change in delivery % vs yesterday. Rising = more conviction.' },
      { term: 'Vol Today / Yest', meaning: 'Volume today vs yesterday. Both up with delivery = bullish.' },
      { term: 'Relative Strength', meaning: 'Stock 20D return minus Nifty 20D return. +15% = outperforming index.' },
      { term: 'Trend', meaning: 'Price > EMA20 > EMA50 > EMA200 = perfect uptrend alignment.' },
    ],
  },
  sector_strength: {
    summary:
      'Don’t buy the best stock in the worst sector. Prefer names in sectors that are already leading the market.',
    metrics: [
      { term: 'Sector', meaning: 'Industry from index CSV (e.g. Banks, IT, Chemicals).' },
      { term: 'Sector 10D %', meaning: 'Average 10-day return of all universe stocks in that sector.' },
      { term: 'Stock 10D %', meaning: 'This stock’s 10-day return within its sector.' },
      { term: 'Sector Rank', meaning: '1 = strongest sector by 10-day return.' },
    ],
  },
}

/** Short tooltip for a single column header */
export const COLUMN_HELP: Record<SwingTabId, Record<string, string>> = {
  dashboard: {
    rank: 'Overall rank by composite score.',
    symbol: 'NSE trading symbol.',
    company: 'Company name from index CSV.',
    ltp: 'Last traded price from Zerodha.',
    change_pct: 'Day change % from Zerodha quote.',
    return_5d_pct: 'Price change over 5 trading days.',
    return_10d_pct: 'Price change over 10 trading days.',
    return_20d_pct: 'Price change over 20 trading days.',
    volume_ratio: "Today's volume ÷ 20-day average.",
    delivery_pct: 'NSE delivery % (latest bhavcopy).',
    avg_daily_volume: '20-day average daily volume.',
    rsi: '14-period RSI.',
    adx: 'Average Directional Index — trend strength.',
    atr: 'Average True Range — volatility.',
    ema_20: '20-day exponential moving average.',
    ema_50: '50-day EMA.',
    ema_200: '200-day EMA.',
    dist_52w_high_pct: 'Distance below 52-week high.',
    breakout: 'Close at or above 20-day high.',
    relative_strength_pct: 'Stock 20D % minus Nifty 20D %.',
    sector_rank: 'Sector rank by 10-day return (1 = strongest).',
    momentum_score: 'Weighted composite score 0–100.',
    entry_price: 'AI-suggested entry (or ATR-based fallback).',
    stop_loss: 'Suggested stop loss.',
    target_1: 'First profit target.',
    target_2: 'Second profit target.',
    risk_reward: 'Reward-to-risk ratio.',
    confidence: 'AI confidence 0–100.',
    ai_remarks: 'LLM one-line trade rationale.',
  },
  stock_score: {
    rank: 'Rank by total weighted score.',
    symbol: 'NSE symbol.',
    score: 'Total weighted score 0–100.',
    return_20d_pct: '20-day price return.',
    relative_strength_pct: 'Outperformance vs Nifty (20D).',
    volume_ratio: 'Volume vs 20-day average.',
    delivery_pct: 'NSE delivery %.',
    sector_rank: 'Sector strength rank.',
    news_sentiment: 'News sentiment label.',
    score_components: 'Sub-scores per factor before weighting.',
  },
  universe: {
    price: 'Latest traded price (₹).',
    market_cap_cr: 'Company size in ₹ Crore.',
    avg_daily_volume: 'Average daily shares traded (20 days).',
    delivery_pct: 'Delivery volume as % of total — higher = more investor holding.',
    is_circuit: 'Hit price circuit limit today (yes / NO).',
  },
  price_momentum: {
    price: 'Latest close price (₹).',
    return_5d_pct: 'Price change over last 5 trading days.',
    return_10d_pct: 'Price change over last 10 trading days.',
    return_20d_pct: 'Price change over last 20 trading days.',
    dist_52w_high_pct: 'Distance below 52-week high. Lower = closer to peak.',
    ema_20: '20-day exponential moving average.',
    ema_50: '50-day exponential moving average.',
  },
  volume_explosion: {
    price: 'Latest close price (₹).',
    volume_ratio: "Today's volume ÷ 20-day average. 2x = twice normal.",
    volume_trend: '5-day avg volume ÷ 20-day avg. Above 1 = rising activity.',
    today_volume: 'Shares traded in the latest session.',
    vol_5d_avg: 'Average volume over last 5 days.',
    vol_20d_avg: 'Average volume over last 20 days.',
    strong_3x: 'Volume ratio ≥ 3× (strong surge).',
  },
  institutional_buying: {
    price: 'Latest close price (₹).',
    delivery_pct: 'NSE delivery %. Higher = more shares taken for delivery.',
    cmf: 'Chaikin Money Flow. Positive = net buying pressure.',
    volume_ratio: "Today's volume vs 20-day average.",
    ema_20: '20-day EMA — price above = uptrend.',
  },
  news_sentiment: {
    sentiment: 'Positive, Neutral, or Negative from news.',
    score: 'AI confidence 0–100.',
    summary: 'Brief news-based explanation.',
    sources: 'Headline sources used.',
  },
  delivery_percentage: {
    price: 'Latest close price (₹).',
    delivery_pct: 'Today’s NSE delivery %. Higher than yesterday = accumulation.',
    delivery_yesterday_pct: 'Previous session delivery %.',
    delivery_change_pct: 'Today delivery % minus yesterday.',
    volume_today: 'Shares traded today (NSE bhavcopy).',
    volume_yesterday: 'Shares traded yesterday.',
    stock_return_20d_pct: 'Stock price change over 20 trading days.',
    nifty_return_20d_pct: 'Nifty 50 change over same 20 days.',
    relative_strength_pct: 'Stock 20D % − Nifty 20D %. Outperformance vs index.',
    ema_20: '20-day EMA — short-term trend.',
    ema_50: '50-day EMA — medium-term trend.',
    ema_200: '200-day EMA — long-term trend.',
    perfect_trend: 'Price > EMA20 > EMA50 > EMA200.',
  },
  sector_strength: {
    price: 'Latest close price (₹).',
    sector: 'Industry group (Banks, IT, Chemicals, etc.).',
    sector_return_10d_pct: 'Average 10-day return for all stocks in this sector.',
    stock_return_10d_pct: 'This stock’s 10-day return.',
    sector_rank: 'Sector rank by 10-day return (1 = strongest).',
  },
}

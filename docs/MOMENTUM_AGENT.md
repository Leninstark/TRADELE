# LangGraph Momentum Agent

Scans NSE stocks for **30-day momentum** using a LangGraph pipeline + Gemini analysis.

## Pipeline

```
resolve_universe → fetch_30d_data → score_momentum → gemini_analyze
```

### Node 1: Resolve Universe
Caps symbols (`momentum_max_symbols`, default 50) for fast scans. Falls back to sample list if no Kite token.

### Node 2: Fetch Data
Pulls ~40 calendar days of daily OHLCV from Zerodha (cached in Postgres).

### Node 3: Score Momentum
Rule-based score per stock:

| Factor | Weight |
|--------|--------|
| 30-day return | 35% |
| 5-day return (acceleration) | 20% |
| Volume trend (5d vs prior 20d) | 15% |
| EMA20/EMA50 alignment | 15% |
| RSI momentum zone | 10% |
| Green days % | 5% |

Only stocks with **positive 30-day return** are included.

### Node 4: Gemini Analyze
`gemini-flash-latest` ranks top picks with confidence, reasons, risk notes, and hold period.

## API

```http
GET /api/agents/momentum?lookback_days=30&top_n=15&max_symbols=50
POST /api/agents/momentum
```

### Response

```json
{
  "agent": "momentum_30d",
  "lookback_days": 30,
  "ai_summary": "...",
  "picks": [
    {
      "symbol": "RELIANCE",
      "confidence": 88,
      "rating": "Strong Buy",
      "reasons": ["30-day return +12%", "Volume expanding 1.8x"],
      "risk": "Extended from 30d high",
      "return_30d_pct": 12.5,
      "hold_period": "2-4 weeks"
    }
  ],
  "all_scored": [...],
  "meta": { "universe_size": 50, "fetched": 18, "scored_count": 12 }
}
```

## Config (`.env`)

```
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-flash-latest
KITE_ACCESS_TOKEN=...   # required for live data
MOMENTUM_MAX_SYMBOLS=50
```

## Requirements

- Valid `KITE_ACCESS_TOKEN` for live OHLCV
- `GEMINI_API_KEY` for AI explanations (falls back to rule-only picks)

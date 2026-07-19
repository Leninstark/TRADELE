# Tradele — AI Trading Intelligence Platform

One platform, three trading styles (Intraday · Swing · Positional), powered by a composable rule engine.

## Architecture (8 Modules)

```
TRADELE/
├── engines/
│   ├── market_data/     # Module 1 — live & historical data, indices
│   ├── indicators/      # Module 2 — backend indicator calculations
│   └── scanners/        # Module 3 — AI scanning via rule engine
├── rules/               # Composable conditions → scanners, alerts, AI
├── services/            # Existing: Zerodha, news, notifications
├── api/routes/          # REST endpoints
└── scheduler/           # EOD + pre-market jobs

UI/                      # React dashboard (AG Grid + charts)
```

### Phase 1 (MVP) — In Progress

- [x] Rule engine with reusable conditions
- [x] Technical indicator engine (EMA, RSI, MACD, ADX, ATR, BB, VWAP, etc.)
- [x] Swing / Intraday / Positional scanners
- [x] Dashboard API + React UI
- [x] CORS for local dev
- [ ] KiteTicker WebSocket streaming
- [ ] User-configurable alert rules
- [ ] TimescaleDB / Redis

### Phase 2

- AI explanations (stop loss, targets, R:R)
- News + fundamental synthesis
- Portfolio sync from Zerodha
- Backtesting

### Phase 3

- AI chat assistant
- No-code strategy builder
- ML ranking engine

## Quick Start

```bash
# Backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # configure Kite + Postgres
uvicorn TRADELE.main:app --reload --port 8000

# Frontend
cd UI && npm install && npm run dev
```

- API: http://localhost:8000/docs
- UI: http://localhost:5173

## New API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/dashboard` | Full morning dashboard payload |
| `GET /api/scanners/strategies` | List scanner strategies |
| `GET /api/scanners/run?style=swing` | Run scanners for a style |
| `GET /api/indicators/{symbol}` | All indicators for a symbol |

## Rule Engine

Every scanner is a set of composable conditions:

```python
Condition(
    field="ema_20",
    operator=Operator.CROSS_ABOVE,
    ref_field="ema_50",
    reason_template="EMA20 crossed above EMA50",
)
```

Add new strategies in `TRADELE/rules/registry.py` without changing scanner logic.

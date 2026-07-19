# AI Trading Intelligence Platform — Frontend

React dashboard for the Tradele platform.

## Stack

- React + TypeScript (Vite)
- AG Grid — scanner results tables
- TradingView Lightweight Charts (Phase 1b — stock detail charts)
- Axios — API client (proxied to FastAPI)

## Run

```bash
# Terminal 1 — backend
cd ..
source .venv/bin/activate
uvicorn TRADELE.main:app --reload --port 8000

# Terminal 2 — frontend
cd UI
npm install
npm run dev
```

Open http://localhost:5173

## Pages

| Route | Description |
|-------|-------------|
| `/` | Morning dashboard — market overview, top swing picks, intraday counts |
| `/scanners` | Run intraday / swing / positional scanners |
| `/alerts` | Latest EOD and pre-market alerts |

## API

The dev server proxies `/api/*` to `http://localhost:8000`.

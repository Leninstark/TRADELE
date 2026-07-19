# Tradele – AI Trading Intelligence Platform

One platform, three trading styles: **Intraday** · **Swing** · **Positional**.

Backend API + React dashboard powered by a composable rule engine.

## Features

- **Universe**: NSE equity, with filters for penny/small-cap (configurable).
- **Scoring**: Rule-based intraday signals (20D breakout/breakdown, volume spike 2×, MA trend, RSI, gap).
- **Alerts**: Top 10 long + top 10 short with reasons and key levels.
- **News**: Aggregated from free RSS (Moneycontrol, ET, Business Standard, Livemint, NDTV).
- **LLM**: Optional – you can plug in your LLM API for an AI summary (set `OPENAI_API_KEY` or custom endpoint).
- **Notifications**: Telegram + email (configurable).
- **Schedule**: EOD scan 4:00 PM IST, morning alert 9:25 AM IST.
- **Audit**: All alerts stored in Postgres.

## Requirements

- Python 3.11+
- Postgres
- Zerodha Kite API (historical + instruments)
- Optional: Telegram bot token, SMTP for email, OpenAI (or compatible) API for LLM

## Setup (Mac / Linux)

1. **Clone / create project and venv**

   ```bash
   cd TRADELE
   python3.11 -m venv .venv
   source .venv/bin/activate  # on Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Postgres**

   Create a database and set `DATABASE_URL` in `.env`:

   ```bash
   createdb tradele
   cp .env.example .env
   # Edit .env: DATABASE_URL=postgresql://user:password@localhost:5432/tradele
   ```

3. **Zerodha Kite**

   - Register app at [kite.zerodha.com](https://kite.zerodha.com), get API key and secret.
   - In `.env`: `KITE_API_KEY`, `KITE_API_SECRET`.
   - Login once to get `request_token`, then exchange for access token:
     - Open: `http://localhost:8000/api/zerodha/login-url` → copy `login_url` → open in browser → after login you get `?request_token=...` in redirect URL.
     - Call: `GET /api/zerodha/session?request_token=YOUR_REQUEST_TOKEN`
     - Put the returned `access_token` in `.env` as `KITE_ACCESS_TOKEN`.
   - Token expires daily; repeat when needed or automate per Zerodha docs.

4. **Optional: Telegram**

   - Create bot via @BotFather, get token. Add token to `.env` as `TELEGRAM_BOT_TOKEN`.
   - Get your chat id (e.g. message the bot, then `getUpdates`). Set `TELEGRAM_CHAT_ID` in `.env`.

5. **Optional: Email**

   - Set `SMTP_*` and `ALERT_EMAIL_TO` in `.env`.

6. **Optional: LLM**

   - Set `OPENAI_API_KEY` (and optionally `LLM_BASE_URL` for a custom endpoint).

## Run

**Backend**

```bash
 source .venv/bin/activate
 uvicorn TRADELE.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend (UI)**

```bash
 cd UI && npm install && npm run dev
```

- API: http://localhost:8000  
- Docs: http://localhost:8000/docs  
- Dashboard UI: http://localhost:5173

Tables are created on first run (SQLAlchemy `create_all`).

## Data APIs

**News (unified – LangGraph agent)**  
- `GET /api/news` – **single endpoint**: fetches all important India market-impact news and runs a LangGraph agent to produce an LLM summary with **impact for tomorrow** (themes, sectors/stocks that may move up or down). Returns `news_items`, `impact_summary`, `stocks_impact` (positive/negative with reasons). Requires `OPENAI_API_KEY` for the summary.  
- `GET /api/news?skip_agent=true` – same news items only, no LLM (raw headlines).  
- `GET /api/news/sources` – list configured RSS sources (India-focused).  
- `GET /api/news/symbol/{symbol}` – news mentioning a symbol (e.g. RELIANCE).  

**Screener.in (Apify)** – requires `APIFY_API_TOKEN`  
- `GET /api/screener?mode=runQuery&query_string=...` – run Screener query (e.g. Market Cap > 50000); default query if omitted  
- `GET /api/screener?mode=getstockdetails&url=https://www.screener.in/company/RELIANCE/` – company details from Screener.in  

**Market (Kite / NSE)** – require valid `KITE_ACCESS_TOKEN`  
- `GET /api/market/historical` – OHLCV candles: `symbol`, `exchange`, `interval` (e.g. day, 5minute), `from_date`, `to_date`, `use_cache`  
- `GET /api/market/quote?instruments=NSE:RELIANCE,NSE:INFY` – live quote  
- `GET /api/market/ltp/{exchange}/{symbol}` – last traded price  
- `GET /api/market/instruments` – list instruments (optional `exchange`, `segment`)  

**Dashboard & Scanners (new)**  
- `GET /api/dashboard` – morning dashboard: indices, top swing picks, scanner counts  
- `GET /api/scanners/strategies?style=swing` – list rule-engine strategies  
- `GET /api/scanners/run?style=intraday` – run scanners and get ranked matches  
- `GET /api/indicators/{symbol}` – all technical indicators for a symbol  

## Manual triggers

- `POST /api/scan/eod` – run EOD scan now.
- `POST /api/scan/morning` – run morning alert now.

## Config (`.env`)

| Variable | Description |
|----------|-------------|
| `KITE_API_KEY` / `KITE_API_SECRET` / `KITE_ACCESS_TOKEN` | Zerodha Kite |
| `DATABASE_URL` | Postgres connection string |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Telegram alerts |
| `SMTP_*` / `ALERT_EMAIL_TO` | Email alerts |
| `OPENAI_API_KEY` / `LLM_BASE_URL` | Optional LLM |
| `APIFY_API_TOKEN` | Optional; Screener.in via [Apify](https://apify.com/shashwattrivedi/screener-in) |
| `min_price` / `max_price` / `min_avg_volume` | Filters (optional) |
| `exclude_small_cap` / `nifty_500_only` | Universe filters (optional) |

## Disclaimer

This app is for notifications and research only. It is not investment advice. Past performance and signals do not guarantee future results. You are responsible for your own trading decisions; execute trades manually (e.g. on Groww) at your own risk.

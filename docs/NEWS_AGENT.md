# News impact agent (LangGraph)

Single news flow: **fetch all important India market-impact news → LLM summary with impact for tomorrow**.

## What it does

1. **Fetch** – Aggregates headlines from all configured RSS sources (Moneycontrol, ET, Business Standard, Livemint, NDTV) with **no symbol filter**, so you get macro, policy, sector, and market-moving news.
2. **Summarize** – A LangGraph agent runs the headlines through an LLM that:
   - Summarizes key themes in 2–3 sentences.
   - Deduces **impact for tomorrow**: which sectors or stocks may move **up** or **down** and why (India NSE/BSE context).
   - Returns structured `positive` / `negative` lists (symbol or sector + reason) plus a text summary.

## API

- **`GET /api/news`** – Runs the full agent. Response:
  - `news_items`: list of `{ title, link, source, published, summary }`
  - `impact_summary`: string (themes + tomorrow’s impact)
  - `stocks_impact`: `{ "positive": [...], "negative": [...], "market_take": "..." }`
  - **`stocks_list`** (for UI): array of `{ "stock_name", "direction" ("up"|"down"), "reason", "what_news_says", "source" }` – one row per stock/sector with news-driven impact and source.
- **`GET /api/news?skip_agent=true`** – Same news items only; no LLM (no impact summary).

## Graph (LangGraph)

- **State:** `news_items`, `impact_summary`, `stocks_impact`
- **Nodes:**
  1. `fetch_news` – calls `aggregate_news(symbols=None)`, fills `news_items`
  2. `summarize_impact` – builds prompt from headlines, calls LLM, parses JSON into `impact_summary` and `stocks_impact`
- **Edges:** START → fetch_news → summarize_impact → END

## Requirements

- **LangGraph:** `pip install langgraph` (in `requirements.txt`)
- **Summarisation:** **Gemini Pro** (preferred): set `GEMINI_API_KEY` in `.env` (from [Google AI Studio](https://aistudio.google.com/apikey)). Install: `pip install google-generativeai`. If not set, falls back to OpenAI via `OPENAI_API_KEY`.

If LangGraph is not installed, the agent falls back to fetching news and an optional one-shot LLM summary (no graph).

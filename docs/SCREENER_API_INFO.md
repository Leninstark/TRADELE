# Screener.in API – What You Get

Tradele uses the [Screener.in Apify actor](https://apify.com/shashwattrivedi/screener-in). Set `APIFY_API_TOKEN` in `.env` (from Apify Console → Settings → Integrations).

---

## 1. Mode: `runQuery` (screen stocks by criteria)

**Endpoint:** `GET /api/screener?mode=runQuery&query_string=...`

**Input:**
- `query_string` – Screener.in-style filter, e.g.  
  `Market Capitalization > 50000 AND Price to Earning < 20`  
  `ROE > 20 AND Debt to Equity < 0.5`  
  `Sales Growth > 25 AND Current Ratio > 1.5`
- Optional: `username` / `password` for Screener.in (if the actor requires login for some queries).

**What you get:** A **list of companies** matching the filter, with **key metrics** per company. Typical fields (exact keys depend on the actor output):
- Company name, symbol, sector
- Market cap, price
- P/E, P/B, ROE, ROCE
- Sales growth, profit growth
- Debt/equity, current ratio
- Other ratios and metrics exposed by Screener.in for that screen

Use this to get a **symbol list + fundamentals** for alerts, scoring, or feeding into the LLM (e.g. market-impact news + “top screened stocks” context).

---

## 2. Mode: `getstockdetails` (one company deep-dive)

**Endpoint:** `GET /api/screener?mode=getstockdetails&url=https://www.screener.in/company/RELIANCE/`

**Input:**
- `url` – Full Screener.in company page URL, e.g.  
  `https://www.screener.in/company/RELIANCE/`  
  `https://www.screener.in/company/TCS/consolidated/`

**What you get:** A **detailed financial profile** for that company, typically including:
- **Financial statements** – P&L, Balance Sheet, Cash Flow (as structured by the actor)
- **Key ratios** – P/E, P/B, ROE, ROCE, margins, etc.
- **Peer comparisons** – vs other companies in the same sector
- **Shareholding pattern** – promoter, FII, DII, public, etc.
- **Historical financial data** – if the actor includes it

Use this for single-stock research or to enrich a symbol with fundamentals before alerts/analysis.

---

## Summary

| Mode             | Use case                    | Typical output                          |
|------------------|-----------------------------|-----------------------------------------|
| `runQuery`       | Screen by liquidity/ratios  | List of symbols + key metrics           |
| `getstockdetails`| One company deep-dive       | Full profile, peers, shareholding, ratios |

All data is sourced from Screener.in; the actor returns it as **structured JSON** in the Apify dataset. The exact field names can vary by actor version – inspect a sample run in [Apify Console](https://console.apify.com) or the response of `GET /api/screener` to see the current schema.

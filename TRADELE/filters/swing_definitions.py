"""Swing tab filter definitions and UI tooltip text."""
from __future__ import annotations

from typing import Any

TAB_UNIVERSE = "universe"
TAB_DASHBOARD = "dashboard"
TAB_STOCK_SCORE = "stock_score"
TAB_PRICE_MOMENTUM = "price_momentum"
TAB_VOLUME_EXPLOSION = "volume_explosion"
TAB_INSTITUTIONAL = "institutional_buying"
TAB_NEWS_SENTIMENT = "news_sentiment"
TAB_DELIVERY_PERCENTAGE = "delivery_percentage"
TAB_SECTOR_STRENGTH = "sector_strength"

SWING_TABS = (
    TAB_DASHBOARD,
    TAB_STOCK_SCORE,
    TAB_UNIVERSE,
    TAB_PRICE_MOMENTUM,
    TAB_VOLUME_EXPLOSION,
    TAB_INSTITUTIONAL,
    TAB_NEWS_SENTIMENT,
    TAB_DELIVERY_PERCENTAGE,
    TAB_SECTOR_STRENGTH,
)

PARALLEL_SCAN_TABS = (
    TAB_PRICE_MOMENTUM,
    TAB_VOLUME_EXPLOSION,
    TAB_INSTITUTIONAL,
    TAB_NEWS_SENTIMENT,
    TAB_DELIVERY_PERCENTAGE,
    TAB_SECTOR_STRENGTH,
)

TAB_FILTER_TOOLTIPS: dict[str, list[str]] = {
    TAB_DASHBOARD: [
        "2-week swing board — top 20 by estimated upside %",
        "Ranked by 14-day profit potential (ATR + momentum; Gemini when available)",
        "+20% conviction is highlighted — lower estimates still appear in the top 20",
        "Click a Symbol for full AI thesis, trade plan, and metric breakdown",
        "Scan runs Universe → filter tabs → Stock Score → rebuilds this board",
    ],
    TAB_STOCK_SCORE: [
        "Weighted composite score (0–100) across 10 factors",
        "Recalculates from saved DB data — no live fetch",
        "Uses whatever tab results exist (Universe, filters, Dashboard)",
        "Weights renormalized for available factors only",
        "Click scan to recalculate after other tabs run",
    ],
    TAB_UNIVERSE: [
        "Mid cap & Small cap only",
        "Price > ₹100",
        "Market Cap > ₹3,000 Cr",
        "Avg Daily Volume > 5 lakh shares",
        "Delivery % > 35%",
        "Circuit stocks excluded",
    ],
    TAB_PRICE_MOMENTUM: [
        "5 Day Return > 5%",
        "10 Day Return > 8%",
        "20 Day Return > 15%",
        "Current Price above 20 EMA",
        "Current Price above 50 EMA",
        "Close near 52 Week High (<10% away)",
        "Runs on Universe scan symbols",
    ],
    TAB_VOLUME_EXPLOSION: [
        "Today's Volume / 20 Day Avg Volume > 2x",
        "3x volume flagged as strong",
        "5 Day Avg Volume > 20 Day Avg Volume",
        "Runs on Universe scan symbols",
    ],
    TAB_INSTITUTIONAL: [
        "Delivery % > 40% (NSE bhavcopy)",
        "Chaikin Money Flow (CMF) > 0",
        "Price above 20 EMA",
        "Volume ratio > 1.2x",
        "FII / MF / Promoter holdings: NSE data pending",
    ],
    TAB_NEWS_SENTIMENT: [
        "Sources: Moneycontrol, Economic Times, Business Standard, Livemint",
        "NSE announcements, results, bulk/block deals (via headlines)",
        "LLM scores: Positive / Neutral / Negative",
        "Runs on Universe scan symbols",
    ],
    TAB_DELIVERY_PERCENTAGE: [
        "Today delivery % > yesterday delivery %",
        "Today volume > yesterday volume (rising interest)",
        "Delivery % today ≥ 35%",
        "Relative Strength: Stock 20D return − Nifty 20D return ≥ 5%",
        "Perfect trend: Price > EMA20 > EMA50 > EMA200",
        "Runs on Universe scan symbols",
    ],
    TAB_SECTOR_STRENGTH: [
        "Sector return = avg 10-day return of stocks in same Industry",
        "Industry from Midcap/Smallcap index CSVs",
        "Only stocks in top-performing sectors (top half by return)",
        "Prefer strongest sector + strong stock within sector",
        "Runs on Universe scan symbols",
    ],
}


def filter_tooltip_dict(tab: str) -> dict[str, Any]:
    lines = TAB_FILTER_TOOLTIPS.get(tab, [])
    return {
        "tab": tab,
        "title": tab.replace("_", " ").title(),
        "conditions": lines,
    }

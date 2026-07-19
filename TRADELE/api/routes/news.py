"""Unified news API: LangGraph agent fetches all India market-impact news and LLM summary for tomorrow."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from TRADELE.services.news_aggregator import SOURCES, NewsItem, aggregate_news, news_for_symbol
from TRADELE.services.news_agent import run_news_agent

router = APIRouter()


def _news_item_to_dict(n: NewsItem) -> dict:
    return {
        "title": n.title,
        "link": n.link,
        "source": n.source,
        "published": n.published.isoformat() if n.published else None,
        "summary": n.summary,
    }


@router.get("/sources")
def list_news_sources():
    """List configured RSS sources used for harvesting (India-focused)."""
    return {
        "sources": [{"name": name, "url": url} for name, url in SOURCES],
        "count": len(SOURCES),
    }


@router.get("")
def get_news_impact_tomorrow(
    skip_agent: bool = Query(
        False,
        description="If true, return only raw news items without running the LLM agent (no impact summary).",
    ),
):
    """
    Single unified news API: fetches all important news that may affect Indian stock prices today,
    then runs a LangGraph agent to produce an LLM-based summary with impact for TOMORROW.
    Returns: news_items (headlines from all sources), impact_summary (themes + tomorrow's impact),
    stocks_impact (positive / negative sectors or stocks with reasons).
    """
    if skip_agent:
        items = aggregate_news(symbols=None)[:50]
        return {
            "news_items": [_news_item_to_dict(n) for n in items],
            "impact_summary": None,
            "stocks_impact": None,
            "stocks_list": None,
            "message": "Agent skipped; raw news only.",
        }
    result: dict[str, Any] = run_news_agent()
    return {
        "news_items": result.get("news_items") or [],
        "impact_summary": result.get("impact_summary") or "",
        "stocks_impact": result.get("stocks_impact") or {},
        "stocks_list": result.get("stocks_list") or [],
    }


@router.get("/symbol/{symbol}")
def news_by_symbol(
    symbol: str,
    limit: int = Query(30, ge=1, le=100),
):
    """Get news items that mention the given symbol (e.g. RELIANCE, INFY). Optional filter."""
    items = news_for_symbol(symbol.upper())[:limit]
    return {
        "symbol": symbol.upper(),
        "count": len(items),
        "items": [_news_item_to_dict(n) for n in items],
    }

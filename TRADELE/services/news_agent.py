"""
LangGraph agent: fetch all India market-impact news and produce LLM summary for tomorrow's impact.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from TRADELE.config import settings
from TRADELE.services.news_aggregator import NewsItem, aggregate_news
from TRADELE.services.llm_agent import call_gemini, call_llm

logger = logging.getLogger(__name__)

try:
    from langgraph.graph import StateGraph, START, END
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    StateGraph = None
    START = END = None

try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict


class NewsAgentState(TypedDict, total=False):
    """State for the news impact agent."""
    news_items: list[dict[str, Any]]
    impact_summary: str
    stocks_impact: dict[str, Any]
    stocks_list: list[dict[str, Any]]  # UI: stock_name, direction, reason, what_news_says, source


def _news_to_dict(n: NewsItem) -> dict[str, Any]:
    return {
        "title": n.title,
        "link": n.link,
        "source": n.source,
        "published": n.published.isoformat() if n.published else None,
        "summary": n.summary,
    }


def node_fetch_news(state: dict[str, Any]) -> dict[str, Any]:
    """Fetch all important India market-impact news (no symbol filter)."""
    items = aggregate_news(symbols=None)
    # Cap for LLM context
    items = items[:50]
    news_dicts = [_news_to_dict(n) for n in items]
    return {"news_items": news_dicts}


def _extract_json(raw: str) -> str:
    """Strip markdown code blocks if present."""
    raw = raw.strip()
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].replace("json", "").strip()
    return raw


def node_summarize_impact(state: dict[str, Any]) -> dict[str, Any]:
    """LLM (Gemini Pro preferred): deduce impact for tomorrow; return UI-ready list: stock_name, direction, reason, what_news_says, source."""
    news_items = state.get("news_items") or []
    if not news_items:
        return {"impact_summary": "No news items to summarize.", "stocks_impact": {}, "stocks_list": []}

    lines = [
        "You are an expert analyst for Indian stock markets (NSE/BSE).",
        "Below are today's important financial and market news headlines that can affect stock prices in India.",
        "For each piece of news that implies a specific stock or sector will likely go UP or DOWN tomorrow, output one entry.",
        "Use Indian NSE stock names or sectors (e.g. RELIANCE, HDFCBANK, Bank Nifty, IT sector, FMCG).",
        "",
        "## Today's headlines (source, title, summary)",
    ]
    for i, n in enumerate(news_items[:35], 1):
        lines.append(f"{i}. SOURCE: {n.get('source', '')}")
        lines.append(f"   TITLE: {n.get('title', '')}")
        if n.get("summary"):
            lines.append(f"   SUMMARY: {str(n['summary'])[:200]}")
        lines.append("")
    lines.append(
        "Respond with ONLY a valid JSON array (no markdown, no other text). Each element must have exactly: "
        '"stock_name" (string, NSE symbol or sector name), '
        '"direction" (string, either "up" or "down"), '
        '"reason" (string, one line why), '
        '"what_news_says" (string, brief quote or gist from the news), '
        '"source" (string, the news source name e.g. Moneycontrol, Economic Times). '
        "Example: [{\"stock_name\": \"RELIANCE\", \"direction\": \"up\", \"reason\": \"Strong demand\", \"what_news_says\": \"...\", \"source\": \"Moneycontrol\"}]"
    )
    prompt = "\n".join(lines)
    raw = call_gemini(prompt) if getattr(settings, "gemini_api_key", None) else None
    if not raw:
        raw = call_llm(prompt)
    if not raw:
        return {
            "impact_summary": "LLM not configured or call failed.",
            "stocks_impact": {},
            "stocks_list": [],
        }
    raw = _extract_json(raw)
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            stocks_list = data
        elif isinstance(data, dict) and "stocks" in data:
            stocks_list = data["stocks"]
        elif isinstance(data, dict):
            stocks_list = (data.get("positive") or []) + (data.get("negative") or [])
            for i, s in enumerate(stocks_list):
                if isinstance(s, dict) and "direction" not in s:
                    s["direction"] = "up" if i < len(data.get("positive") or []) else "down"
        else:
            stocks_list = []
        # Normalise to UI shape: stock_name, direction, reason, what_news_says, source
        out_list = []
        for s in stocks_list:
            if not isinstance(s, dict):
                continue
            out_list.append({
                "stock_name": s.get("stock_name") or s.get("symbol_or_sector") or s.get("symbol") or "—",
                "direction": (s.get("direction") or "up").lower() if str(s.get("direction", "")).lower() in ("up", "down") else "up",
                "reason": s.get("reason") or s.get("reasoning") or "",
                "what_news_says": s.get("what_news_says") or s.get("summary") or "",
                "source": s.get("source") or "",
            })
        impact_summary = "Summary based on today's news; impact inferred for tomorrow's session."
        stocks_impact = {
            "positive": [x for x in out_list if x.get("direction") == "up"],
            "negative": [x for x in out_list if x.get("direction") == "down"],
            "market_take": impact_summary,
        }
        return {"impact_summary": impact_summary, "stocks_impact": stocks_impact, "stocks_list": out_list}
    except json.JSONDecodeError:
        return {"impact_summary": raw[:500], "stocks_impact": {}, "stocks_list": []}


def build_news_agent():
    """Build and compile the LangGraph agent. Returns None if langgraph not installed."""
    if not LANGGRAPH_AVAILABLE:
        return None
    workflow = StateGraph(NewsAgentState)
    workflow.add_node("fetch_news", node_fetch_news)
    workflow.add_node("summarize_impact", node_summarize_impact)
    workflow.add_edge(START, "fetch_news")
    workflow.add_edge("fetch_news", "summarize_impact")
    workflow.add_edge("summarize_impact", END)
    return workflow.compile()


_agent = None


def get_news_agent():
    """Singleton compiled agent."""
    global _agent
    if _agent is None:
        _agent = build_news_agent()
    return _agent


def run_news_agent() -> dict[str, Any]:
    """
    Run the full agent: fetch all India market-impact news, then LLM summary for tomorrow's impact.
    Returns { "news_items": [...], "impact_summary": str, "stocks_impact": { positive, negative, market_take } }.
    """
    agent = get_news_agent()
    if agent is None:
        # Fallback without LangGraph: just fetch news and optional simple LLM
        items = aggregate_news(symbols=None)[:50]
        news_dicts = [_news_to_dict(n) for n in items]
        summary = ""
        stocks_impact = {}
        raw = call_llm(
            "Summarize in 2 sentences the likely impact on Indian stock markets tomorrow based on these headlines:\n"
            + "\n".join(n.title for n in items[:20])
        )
        if raw:
            summary = raw
        return {
            "news_items": news_dicts,
            "impact_summary": summary,
            "stocks_impact": stocks_impact,
            "stocks_list": [],
        }
    initial: dict[str, Any] = {}
    result = agent.invoke(initial)
    return {
        "news_items": result.get("news_items") or [],
        "impact_summary": result.get("impact_summary") or "",
        "stocks_impact": result.get("stocks_impact") or {},
        "stocks_list": result.get("stocks_list") or [],
    }

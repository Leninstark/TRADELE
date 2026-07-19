"""News Sentiment swing tab — RSS + LLM scoring per universe symbol."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from TRADELE.config import settings
from TRADELE.filters.swing_definitions import TAB_NEWS_SENTIMENT, filter_tooltip_dict
from TRADELE.services.llm_agent import call_gemini, call_llm
from TRADELE.services.news_aggregator import aggregate_news

logger = logging.getLogger(__name__)

MAX_SYMBOLS_LLM = 40


def _keyword_sentiment(symbol: str, headlines: list[dict[str, str]]) -> dict[str, Any]:
    """Fallback when LLM unavailable."""
    pos = ("surge", "gain", "profit", "upgrade", "beat", "win", "record", "growth", "bull")
    neg = ("fall", "loss", "downgrade", "miss", "fraud", "probe", "decline", "cut", "bear")
    score = 50
    hits: list[str] = []
    for h in headlines:
        text = f"{h.get('title', '')} {h.get('summary', '')}".lower()
        if symbol.lower() not in text and symbol[:4].lower() not in text:
            continue
        hits.append(h.get("source", ""))
        if any(w in text for w in pos):
            score += 15
        if any(w in text for w in neg):
            score -= 15
    score = max(0, min(100, score))
    if score >= 65:
        sentiment = "Positive"
    elif score <= 35:
        sentiment = "Negative"
    else:
        sentiment = "Neutral"
    return {
        "symbol": symbol,
        "price": None,
        "extra": {
            "sentiment": sentiment,
            "score": score,
            "summary": f"Keyword scan across {len(hits)} headline(s).",
            "sources": list(dict.fromkeys(hits))[:5],
            "llm_used": False,
        },
    }


def _llm_score_symbols(symbols: list[str], news_dicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    headlines = "\n".join(
        f"- [{n.get('source', '')}] {n.get('title', '')}"
        for n in news_dicts[:40]
    )
    prompt = f"""You are an Indian equity news analyst. Score swing-trading sentiment for each stock below using today's headlines (Moneycontrol, Economic Times, NSE-related news, bulk/block deals, results, policy).

Stocks to score: {', '.join(symbols)}

Headlines:
{headlines}

Return ONLY a JSON array (no markdown). One object per stock that has news OR Neutral if no direct news:
[{{"symbol":"TICKER","sentiment":"Positive|Neutral|Negative","score":0-100,"summary":"one line","sources":["Moneycontrol"]}}]

Use exact NSE symbols from the list. sentiment must be Positive, Neutral, or Negative."""

    raw = call_gemini(prompt) or call_llm(prompt)
    if not raw:
        return [_keyword_sentiment(s, news_dicts) for s in symbols]

    try:
        text = raw.strip()
        if "```" in text:
            text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("expected array")
        out: list[dict[str, Any]] = []
        allowed = {s.upper() for s in symbols}
        for item in data:
            sym = str(item.get("symbol", "")).upper()
            if sym not in allowed:
                continue
            sentiment = str(item.get("sentiment", "Neutral"))
            if sentiment not in ("Positive", "Neutral", "Negative"):
                sentiment = "Neutral"
            out.append({
                "symbol": sym,
                "price": None,
                "extra": {
                    "sentiment": sentiment,
                    "score": int(item.get("score", 50)),
                    "summary": str(item.get("summary", ""))[:300],
                    "sources": item.get("sources") or [],
                    "llm_used": True,
                },
            })
        scored_syms = {r["symbol"] for r in out}
        for s in symbols:
            if s.upper() not in scored_syms:
                out.append(_keyword_sentiment(s, news_dicts))
        return out
    except Exception as e:
        logger.warning("LLM news parse failed: %s", e)
        return [_keyword_sentiment(s, news_dicts) for s in symbols]


def run_news_sentiment_scan(symbols: list[str]) -> dict[str, Any]:
    if not symbols:
        return {
            "tab": TAB_NEWS_SENTIMENT,
            "filter": filter_tooltip_dict(TAB_NEWS_SENTIMENT),
            "stocks": [],
            "meta": {"error": "no_universe", "message": "Run Universe scan first."},
        }

    batch = symbols[:MAX_SYMBOLS_LLM]
    news_items = aggregate_news(symbols=batch)
    news_dicts = [
        {"title": n.title, "source": n.source, "summary": n.summary, "link": n.link}
        for n in news_items
    ]

    stocks = _llm_score_symbols(batch, news_dicts)
    # Keep Positive and Neutral; drop Negative unless user wants all - show all with sentiment
    stocks.sort(
        key=lambda r: (
            {"Positive": 2, "Neutral": 1, "Negative": 0}.get(r.get("extra", {}).get("sentiment", ""), 0),
            r.get("extra", {}).get("score", 0),
        ),
        reverse=True,
    )

    llm_ok = bool(settings.gemini_api_key or settings.openai_api_key)
    return {
        "tab": TAB_NEWS_SENTIMENT,
        "filter": filter_tooltip_dict(TAB_NEWS_SENTIMENT),
        "stocks": stocks,
        "meta": {
            "universe_count": len(symbols),
            "scored_count": len(stocks),
            "headlines_used": len(news_dicts),
            "note": (
                "LLM sentiment via Gemini/OpenAI."
                if llm_ok
                else "LLM not configured; using keyword fallback. Set GEMINI_API_KEY."
            ),
        },
    }

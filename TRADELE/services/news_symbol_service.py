"""Per-symbol news harvest + AI market-impact summary."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from TRADELE.engines.agents.stock_analyst import _clean_company, _gather_news, _to_dicts
from TRADELE.services.llm_agent import call_llm_auto
from TRADELE.services.news_aggregator import NewsItem, aggregate_news, fetch_google_news
from TRADELE.services.news_watch_store import get_feed, save_feed

logger = logging.getLogger(__name__)


def _news_dict(n: NewsItem) -> dict[str, Any]:
    return {
        "title": n.title,
        "link": n.link,
        "source": n.source,
        "published": n.published.isoformat() if n.published else None,
        "summary": (n.summary or "")[:400],
    }


def _dedupe_items(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    out: list[NewsItem] = []
    for n in items:
        key = (n.link or n.title[:80]).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(n)
    out.sort(
        key=lambda x: x.published or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return out


def _rss_hits(symbol: str, company: str, sector: str) -> list[NewsItem]:
    """Scan configured RSS feeds for symbol, company, or sector mentions."""
    sym = symbol.upper()
    comp = _clean_company(company).lower() if company else ""
    sec = (sector or "").lower()
    tokens = [sym]
    if comp and len(comp) > 3:
        tokens.append(comp)
    if sec and sec not in ("unknown", ""):
        tokens.append(sec)
    pattern = re.compile("|".join(re.escape(t) for t in tokens if t), re.I)
    hits: list[NewsItem] = []
    for n in aggregate_news(symbols=None):
        blob = f"{n.title} {n.summary}"
        if pattern.search(blob):
            hits.append(n)
    return hits[:20]


def gather_symbol_news(symbol: str, company: str, sector: str) -> dict[str, Any]:
    """Company + sector + RSS hits from all configured sources."""
    company_news, sector_news = _gather_news(symbol, company, sector)
    rss_items = [_news_dict(n) for n in _rss_hits(symbol, company, sector)]

    # Extra Google News query for direct symbol mentions
    extra = _dedupe_items(fetch_google_news(f"{symbol} NSE stock", limit=8))
    extra_dicts = _to_dicts(extra, 8)

    seen_titles: set[str] = set()
    merged_company: list[dict[str, Any]] = []
    for item in company_news + extra_dicts:
        key = (item.get("title") or "")[:80].lower()
        if key and key not in seen_titles:
            seen_titles.add(key)
            merged_company.append(item)

    return {
        "company_news": merged_company[:20],
        "sector_news": sector_news[:12],
        "rss_hits": rss_items,
        "sources": ["RSS", "Google News", "Moneycontrol", "Economic Times", "Business Standard", "Livemint", "NDTV"],
    }


def _extract_json(raw: str) -> str:
    raw = raw.strip()
    if "```json" in raw:
        return raw.split("```json")[1].split("```")[0].strip()
    if "```" in raw:
        return raw.split("```")[1].replace("json", "", 1).strip()
    return raw


def _rule_analysis(symbol: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    pos = sum(1 for t in " ".join(i.get("title", "") for i in items).lower().split() if t in ("surge", "gain", "rise", "beat", "upgrade", "growth"))
    neg = sum(1 for t in " ".join(i.get("title", "") for i in items).lower().split() if t in ("fall", "drop", "cut", "downgrade", "loss", "probe"))
    verdict = "neutral"
    score = 50
    if pos > neg + 1:
        verdict, score = "bullish", 62
    elif neg > pos + 1:
        verdict, score = "bearish", 38
    return {
        "verdict": verdict,
        "sentiment_score": score,
        "impact_summary": f"{len(items)} headlines tracked for {symbol}. Rule-based read — configure Gemini/OpenAI for deeper impact analysis.",
        "sector_note": "",
        "highlights": [{"title": i.get("title"), "link": i.get("link"), "source": i.get("source"), "impact": ""} for i in items[:5]],
    }


def analyze_symbol_news(
    symbol: str,
    company: str,
    sector: str,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    all_items = bundle.get("company_news", []) + bundle.get("sector_news", []) + bundle.get("rss_hits", [])
    if not all_items:
        return {
            "verdict": "neutral",
            "sentiment_score": 50,
            "impact_summary": f"No recent headlines found for {symbol}. Add again later or check spelling.",
            "sector_note": "",
            "highlights": [],
        }

    lines = [
        f"You are an Indian equity market analyst. Analyze news impact for {symbol} ({company}), sector: {sector or 'Unknown'}.",
        "Use ONLY the headlines below. Respond with ONLY valid JSON:",
        "{",
        '  "verdict": "bullish|bearish|neutral",',
        '  "sentiment_score": 0-100,',
        '  "impact_summary": "2-4 sentences on likely market impact for this stock and sector",',
        '  "sector_note": "1-2 sentences on sector spillover if any",',
        '  "highlights": [{"title":"...","link":"...","source":"...","impact":"one line why it matters"}]',
        "}",
        "",
        "## Headlines",
    ]
    for i, n in enumerate(all_items[:25], 1):
        lines.append(f"{i}. [{n.get('source')}] {n.get('title')}")
        if n.get("summary"):
            lines.append(f"   {str(n['summary'])[:180]}")
        if n.get("link"):
            lines.append(f"   LINK: {n['link']}")

    prompt = "\n".join(lines)
    raw = call_llm_auto(prompt)
    if not raw:
        return _rule_analysis(symbol, all_items)

    try:
        data = json.loads(_extract_json(raw))
        highlights = data.get("highlights") or []
        # Ensure links from original items when LLM omits them
        by_title = {(i.get("title") or "").lower(): i for i in all_items}
        norm_highlights = []
        for h in highlights[:8]:
            if not isinstance(h, dict):
                continue
            title = h.get("title") or ""
            orig = by_title.get(title.lower(), {})
            norm_highlights.append(
                {
                    "title": title,
                    "link": h.get("link") or orig.get("link") or "",
                    "source": h.get("source") or orig.get("source") or "",
                    "impact": h.get("impact") or "",
                }
            )
        if not norm_highlights:
            norm_highlights = [
                {
                    "title": i.get("title"),
                    "link": i.get("link"),
                    "source": i.get("source"),
                    "impact": "",
                }
                for i in all_items[:6]
            ]
        return {
            "verdict": str(data.get("verdict") or "neutral").lower(),
            "sentiment_score": int(data.get("sentiment_score") or 50),
            "impact_summary": data.get("impact_summary") or "",
            "sector_note": data.get("sector_note") or "",
            "highlights": norm_highlights,
        }
    except Exception as e:
        logger.warning("news analysis JSON parse failed %s: %s", symbol, e)
        return _rule_analysis(symbol, all_items)


def refresh_symbol_feed(
    db: Session,
    username: str,
    symbol: str,
    company: str,
    sector: Optional[str],
    *,
    force: bool = False,
) -> dict[str, Any]:
    bundle = gather_symbol_news(symbol, company, sector or "")
    all_items = bundle["company_news"] + bundle["sector_news"] + bundle["rss_hits"]
    links = [i.get("link") for i in all_items if i.get("link")]

    prev = get_feed(db, username, symbol)
    prev_payload: dict = {}
    if prev and isinstance(prev.get("payload"), dict):
        prev_payload = prev["payload"]
    prev_seen = set(prev_payload.get("seen_links") or [])
    ack_links = set(prev_payload.get("ack_links") or [])

    new_since_fetch = [lk for lk in links if lk not in prev_seen]
    unread = [lk for lk in links if lk not in ack_links]
    has_new = len(unread) > 0

    if force or not prev or new_since_fetch:
        analysis = analyze_symbol_news(symbol, company, sector or "", bundle)
    else:
        analysis = prev_payload.get("analysis") or {}

    payload = {
        **bundle,
        "analysis": analysis,
        "seen_links": links,
        "ack_links": list(ack_links),
        "has_new": has_new,
        "new_count": len(unread),
    }
    save_feed(db, username, symbol, payload, links)
    return {
        "symbol": symbol.upper(),
        "company": company,
        "sector": sector,
        "feed": payload,
        "has_new": has_new,
    }


def refresh_user_feeds(
    db: Session,
    username: str,
    *,
    force: bool = False,
) -> list[dict[str, Any]]:
    from TRADELE.services.news_watch_store import list_news_watch

    watches = list_news_watch(db, username)
    out: list[dict[str, Any]] = []
    for w in watches:
        try:
            out.append(
                refresh_symbol_feed(
                    db,
                    username,
                    w["symbol"],
                    w.get("company") or w["symbol"],
                    w.get("sector"),
                    force=force,
                )
            )
        except Exception as e:
            logger.warning("news refresh failed %s: %s", w.get("symbol"), e)
    return out

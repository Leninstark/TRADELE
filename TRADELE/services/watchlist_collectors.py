"""Deterministic fact collectors for Watchlist Analyst."""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any, Optional

from sqlalchemy.orm import Session

from TRADELE.db.models import ExploreAnalysisCache, IntradayMomentumCandidate, IntradayMomentumScanRun
from TRADELE.engines.agents.stock_analyst import (
    _fundamentals,
    _gather_news,
    build_metrics,
    resolve_symbol,
)
from TRADELE.filters.nse_data import fetch_delivery_map, fetch_market_cap_cr
from TRADELE.filters.universe import load_full_symbol_industry_map
from TRADELE.services.watchlist_fact_cache import get_fact_cache, put_fact_cache

logger = logging.getLogger(__name__)

STOCK_KEYWORDS = (
    "stock", "share", "nse", "bse", "intraday", "swing", "buy", "sell", "short", "long",
    "vwap", "ema", "rsi", "macd", "adx", "atr", "stoch", "bollinger", "breakout",
    "support", "resistance", "target", "stop", "sl", "delivery", "volume", "candle",
    "chart", "technical", "fundamental", "pe", "eps", "dividend", "earnings", "result",
    "quarter", "sector", "nifty", "banknifty", "ipo", "price", "trade", "position",
    "conviction", "bullish", "bearish", "neutral", "levels", "setup", "entry", "exit",
    "hold", "outlook", "verdict", "analyse", "analyze", "analysis", "momentum",
    "pullback", "rally", "correction", "overbought", "oversold", "cmp", "ltp",
)

# Short trading intents when a watchlist symbol is already selected
STOCK_INTENTS = (
    "should i", "can i", "what do you think", "your view", "your take",
    "good to buy", "worth buying", "enter now", "exit now", "book profit",
    "add more", "average", "risk reward", "rr ", " tomorrow", "today",
)

OFF_TOPIC_PATTERNS = (
    r"\bjoke\b", r"\bpoem\b", r"\bstory\b", r"\brecipe\b", r"\bcook\b",
    r"\bweather\b", r"\bhomework\b", r"\bcode\b", r"\bpython\b", r"\bjavascript\b",
    r"\bwho is\b", r"\bpresident\b", r"\bprime minister\b", r"\bcricket\b",
    r"\bmovie\b", r"\bsong\b", r"\blove\b", r"\brelationship\b",
    r"\btranslate\b", r"\bwrite (an |a )?(email|essay|letter)\b",
)


def is_stock_question(text: str, *, symbol: str = "") -> bool:
    """True only for Indian equity / trading questions (or empty refresh on a symbol)."""
    t = (text or "").strip()
    if not t:
        return bool(symbol)

    low = t.lower()
    if any(re.search(p, low) for p in OFF_TOPIC_PATTERNS):
        # Still allow if clearly about the selected ticker + trading
        sym = (symbol or "").strip().upper()
        if not (sym and sym.lower() in low and any(k in low for k in ("buy", "sell", "price", "stock", "share"))):
            return False

    if any(k in low for k in STOCK_KEYWORDS):
        return True
    if any(k in low for k in STOCK_INTENTS):
        return True

    sym = (symbol or "").strip().upper()
    if sym and re.search(rf"\b{re.escape(sym)}\b", t, flags=re.I):
        return True

    # Uppercase ticker-like token
    for word in t.split():
        w = word.strip(".,?!")
        if 2 <= len(w) <= 15 and w.isupper() and w.isalpha():
            return True
    return False


def _db_context(db: Session, symbol: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    explore = (
        db.query(ExploreAnalysisCache)
        .filter(ExploreAnalysisCache.symbol == symbol)
        .order_by(ExploreAnalysisCache.accessed_at.desc())
        .first()
    )
    if explore and isinstance(explore.payload, dict):
        report = explore.payload.get("report") or explore.payload
        out["explore_cache"] = {
            "date": explore.analysis_date.isoformat() if explore.analysis_date else None,
            "verdict": report.get("verdict"),
            "conviction": report.get("conviction"),
            "summary": (report.get("summary") or "")[:500],
        }

    cand = (
        db.query(IntradayMomentumCandidate)
        .join(IntradayMomentumScanRun, IntradayMomentumCandidate.run_id == IntradayMomentumScanRun.id)
        .filter(
            IntradayMomentumCandidate.symbol == symbol,
            IntradayMomentumCandidate.is_top_pick.is_(True),
        )
        .order_by(IntradayMomentumScanRun.as_of.desc())
        .first()
    )
    if cand:
        run = (
            db.query(IntradayMomentumScanRun)
            .filter(IntradayMomentumScanRun.id == cand.run_id)
            .first()
        )
        out["intraday_conviction"] = {
            "direction": cand.direction,
            "conviction": cand.conviction,
            "can_trade_tomorrow": cand.can_trade_tomorrow,
            "checks_passed": cand.checks_passed,
            "checks_total": cand.checks_total,
            "as_of": run.as_of.isoformat() if run and run.as_of else None,
        }
    return out


def collect_facts(
    db: Session,
    symbol: str,
    *,
    company: Optional[str] = None,
    sector: Optional[str] = None,
    force_refresh: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    sym = symbol.strip().upper()
    if not force_refresh:
        cached = get_fact_cache(db, sym)
        if cached:
            return cached["facts"], list(cached.get("sources") or [])

    industry_map = load_full_symbol_industry_map()
    co = company or sym
    sec = sector or industry_map.get(sym) or "Unknown"
    sources: list[str] = []
    facts: dict[str, Any] = {
        "symbol": sym,
        "company": co,
        "sector": sec,
        "collected_at": date.today().isoformat(),
    }

    rate_limited = False
    try:
        metrics = build_metrics(sym, db)
    except Exception as e:
        from TRADELE.services.zerodha_client import KiteRateLimitError

        if isinstance(e, KiteRateLimitError):
            rate_limited = True
            metrics = None
        else:
            raise
    if metrics:
        facts["technical"] = metrics
        sources.append("technical")
    elif rate_limited:
        facts["rate_limited"] = True
        facts["warnings"] = ["Zerodha rate limit — using cached NSE/news/DB only"]

    try:
        delivery_map = fetch_delivery_map()
        deliv = delivery_map.get(sym)
        mcap = fetch_market_cap_cr(sym)
        facts["nse"] = {
            "delivery_pct": deliv,
            "market_cap_cr": mcap,
        }
        if deliv is not None or mcap is not None:
            sources.append("nse")
    except Exception as e:
        logger.debug("NSE collect failed %s: %s", sym, e)

    try:
        company_news, sector_news = _gather_news(sym, co, sec)
        facts["news"] = {"company": company_news, "sector": sector_news}
        if company_news or sector_news:
            sources.append("news")
    except Exception as e:
        logger.debug("News collect failed %s: %s", sym, e)

    try:
        fund = _fundamentals(sym)
        if fund:
            facts["fundamentals"] = fund
            sources.append("screener")
    except Exception as e:
        logger.debug("Fundamentals failed %s: %s", sym, e)

    db_ctx = _db_context(db, sym)
    if db_ctx:
        facts["db"] = db_ctx
        sources.append("db")

    try:
        import yfinance as yf

        info = yf.Ticker(f"{sym}.NS").info or {}
        if info.get("shortName") or info.get("marketCap"):
            facts["yahoo"] = {
                "name": info.get("shortName"),
                "market_cap": info.get("marketCap"),
                "avg_volume": info.get("averageVolume"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
            }
            sources.append("yahoo")
    except Exception as e:
        logger.debug("Yahoo failed %s: %s", sym, e)

    put_fact_cache(db, sym, facts, sources)
    return facts, sources


def facts_to_chunks(facts: dict[str, Any]) -> list[tuple[str, str, str, dict]]:
    """Return (source, suffix, content, metadata) for indexing."""
    sym = facts.get("symbol", "")
    chunks: list[tuple[str, str, str, dict]] = []

    tech = facts.get("technical")
    if tech:
        chunks.append(
            (
                "technical",
                "snapshot",
                json.dumps(tech, default=str)[:4000],
                {"symbol": sym},
            )
        )

    nse = facts.get("nse")
    if nse:
        chunks.append(("nse", "delivery", json.dumps(nse), {"symbol": sym}))

    news = facts.get("news") or {}
    for i, item in enumerate((news.get("company") or [])[:5]):
        chunks.append(
            (
                "news",
                f"co_{i}",
                f"{item.get('title', '')} — {item.get('summary', '')}",
                {"link": item.get("link"), "published": item.get("published")},
            )
        )

    db_ctx = facts.get("db")
    if db_ctx:
        chunks.append(("db", "cache", json.dumps(db_ctx, default=str), {"symbol": sym}))

    return chunks

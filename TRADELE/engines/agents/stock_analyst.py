"""
Deep single-stock analysis agent for the Explore page.

Given a stock symbol/name, it:
  1. Resolves & validates the symbol against the NSE universe.
  2. Pulls ~1 year of OHLCV (Zerodha, cached), computes a full technical snapshot.
  3. Pulls fundamentals (Screener.in via Apify) + NSE market cap / delivery.
  4. Pulls recent news mentioning the stock/company.
  5. Asks Gemini for an evidence-backed report with next-week / next-month /
     next-3-month outlooks across fundamental, technical and sentiment lenses.

Falls back to a rule-based report when the LLM is unavailable.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from TRADELE.config import settings
from TRADELE.engines.indicators.calculator import IndicatorCalculator
from TRADELE.filters.nse_data import fetch_delivery_map, fetch_market_cap_cr
from TRADELE.filters.universe import (
    load_full_symbol_company_map,
    load_full_symbol_industry_map,
)
from TRADELE.services.llm_agent import call_gemini, call_llm
from TRADELE.services.news_aggregator import NewsItem, fetch_google_news
from TRADELE.services.screener_service import run_screener_query
from TRADELE.services.zerodha_client import get_client

logger = logging.getLogger(__name__)

CALC = IndicatorCalculator()
LOOKBACK_DAYS = 420  # ~1 trading year + buffer

# Trading-day offsets for horizon returns
RETURN_WINDOWS = {
    "return_1w_pct": 5,
    "return_1m_pct": 21,
    "return_3m_pct": 63,
    "return_6m_pct": 126,
    "return_1y_pct": 252,
}


# ─────────────────────────────── helpers ────────────────────────────────

def _extract_json(raw: str) -> str:
    raw = raw.strip()
    if "```json" in raw:
        return raw.split("```json")[1].split("```")[0].strip()
    if "```" in raw:
        return raw.split("```")[1].replace("json", "", 1).strip()
    return raw


def _return_pct(closes: list[float], days: int) -> Optional[float]:
    if len(closes) <= days:
        return None
    prev, now = closes[-1 - days], closes[-1]
    if not prev:
        return None
    return round((now - prev) / prev * 100, 2)


def resolve_symbol(query: str) -> tuple[Optional[str], Optional[str]]:
    """Return (symbol, company) from a user query (symbol or company name)."""
    if not query:
        return None, None
    q = query.strip().upper()
    company_map = load_full_symbol_company_map()

    if q in company_map:
        return q, company_map[q]

    # Match by company name (contains)
    ql = query.strip().lower()
    best: Optional[tuple[str, str]] = None
    for sym, comp in company_map.items():
        cl = comp.lower()
        if cl == ql:
            return sym, comp
        if ql in cl or cl in ql:
            # Prefer shorter company names (closer match)
            if best is None or len(comp) < len(best[1]):
                best = (sym, comp)
    if best:
        return best
    # Unknown to CSV universe — still allow raw symbol (Zerodha may resolve it)
    return q, q


def _clean_company(company: str) -> str:
    """Strip common suffixes so 'Reliance Industries Ltd.' -> 'Reliance Industries'."""
    name = company or ""
    for suffix in (" Ltd.", " Ltd", " Limited", " Ltd.-", " Corporation", " Corp."):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def _to_dicts(items: list[NewsItem], limit: int) -> list[dict[str, Any]]:
    return [
        {
            "title": n.title,
            "source": n.source,
            "published": n.published.isoformat() if n.published else None,
            "summary": (n.summary or "")[:280],
            "link": n.link,
        }
        for n in items[:limit]
        if n.title
    ]


def _gather_news(symbol: str, company: str, sector: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Company-specific + industry/sector news from Google News (free)."""
    comp = _clean_company(company) if company and company != symbol else symbol

    company_items = fetch_google_news(f"{comp} share price NSE", limit=10)
    if len(company_items) < 3:
        company_items += fetch_google_news(f"{symbol} stock news", limit=8)
    # Dedupe by title
    seen: set[str] = set()
    company_dedup: list[NewsItem] = []
    for n in company_items:
        key = n.title[:80].lower()
        if key and key not in seen:
            seen.add(key)
            company_dedup.append(n)

    industry_items: list[NewsItem] = []
    if sector and sector != "Unknown":
        industry_items = fetch_google_news(f"{sector} sector India outlook stocks", limit=8)

    return _to_dicts(company_dedup, 12), _to_dicts(industry_items, 8)


def _fundamentals(symbol: str) -> dict[str, Any]:
    """Best-effort Screener.in fundamentals (may be empty if Apify unauthorised/slow)."""
    if not settings.apify_api_token:
        return {}
    try:
        url = f"https://www.screener.in/company/{symbol}/"
        items = run_screener_query(mode="getstockdetails", url=url)
        if items:
            return items[0]
    except Exception as e:
        logger.debug("screener fundamentals failed for %s: %s", symbol, e)
    return {}


# ─────────────────────────────── metrics ────────────────────────────────

def build_metrics(symbol: str, db: Session) -> Optional[dict[str, Any]]:
    """Fetch candles + compute the full technical / price snapshot."""
    client = get_client()
    to_date = date.today()
    from_date = to_date - timedelta(days=LOOKBACK_DAYS)
    try:
        # Try cached fetch first; fall back to direct fetch if the candle_cache
        # table is unavailable in this environment.
        try:
            candles = client.get_historical(symbol, "NSE", "day", from_date, to_date, db=db)
        except Exception as cache_err:
            logger.debug("cached fetch failed for %s (%s); retrying without cache", symbol, cache_err)
            try:
                db.rollback()
            except Exception:
                pass
            candles = client.get_historical(
                symbol, "NSE", "day", from_date, to_date, use_cache=False
            )
    except Exception as e:
        logger.warning("historical fetch failed for %s: %s", symbol, e)
        return None
    if not candles or len(candles) < 20:
        return None

    ind = CALC.compute(symbol, candles)
    if not ind:
        return None

    closes = [float(c["close"]) for c in candles]
    close = float(ind["close"])

    metrics: dict[str, Any] = {
        "symbol": symbol,
        "close": round(close, 2),
        "change_pct": ind.get("change_pct"),
        "candles_count": len(candles),
    }
    for key, days in RETURN_WINDOWS.items():
        metrics[key] = _return_pct(closes, days)

    high_52w = ind.get("high_52w")
    low_52w = ind.get("low_52w")
    metrics["high_52w"] = high_52w
    metrics["low_52w"] = low_52w
    if high_52w:
        metrics["dist_52w_high_pct"] = round((float(high_52w) - close) / float(high_52w) * 100, 2)
    if low_52w:
        metrics["above_52w_low_pct"] = round((close - float(low_52w)) / float(low_52w) * 100, 2)

    for key in (
        "rsi", "adx", "atr", "macd", "macd_signal", "macd_hist",
        "ema_20", "ema_50", "ema_200", "sma_50", "sma_200",
        "bb_upper", "bb_lower", "supertrend", "cci", "stoch_rsi",
        "volume_ratio", "high_20d", "low_20d",
        "dist_ema_20_pct", "dist_ema_50_pct", "dist_ema_200_pct",
    ):
        if ind.get(key) is not None:
            metrics[key] = ind[key]

    ema20, ema50, ema200 = ind.get("ema_20"), ind.get("ema_50"), ind.get("ema_200")
    metrics["ema_aligned_bull"] = bool(
        ema20 and ema50 and ema200 and close > ema20 > ema50 > ema200
    )
    high_20d = ind.get("high_20d")
    metrics["near_20d_breakout"] = bool(high_20d and close >= float(high_20d) * 0.99)

    avg_vol = sum(float(c.get("volume") or 0) for c in candles[-20:]) / min(20, len(candles))
    metrics["avg_daily_volume"] = round(avg_vol, 0)
    return metrics


# ─────────────────────────── rule-based trend ───────────────────────────

def _rule_based_report(m: dict[str, Any], company: str) -> dict[str, Any]:
    """Deterministic fallback when no LLM is configured."""
    close = m.get("close") or 0
    rsi = m.get("rsi") or 50
    adx = m.get("adx") or 0
    atr = m.get("atr") or (close * 0.02)
    aligned = m.get("ema_aligned_bull")
    ret1m = m.get("return_1m_pct") or 0
    ret3m = m.get("return_3m_pct") or 0

    bull = (1 if aligned else 0) + (1 if rsi > 55 else 0) + (1 if ret3m > 5 else 0) + (1 if adx > 20 else 0)
    if bull >= 3:
        verdict, bias = "Accumulate", "Bullish"
        conv = 70
    elif bull <= 1:
        verdict, bias = "Avoid", "Bearish"
        conv = 55
    else:
        verdict, bias = "Hold", "Neutral"
        conv = 50

    def rng(days_atr: float) -> str:
        lo = round(close - days_atr * atr, 1)
        hi = round(close + days_atr * atr, 1)
        return f"₹{lo} – ₹{hi}"

    horizon = lambda mult: {
        "bias": bias,
        "expected_range": rng(mult),
        "confidence": conv,
        "rationale": "Rule-based projection from trend, RSI and ATR volatility (LLM not configured).",
    }
    return {
        "verdict": verdict,
        "conviction": conv,
        "summary": (
            f"{company}: {'strong' if bull >= 3 else 'weak' if bull <= 1 else 'mixed'} technical setup. "
            f"3M return {ret3m}%, RSI {round(rsi,1)}, ADX {round(adx,1)}."
        ),
        "fundamental": {"rating": "Unknown", "points": ["Fundamental data unavailable."], "risks": []},
        "technical": {
            "rating": "Strong" if bull >= 3 else "Weak" if bull <= 1 else "Moderate",
            "trend": "Uptrend" if aligned else "Downtrend" if bull <= 1 else "Sideways",
            "points": [
                f"EMA alignment bullish: {aligned}",
                f"RSI {round(rsi,1)}, ADX {round(adx,1)}",
                f"1M {ret1m}% / 3M {ret3m}%",
            ],
            "key_levels": {"support": m.get("ema_50"), "resistance": m.get("high_20d")},
        },
        "sentiment": {
            "rating": "Neutral",
            "points": ["No LLM sentiment analysis available."],
            "industry_impact": "",
        },
        "outlook": {
            "next_week": horizon(2),
            "next_month": horizon(4),
            "next_3_months": horizon(7),
        },
        "entry": {
            "buy_zone": rng(1),
            "stop_loss": round(close - 2 * atr, 1),
            "target_1": round(close + 3 * atr, 1),
            "target_2": round(close + 5 * atr, 1),
            "risk_reward": "≈1:1.5",
        },
        "catalysts": [],
        "red_flags": [] if bull >= 2 else ["Weak trend / momentum"],
        "conclusion": (
            f"Bottom line: {verdict} {company}. The trend is "
            f"{'clearly positive' if bull >= 3 else 'weak' if bull <= 1 else 'mixed'} "
            f"(3-month return {ret3m}%, RSI {round(rsi,1)}), so over the next 3 months we lean {bias.lower()}. "
            "This is a rule-based read (AI not configured); manage risk with the stop-loss above."
        ),
        "engine": "rule_based",
    }


# ─────────────────────────────── prompt ─────────────────────────────────

def _build_prompt(symbol: str, company: str, sector: str, m: dict[str, Any],
                  fundamentals: dict[str, Any], news: list[dict[str, Any]],
                  industry_news: list[dict[str, Any]]) -> str:
    lines = [
        "You are a senior SEBI-registered equity research analyst covering Indian (NSE) stocks.",
        f"Produce a detailed, evidence-backed research report on {company} ({symbol}), "
        f"which operates in the '{sector}' sector.",
        "Base EVERY claim on the data provided below. Cite concrete numbers and headlines as evidence.",
        "Assess sentiment from BOTH company-specific news AND industry/sector news. Not everything is "
        "driven by company data alone — sector tailwinds/headwinds (policy, demand, commodity prices, "
        "peer results, global cues) materially shift a stock's bull/bear case. Explicitly reason about "
        "how the industry backdrop helps or hurts THIS company, and reflect that in sentiment and the outlook.",
        "Then give a directional outlook for the next week, next month and next 3 months with expected "
        "price ranges and confidence.",
        "",
        "## Technical & price data",
    ]
    for k, v in m.items():
        if v is not None:
            lines.append(f"- {k}: {v}")

    if fundamentals:
        lines.append("")
        lines.append("## Fundamentals (Screener.in)")
        for k, v in list(fundamentals.items())[:60]:
            if isinstance(v, (str, int, float)) and str(v).strip():
                lines.append(f"- {k}: {v}")

    lines.append("")
    lines.append(f"## Company-specific news ({company})")
    if news:
        for n in news:
            lines.append(f"- [{n['source']}] {n['title']}")
    else:
        lines.append("- (No company-specific headlines found.)")

    lines.append("")
    lines.append(f"## Industry / sector news ({sector})")
    if industry_news:
        for n in industry_news:
            lines.append(f"- [{n['source']}] {n['title']}")
    else:
        lines.append("- (No sector headlines found.)")

    lines.append("")
    lines.append(
        "Respond with ONLY valid JSON (no markdown, no commentary) in EXACTLY this schema:\n"
        "{\n"
        '  "verdict": "Buy|Accumulate|Hold|Reduce|Avoid",\n'
        '  "conviction": <0-100 integer>,\n'
        '  "summary": "2-4 sentence executive summary with key evidence",\n'
        '  "fundamental": {"rating": "Strong|Moderate|Weak|Unknown", "points": ["evidence with numbers"], "risks": ["..."]},\n'
        '  "technical": {"rating": "Strong|Moderate|Weak", "trend": "Uptrend|Sideways|Downtrend", "points": ["evidence with numbers"], "key_levels": {"support": <number>, "resistance": <number>}},\n'
        '  "sentiment": {"rating": "Positive|Neutral|Negative", "points": ["from company news"], "industry_impact": "1-3 sentences on how sector/industry news shifts this stock bull/bear case"},\n'
        '  "outlook": {\n'
        '    "next_week": {"bias": "Bullish|Neutral|Bearish", "expected_range": "\u20b9x \u2013 \u20b9y", "confidence": <0-100>, "rationale": "why, with evidence"},\n'
        '    "next_month": {"bias": "...", "expected_range": "...", "confidence": <0-100>, "rationale": "..."},\n'
        '    "next_3_months": {"bias": "...", "expected_range": "...", "confidence": <0-100>, "rationale": "..."}\n'
        "  },\n"
        '  "entry": {"buy_zone": "\u20b9x \u2013 \u20b9y", "stop_loss": <number>, "target_1": <number>, "target_2": <number>, "risk_reward": "1:x"},\n'
        '  "catalysts": ["upcoming positive triggers"],\n'
        '  "red_flags": ["key risks / warnings"],\n'
        '  "conclusion": "Final bottom line in SIMPLE, plain English a beginner can understand (2-4 sentences). '
        "Clearly state the action (Buy / Add more / Hold / Reduce / Sell) and WHY, tying together the fundamental, "
        'technical and sentiment/industry evidence. The investment target horizon is a MAXIMUM of 3 months."\n'
        "}"
    )
    return "\n".join(lines)


# ─────────────────────────────── main ───────────────────────────────────

def analyze_stock(query: str, db: Session) -> dict[str, Any]:
    """Full pipeline: resolve -> metrics -> fundamentals/news -> LLM report."""
    symbol, company = resolve_symbol(query)
    if not symbol:
        return {"error": "invalid_symbol", "message": f"Could not resolve '{query}'."}

    industry_map = load_full_symbol_industry_map()
    sector = industry_map.get(symbol, "Unknown")

    metrics = build_metrics(symbol, db)
    if not metrics:
        return {
            "error": "no_data",
            "symbol": symbol,
            "company": company,
            "message": (
                f"No price history available for {symbol}. "
                "Ensure Zerodha is connected and the symbol is a valid NSE equity."
            ),
        }

    fundamentals = _fundamentals(symbol)
    news, industry_news = _gather_news(symbol, company or symbol, sector)

    prompt = _build_prompt(symbol, company or symbol, sector, metrics, fundamentals, news, industry_news)
    raw = call_gemini(prompt) if settings.gemini_api_key else None
    if not raw:
        raw = call_llm(prompt)

    report: dict[str, Any]
    if raw:
        try:
            report = json.loads(_extract_json(raw))
            report["engine"] = "gemini" if settings.gemini_api_key else "llm"
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("stock analyst LLM parse failed for %s: %s", symbol, e)
            report = _rule_based_report(metrics, company or symbol)
            report["parse_note"] = "LLM response was not valid JSON; used rule-based fallback."
    else:
        report = _rule_based_report(metrics, company or symbol)

    return {
        "symbol": symbol,
        "company": company or symbol,
        "sector": sector,
        "metrics": metrics,
        "fundamentals": fundamentals or {},
        "news": news,
        "industry_news": industry_news,
        "report": report,
        "generated_at": date.today().isoformat(),
    }


def list_universe_symbols() -> list[dict[str, str]]:
    """Symbol + company list for search suggestions."""
    company_map = load_full_symbol_company_map()
    return [{"symbol": s, "company": c} for s, c in sorted(company_map.items())]

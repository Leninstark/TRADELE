"""LLM agent: analyze historical + current data and suggest with justification (user-provided API)."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from TRADELE.config import settings
from TRADELE.services.scoring_engine import StockScore, reasons_to_dict

logger = logging.getLogger(__name__)

# Optional: openai package for OpenAI-compatible API
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


def build_analysis_prompt(
    top_longs: list[StockScore],
    top_shorts: list[StockScore],
    news_snippets: list[dict],
    market_context: Optional[str] = None,
) -> str:
    """Build prompt for LLM to summarize and justify intraday picks."""
    lines = [
        "You are an intraday trading analyst. Based on the following rule-based scan results and news, "
        "provide a concise summary and justification for the top intraday picks.",
        "",
        "## Top 10 LONG candidates (buy)",
    ]
    for i, s in enumerate(top_longs[:10], 1):
        lines.append(f"{i}. {s.symbol} (score: {s.score:.0f})")
        for r in s.reasons:
            lines.append(f"   - {r.reason} [source: {r.source}]")
        if s.key_levels:
            lines.append(f"   Key levels: {s.key_levels}")
        lines.append("")
    lines.append("## Top 10 SHORT candidates (avoid/sell)")
    for i, s in enumerate(top_shorts[:10], 1):
        lines.append(f"{i}. {s.symbol} (score: {s.score:.0f})")
        for r in s.reasons:
            lines.append(f"   - {r.reason} [source: {r.source}]")
        if s.key_levels:
            lines.append(f"   Key levels: {s.key_levels}")
        lines.append("")
    if news_snippets:
        lines.append("## Relevant news headlines")
        for n in news_snippets[:15]:
            lines.append(f"- [{n.get('source','')}] {n.get('title','')}")
        lines.append("")
    if market_context:
        lines.append("## Market context")
        lines.append(market_context)
    lines.append("")
    lines.append(
        "Respond with: (1) Brief market take. (2) Top 3 LONG with 1-line reason each. "
        "(3) Top 3 SHORT with 1-line reason each. (4) Disclaimer: Past performance and signals "
        "do not guarantee future results; trade at your own risk."
    )
    return "\n".join(lines)


def call_llm(prompt: str, api_key: Optional[str] = None, base_url: Optional[str] = None) -> Optional[str]:
    """Call OpenAI-compatible API. Set OPENAI_API_KEY and optionally LLM_BASE_URL."""
    api_key = api_key or settings.openai_api_key
    base_url = base_url or settings.llm_base_url
    if not api_key or not OpenAI:
        logger.debug("LLM not configured or openai not installed")
        return None
    try:
        client = OpenAI(api_key=api_key, base_url=base_url if base_url else None)
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
        )
        return r.choices[0].message.content if r.choices else None
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return None


def call_gemini(prompt: str, api_key: Optional[str] = None) -> Optional[str]:
    """Call Google Gemini Pro for news summarisation. Uses GEMINI_API_KEY when set."""
    api_key = api_key or getattr(settings, "gemini_api_key", None)
    if not api_key:
        return None
    try:
        import google.generativeai as genai
        # Use REST transport: the default gRPC transport can hang indefinitely
        # in some network environments.
        genai.configure(api_key=api_key, transport="rest")
        model = genai.GenerativeModel(getattr(settings, "gemini_model", None) or "gemini-flash-latest")
        response = model.generate_content(prompt, request_options={"timeout": 90})
        if response and response.text:
            return response.text
        return None
    except ImportError:
        logger.debug("google-generativeai not installed; pip install google-generativeai")
        return None
    except Exception as e:
        logger.warning("Gemini call failed: %s", e)
        return None


def enrich_alerts_with_llm(
    top_longs: list[StockScore],
    top_shorts: list[StockScore],
    news_snippets: list[dict],
    market_context: Optional[str] = None,
) -> str:
    """Return LLM summary string for notifications; empty if LLM not configured."""
    prompt = build_analysis_prompt(top_longs, top_shorts, news_snippets, market_context)
    return call_llm(prompt) or ""


def build_news_impact_prompt(
    news_headlines: list[dict],
    screener_context: Optional[str] = None,
) -> str:
    """Build prompt for LLM to infer which stocks/sectors may go up or down from market-impact news."""
    lines = [
        "You are a market analyst. Below are recent financial and market news headlines that can move the market (macro, policy, sector, global).",
        "Infer which Indian stocks or sectors might move UP (positive) or DOWN (negative) based on these headlines.",
        "Do NOT base your answer on user-provided symbol lists; base it only on the news content.",
        "",
        "## News headlines",
    ]
    for n in news_headlines[:25]:
        lines.append(f"- [{n.get('source', '')}] {n.get('title', '')}")
        if n.get("summary"):
            lines.append(f"  {n['summary'][:200]}")
    if screener_context:
        lines.append("")
        lines.append("## Optional context (top screened stocks / sectors)")
        lines.append(screener_context[:1500])
    lines.append("")
    lines.append(
        "Respond in this exact JSON format only, no other text:\n"
        '{"positive": [{"symbol_or_sector": "name", "reason": "one line"}], '
        '"negative": [{"symbol_or_sector": "name", "reason": "one line"}], '
        '"market_take": "one paragraph summary"}\n'
        "Use Indian NSE stock symbols or sector names (e.g. RELIANCE, Bank Nifty, IT sector)."
    )
    return "\n".join(lines)


def infer_stocks_from_news(
    news_headlines: list[dict],
    screener_context: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    Use LLM to infer which stocks/sectors may go up or down from market-impact news.
    Returns {"positive": [...], "negative": [...], "market_take": "..."} or None.
    """
    prompt = build_news_impact_prompt(news_headlines, screener_context)
    raw = call_llm(prompt)
    if not raw:
        return None
    try:
        # Try to extract JSON from response (in case LLM adds markdown or extra text)
        raw = raw.strip()
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLM did not return valid JSON for news impact")
        return {"raw_response": raw, "positive": [], "negative": [], "market_take": ""}

"""Dashboard swing tab — full metrics grid + AI trade levels for top picks."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from TRADELE.config import settings
from TRADELE.filters.swing_definitions import TAB_DASHBOARD, filter_tooltip_dict
from TRADELE.filters.swing_helpers import check_zerodha
from TRADELE.filters.symbol_metrics import build_symbol_metrics
from TRADELE.services.llm_agent import call_gemini, call_llm

logger = logging.getLogger(__name__)

LLM_TOP_N = 25


def _rule_based_trade_levels(m: dict[str, Any]) -> dict[str, Any]:
    """Fallback entry/stop/targets from ATR when LLM unavailable."""
    close = float(m.get("ltp") or m.get("close") or 0)
    atr = float(m.get("atr") or close * 0.02)
    entry = round(close, 2)
    stop = round(close - 1.5 * atr, 2)
    t1 = round(close + 2 * atr, 2)
    t2 = round(close + 3.5 * atr, 2)
    risk = entry - stop
    reward = t1 - entry
    rr = round(reward / risk, 2) if risk > 0 else None
    return {
        "entry_price": entry,
        "stop_loss": stop,
        "target_1": t1,
        "target_2": t2,
        "risk_reward": rr,
        "confidence": min(95, int(m.get("score", 50))),
        "ai_remarks": "Rule-based levels from ATR (connect LLM for richer analysis).",
        "llm_used": False,
    }


def _llm_trade_levels(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not candidates:
        return {}

    lines = []
    for m in candidates[:LLM_TOP_N]:
        lines.append(
            f"{m['symbol']}: score={m.get('score')}, LTP={m.get('ltp')}, "
            f"RSI={m.get('rsi')}, ADX={m.get('adx')}, ATR={m.get('atr')}, "
            f"20D={m.get('return_20d_pct')}%, RelStr={m.get('relative_strength_pct')}%"
        )

    prompt = f"""You are an Indian swing trading analyst. For each stock below, suggest swing trade levels.

Stocks:
{chr(10).join(lines)}

Return ONLY a JSON array (no markdown). One object per stock:
[{{
  "symbol": "TICKER",
  "momentum_score": 0-100,
  "entry_price": number,
  "stop_loss": number,
  "target_1": number,
  "target_2": number,
  "risk_reward": number,
  "confidence": 0-100,
  "ai_remarks": "one line rationale"
}}]

Use exact NSE symbols. Prices in INR."""

    raw = call_gemini(prompt) or call_llm(prompt)
    if not raw:
        return {}

    try:
        text = raw.strip()
        if "```" in text:
            text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        data = json.loads(text)
        if not isinstance(data, list):
            return {}
        out: dict[str, dict[str, Any]] = {}
        for item in data:
            sym = str(item.get("symbol", "")).upper()
            if sym:
                item["llm_used"] = True
                out[sym] = item
        return out
    except Exception as e:
        logger.warning("Dashboard LLM parse failed: %s", e)
        return {}


def _metrics_to_dashboard_row(m: dict[str, Any], ai: dict[str, Any]) -> dict[str, Any]:
    trade = ai or _rule_based_trade_levels(m)
    extra = {
        "company": m.get("company"),
        "ltp": m.get("ltp"),
        "change_pct": m.get("change_pct"),
        "return_5d_pct": m.get("return_5d_pct"),
        "return_10d_pct": m.get("return_10d_pct"),
        "return_20d_pct": m.get("return_20d_pct"),
        "volume_ratio": m.get("volume_ratio"),
        "avg_daily_volume": m.get("avg_daily_volume"),
        "rsi": m.get("rsi"),
        "adx": m.get("adx"),
        "atr": m.get("atr"),
        "ema_20": m.get("ema_20"),
        "ema_50": m.get("ema_50"),
        "ema_200": m.get("ema_200"),
        "dist_52w_high_pct": m.get("dist_52w_high_pct"),
        "breakout": m.get("breakout"),
        "relative_strength_pct": m.get("relative_strength_pct"),
        "sector_rank": m.get("sector_rank"),
        "sector": m.get("sector"),
        "rank": m.get("rank"),
        "score": m.get("score"),
        "momentum_score": trade.get("momentum_score") or m.get("score"),
        "entry_price": trade.get("entry_price"),
        "stop_loss": trade.get("stop_loss"),
        "target_1": trade.get("target_1"),
        "target_2": trade.get("target_2"),
        "risk_reward": trade.get("risk_reward"),
        "confidence": trade.get("confidence"),
        "ai_remarks": trade.get("ai_remarks"),
        "llm_used": trade.get("llm_used", False),
        "news_sentiment": m.get("news_sentiment"),
    }
    return {
        "symbol": m["symbol"],
        "price": m.get("ltp") or m.get("close"),
        "delivery_pct": m.get("delivery_pct"),
        "avg_daily_volume": m.get("avg_daily_volume"),
        "extra": extra,
    }


def run_dashboard_scan(
    symbols: list[str],
    news_by_symbol: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    client, err = check_zerodha()
    if err:
        return {
            "tab": TAB_DASHBOARD,
            "filter": filter_tooltip_dict(TAB_DASHBOARD),
            "stocks": [],
            "meta": err,
        }

    if not symbols:
        return {
            "tab": TAB_DASHBOARD,
            "filter": filter_tooltip_dict(TAB_DASHBOARD),
            "stocks": [],
            "meta": {"error": "no_universe", "message": "Run Universe scan first."},
        }

    metrics = build_symbol_metrics(client, symbols, news_by_symbol=news_by_symbol)
    top_for_llm = metrics[:LLM_TOP_N]
    ai_map = _llm_trade_levels(top_for_llm)

    stocks = [_metrics_to_dashboard_row(m, ai_map.get(m["symbol"], {})) for m in metrics]

    llm_configured = bool(settings.gemini_api_key or settings.openai_api_key)
    return {
        "tab": TAB_DASHBOARD,
        "filter": filter_tooltip_dict(TAB_DASHBOARD),
        "stocks": stocks,
        "meta": {
            "universe_count": len(symbols),
            "matched": len(stocks),
            "llm_enriched": len(ai_map),
            "llm_configured": llm_configured,
            "top_score": metrics[0].get("score") if metrics else None,
        },
    }

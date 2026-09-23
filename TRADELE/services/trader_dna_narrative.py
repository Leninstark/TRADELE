"""LLM narrative for Trader DNA — writes verdict from computed stats only."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from TRADELE.services.llm_agent import call_llm_auto, last_llm_provider

logger = logging.getLogger(__name__)


def _compact_stats(stats: dict[str, Any]) -> dict[str, Any]:
    """Shrink payload for the LLM prompt."""
    return {
        "data_quality": stats.get("data_quality"),
        "overall": stats.get("overall"),
        "style_table": stats.get("style_table"),
        "strongest_style_by_stats": stats.get("strongest_style_by_stats"),
        "optimal_holding_bucket": stats.get("optimal_holding_bucket"),
        "holding_table": {
            k: {"trades": v.get("trades"), "win_rate": v.get("win_rate"), "net_pnl": v.get("net_pnl"),
                "expectancy": v.get("expectancy"), "profit_factor": v.get("profit_factor")}
            for k, v in (stats.get("holding_table") or {}).items()
        },
        "opening_bias": stats.get("opening_bias"),
        "winner_loser": stats.get("winner_loser"),
        "profit_distribution": {
            "top_1_pct_of_gross_profit": (stats.get("profit_distribution") or {}).get("top_1_pct_of_gross_profit"),
            "top_5_pct_of_gross_profit": (stats.get("profit_distribution") or {}).get("top_5_pct_of_gross_profit"),
            "top_10_pct_of_gross_profit": (stats.get("profit_distribution") or {}).get("top_10_pct_of_gross_profit"),
            "note": (stats.get("profit_distribution") or {}).get("note"),
            "performance_without": {
                k: {"net_pnl": v.get("net_pnl"), "win_rate": v.get("win_rate"), "trades": v.get("trades")}
                for k, v in ((stats.get("profit_distribution") or {}).get("performance_without") or {}).items()
            },
        },
        "stocks": {
            "best": (stats.get("stocks") or {}).get("best", [])[:8],
            "worst": (stats.get("stocks") or {}).get("worst", [])[:8],
            "repeated_poor": (stats.get("stocks") or {}).get("repeated_poor", [])[:8],
        },
        "sequence": stats.get("sequence"),
        "overtrading": stats.get("overtrading"),
        "risk": stats.get("risk"),
        "style_drift": stats.get("style_drift"),
        "scorecard": stats.get("scorecard"),
        "what_if": stats.get("what_if"),
        "fomo": stats.get("fomo"),
        "market_condition": stats.get("market_condition"),
        "day_of_week": {
            k: {"trades": v.get("trades"), "net_pnl": v.get("net_pnl"), "win_rate": v.get("win_rate")}
            for k, v in (stats.get("day_of_week") or {}).items()
        },
        "monthly_tail": (stats.get("monthly") or [])[-6:],
        "equity_vs_fno": stats.get("equity_vs_fno"),
    }


def template_narrative(stats: dict[str, Any]) -> dict[str, Any]:
    """Rule-based narrative when LLM is unavailable."""
    o = stats.get("overall") or {}
    style = stats.get("strongest_style_by_stats") or "unclear"
    hold = stats.get("optimal_holding_bucket") or "unclear"
    wl = stats.get("winner_loser") or {}
    risk = stats.get("risk") or {}
    drift = stats.get("style_drift") or {}
    what_if = stats.get("what_if") or {}
    return {
        "executive_summary": (
            f"Completed trades: {o.get('trades')}. Net P&L ₹{o.get('net_pnl')}. "
            f"Win rate {o.get('win_rate')}%. Expectancy ₹{o.get('expectancy')} per trade. "
            f"Statistically strongest style bucket: {style}. Optimal holding bucket (n≥8): {hold}. "
            f"Risk rating: {risk.get('rating')} (max DD ₹{risk.get('max_drawdown')}). "
            "This summary is template-generated (LLM unavailable)."
        ),
        "scorecard_notes": "Scores are heuristic from sample sizes and expectancy; treat thin buckets cautiously.",
        "top_strengths": [
            {"rank": 1, "title": f"Edge in {style}" if style != "unclear" else "Insufficient style edge", "evidence": f"strongest_style_by_stats={style}"},
            {"rank": 2, "title": f"Holding window {hold}", "evidence": f"optimal_holding_bucket={hold}"},
            {"rank": 3, "title": "Documented risk metrics", "evidence": f"max_dd={risk.get('max_drawdown')}"},
            {"rank": 4, "title": "FIFO-reconstructed sample", "evidence": f"trades={o.get('trades')}"},
            {"rank": 5, "title": "Style vs product separation", "evidence": "Holding style classified by dates, not CNC/MIS alone"},
        ],
        "top_mistakes": [
            {"rank": 1, "behavior": wl.get("interpretation"), "evidence": wl, "cost_hint": "See winner vs loser hold asymmetry"},
            {"rank": 2, "behavior": (stats.get("overtrading") or {}).get("note"), "evidence": "overtrading section"},
            {"rank": 3, "behavior": (stats.get("sequence") or {}).get("caution"), "evidence": "sequence after loss"},
            {"rank": 4, "behavior": drift.get("note"), "evidence": drift},
            {"rank": 5, "behavior": (stats.get("profit_distribution") or {}).get("note"), "evidence": "profit concentration"},
        ],
        "best_trading_style": {
            "recommendation": style,
            "holding": hold,
            "rationale": "Chosen from expectancy × log(sample size), not raw P&L alone.",
        },
        "what_if_commentary": what_if.get("assumption"),
        "personalized_rules": {
            "trading_style": style,
            "holding_period": hold,
            "preferred_entry_time": "Needs further testing" if not (stats.get("entry_timing") or {}) else "See entry_timing table",
            "max_position_size": "Needs further testing",
            "max_daily_trades": (stats.get("overtrading") or {}).get("trades_per_day_median"),
            "max_consecutive_losses": "Needs further testing",
            "stop_loss_framework": "Needs further testing — MAE unavailable without candles",
            "profit_taking_framework": "Needs further testing — MFE unavailable without candles",
            "re_entry_rule": "Avoid same-day re-entry until reviewed",
            "do_not_trade_when": "After a loss streak if size escalates (see sequence caution)",
        },
        "final_verdict": {
            "who_am_i": f"A trader whose stats currently favour {style} over other buckets (sample-dependent).",
            "good_at": style,
            "bad_at": what_if.get("avoid_style") or "unclear",
            "money_comes_from": (stats.get("profit_distribution") or {}).get("note"),
            "costliest_behavior": wl.get("interpretation"),
            "best_holding": hold,
            "intraday_or_swing": style,
            "biggest_psychological_risk": (stats.get("sequence") or {}).get("caution"),
            "biggest_edge": style,
            "stop_doing": what_if.get("avoid_style") or "Overtrading on high-activity days if expectancy falls",
            "do_more": f"Trades in holding bucket {hold}" if hold != "unclear" else "Build sample in strongest style",
        },
        "personality": [style.replace("_", " ") if style else "hybrid trader"],
        "llm_used": False,
    }


def _extract_json(text: str) -> Optional[dict[str, Any]]:
    text = (text or "").strip()
    if "```" in text:
        text = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    if not text.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", text)
        text = m.group(0) if m else text
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def generate_trader_dna_narrative(stats: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_stats(stats)
    prompt = f"""You are a quantitative trading analyst, behavioral finance analyst, and risk manager.
You receive PRE-COMPUTED statistics from a FIFO trade reconstruction. Do NOT invent numbers.
Do not flatter. Do not claim psychology without citing the provided stats.
If sample size is thin (<5 or <8 as noted), say so.

Stats JSON:
{json.dumps(compact, default=str)[:28000]}

Return ONLY a JSON object with these keys:
{{
  "executive_summary": "8-12 sentences, brutally honest",
  "scorecard_notes": "short paragraph on scorecard interpretation",
  "top_strengths": [{{"rank":1,"title":"...","evidence":"cite metrics"}}, ... 5 items],
  "top_mistakes": [{{"rank":1,"behavior":"...","frequency":"...","cost_hint":"...","evidence":"...","fix":"..."}}, ... 5 items],
  "best_trading_style": {{"recommendation":"A-F style label","holding":"...","rationale":"..."}},
  "what_if_commentary": "interpret the historical what-if only",
  "personalized_rules": {{
    "trading_style":"...",
    "holding_period":"...",
    "preferred_entry_time":"..." ,
    "max_position_size":"Needs further testing or value",
    "max_daily_trades":"...",
    "max_consecutive_losses":"...",
    "stop_loss_framework":"...",
    "profit_taking_framework":"...",
    "re_entry_rule":"...",
    "do_not_trade_when":"..."
  }},
  "final_verdict": {{
    "who_am_i":"...",
    "good_at":"...",
    "bad_at":"...",
    "money_comes_from":"...",
    "costliest_behavior":"...",
    "best_holding":"...",
    "intraday_or_swing":"...",
    "biggest_psychological_risk":"...",
    "biggest_edge":"...",
    "stop_doing":"...",
    "do_more":"..."
  }},
  "personality": ["one or more labels from: intraday scalper, momentum trader, swing trader, positional trader, overactive trader, hybrid trader, opportunistic trader"]
}}
"""
    raw = call_llm_auto(prompt)
    provider = last_llm_provider()
    if not raw:
        out = template_narrative(stats)
        out["llm_provider"] = None
        return out
    parsed = _extract_json(raw)
    if not parsed:
        logger.warning("Trader DNA narrative JSON parse failed")
        out = template_narrative(stats)
        out["llm_provider"] = provider
        out["parse_failed"] = True
        return out
    parsed["llm_used"] = True
    parsed["llm_provider"] = provider
    return parsed

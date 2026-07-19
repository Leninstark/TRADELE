"""
LangGraph agent: scan NSE stocks for 30-day momentum.

Pipeline:
  1. Resolve universe (capped for speed)
  2. Fetch last ~30 trading days OHLCV via Zerodha
  3. Score momentum (returns, volume trend, RSI, EMA alignment)
  4. Rank top candidates
  5. Gemini explains picks with confidence and risk notes
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from TRADELE.config import settings
from TRADELE.db.session import SessionLocal
from TRADELE.engines.indicators.calculator import IndicatorCalculator
from TRADELE.services.data_fetcher import apply_liquidity_filters, fetch_eod_batch
from TRADELE.services.llm_agent import call_gemini, call_llm
from TRADELE.services.universe import NIFTY500_SAMPLE, get_tradeable_equity_symbols
from TRADELE.services.zerodha_client import get_client

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 30
MIN_TRADING_DAYS = 20

try:
    from langgraph.graph import END, START, StateGraph
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    StateGraph = None
    START = END = None

try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict


class MomentumAgentState(TypedDict, total=False):
    lookback_days: int
    top_n: int
    max_symbols: int
    symbols: list[str]
    symbol_data: dict[str, list[dict]]
    scored: list[dict[str, Any]]
    top_candidates: list[dict[str, Any]]
    ai_summary: str
    picks: list[dict[str, Any]]
    errors: list[str]
    meta: dict[str, Any]


def _extract_json(raw: str) -> str:
    raw = raw.strip()
    if "```json" in raw:
        return raw.split("```json")[1].split("```")[0].strip()
    if "```" in raw:
        return raw.split("```")[1].replace("json", "").strip()
    return raw


def compute_momentum_metrics(symbol: str, candles: list[dict]) -> Optional[dict[str, Any]]:
    """Rule-based 30-day momentum score for one symbol."""
    if len(candles) < MIN_TRADING_DAYS:
        return None

    calc = IndicatorCalculator()
    indicators = calc.compute(symbol, candles)
    if not indicators:
        return None

    closes = [float(c["close"]) for c in candles]
    volumes = [float(c.get("volume", 0)) for c in candles]

    n = min(LOOKBACK_DAYS, len(closes) - 1)
    close_now = closes[-1]
    close_30d = closes[-1 - n]
    close_5d = closes[-6] if len(closes) >= 6 else closes[0]

    return_30d = (close_now - close_30d) / close_30d * 100 if close_30d else 0.0
    return_5d = (close_now - close_5d) / close_5d * 100 if close_5d else 0.0

    vol_recent = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else volumes[-1]
    vol_prior = sum(volumes[-25:-5]) / 20 if len(volumes) >= 25 else sum(volumes[:-5]) / max(len(volumes) - 5, 1)
    volume_trend = vol_recent / vol_prior if vol_prior else 1.0

    green_days = sum(1 for i in range(-n, 0) if closes[i] > closes[i - 1])
    green_pct = green_days / n * 100

    high_30d = max(float(c["high"]) for c in candles[-n:])
    dist_from_high_pct = (close_now - high_30d) / high_30d * 100 if high_30d else 0.0

    rsi = indicators.get("rsi") or 50.0
    ema_20 = indicators.get("ema_20")
    ema_50 = indicators.get("ema_50")

    trend_score = 0.0
    if ema_20 and ema_50:
        if close_now > ema_20 > ema_50:
            trend_score = 1.0
        elif close_now > ema_20:
            trend_score = 0.6
        elif close_now > ema_50:
            trend_score = 0.3

    rsi_score = 1.0 if 55 <= rsi <= 75 else (0.7 if 45 <= rsi < 55 else 0.4)

    # Weighted momentum score (0–100)
    raw_score = (
        min(max(return_30d, -10), 30) / 30 * 35
        + min(max(return_5d, -5), 15) / 15 * 20
        + min(volume_trend, 3) / 3 * 15
        + trend_score * 15
        + rsi_score * 10
        + min(green_pct, 70) / 70 * 5
    )

    if return_30d <= 0:
        return None

    return {
        "symbol": symbol,
        "close": round(close_now, 2),
        "return_30d_pct": round(return_30d, 2),
        "return_5d_pct": round(return_5d, 2),
        "volume_trend": round(volume_trend, 2),
        "rsi": round(rsi, 1),
        "green_days_pct": round(green_pct, 1),
        "dist_from_30d_high_pct": round(dist_from_high_pct, 2),
        "above_ema20": bool(ema_20 and close_now > ema_20),
        "ema_aligned": bool(ema_20 and ema_50 and ema_20 > ema_50),
        "momentum_score": round(raw_score, 1),
        "rating": _score_to_rating(raw_score),
    }


def _score_to_rating(score: float) -> str:
    if score >= 75:
        return "Strong Momentum"
    if score >= 60:
        return "Momentum"
    if score >= 45:
        return "Building"
    return "Weak"


def node_resolve_universe(state: dict[str, Any]) -> dict[str, Any]:
    max_symbols = state.get("max_symbols") or getattr(settings, "momentum_max_symbols", 50)
    client = get_client()
    symbols = get_tradeable_equity_symbols(client=client)[:max_symbols]
    if not symbols:
        symbols = list(NIFTY500_SAMPLE)
    return {
        "symbols": symbols,
        "errors": state.get("errors") or [],
        "meta": {"universe_size": len(symbols)},
    }


def node_fetch_data(state: dict[str, Any]) -> dict[str, Any]:
    lookback = state.get("lookback_days") or LOOKBACK_DAYS
    symbols = state.get("symbols") or []
    errors = list(state.get("errors") or [])

    db = SessionLocal()
    try:
        client = get_client()
        symbol_data = fetch_eod_batch(client, db, symbols=symbols, lookback_days=lookback + 10)
        symbol_data = apply_liquidity_filters(symbol_data)
    except Exception as e:
        logger.exception("Momentum fetch failed: %s", e)
        errors.append(f"Data fetch failed: {e}")
        symbol_data = {}
    finally:
        db.close()

    return {
        "symbol_data": symbol_data,
        "errors": errors,
        "meta": {**(state.get("meta") or {}), "fetched": len(symbol_data)},
    }


def node_score_momentum(state: dict[str, Any]) -> dict[str, Any]:
    symbol_data = state.get("symbol_data") or {}
    scored: list[dict[str, Any]] = []

    for symbol, candles in symbol_data.items():
        metrics = compute_momentum_metrics(symbol, candles)
        if metrics:
            scored.append(metrics)

    scored.sort(key=lambda x: x["momentum_score"], reverse=True)
    top_n = state.get("top_n") or 15
    top_candidates = scored[: max(top_n * 2, 20)]

    return {
        "scored": scored,
        "top_candidates": top_candidates,
        "meta": {**(state.get("meta") or {}), "scored_count": len(scored)},
    }


def node_gemini_analyze(state: dict[str, Any]) -> dict[str, Any]:
    candidates = state.get("top_candidates") or []
    top_n = state.get("top_n") or 15
    errors = list(state.get("errors") or [])

    if not candidates:
        return {
            "ai_summary": "No momentum candidates found. Ensure KITE_ACCESS_TOKEN is set and market data is available.",
            "picks": [],
            "errors": errors,
        }

    lines = [
        "You are an expert Indian equity momentum analyst (NSE).",
        f"Analyze these stocks with strong 30-day momentum. Pick the best {top_n} for swing/positional trades.",
        "Consider: sustained vs fading momentum, volume confirmation, RSI not overbought (>80 = caution), distance from 30d high.",
        "",
        "## Candidates (30-day momentum scan)",
    ]
    for i, c in enumerate(candidates[:25], 1):
        lines.append(
            f"{i}. {c['symbol']} | 30d: +{c['return_30d_pct']}% | 5d: {c['return_5d_pct']:+.1f}% | "
            f"Vol trend: {c['volume_trend']:.1f}x | RSI: {c['rsi']} | Score: {c['momentum_score']} | "
            f"From 30d high: {c['dist_from_30d_high_pct']:.1f}%"
        )
    lines.append("")
    lines.append(
        'Respond with ONLY valid JSON (no markdown): '
        '{"summary": "2-3 sentence market momentum take", '
        '"picks": [{"symbol": "RELIANCE", "confidence": 88, "rating": "Strong Buy", '
        '"reasons": ["reason1", "reason2"], "risk": "one line risk note", '
        '"return_30d_pct": 12.5, "hold_period": "2-4 weeks"}]}'
    )
    prompt = "\n".join(lines)

    raw = call_gemini(prompt) if settings.gemini_api_key else None
    if not raw:
        raw = call_llm(prompt)

    if not raw:
        picks = [_candidate_to_pick(c, confidence=c["momentum_score"]) for c in candidates[:top_n]]
        return {
            "ai_summary": "Rule-based momentum scan (LLM not configured).",
            "picks": picks,
            "errors": errors,
        }

    try:
        data = json.loads(_extract_json(raw))
        summary = data.get("summary") or "Momentum scan complete."
        llm_picks = data.get("picks") or []
        picks = []
        candidate_map = {c["symbol"]: c for c in candidates}

        for p in llm_picks[:top_n]:
            sym = (p.get("symbol") or "").upper()
            base = candidate_map.get(sym, {})
            picks.append({
                "symbol": sym,
                "confidence": p.get("confidence") or base.get("momentum_score", 0),
                "rating": p.get("rating") or base.get("rating", "Momentum"),
                "reasons": p.get("reasons") or _auto_reasons(base),
                "risk": p.get("risk") or "",
                "return_30d_pct": p.get("return_30d_pct") or base.get("return_30d_pct"),
                "return_5d_pct": base.get("return_5d_pct"),
                "volume_trend": base.get("volume_trend"),
                "rsi": base.get("rsi"),
                "momentum_score": base.get("momentum_score"),
                "hold_period": p.get("hold_period") or "2-4 weeks",
                "close": base.get("close"),
            })

        if not picks:
            picks = [_candidate_to_pick(c, confidence=c["momentum_score"]) for c in candidates[:top_n]]

        return {"ai_summary": summary, "picks": picks, "errors": errors}
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Momentum LLM parse failed: %s", e)
        picks = [_candidate_to_pick(c, confidence=c["momentum_score"]) for c in candidates[:top_n]]
        return {
            "ai_summary": raw[:400] if raw else "Parse error",
            "picks": picks,
            "errors": errors + [f"LLM parse error: {e}"],
        }


def _auto_reasons(c: dict[str, Any]) -> list[str]:
    reasons = [f"30-day return +{c.get('return_30d_pct', 0)}%"]
    if c.get("volume_trend", 0) >= 1.3:
        reasons.append(f"Volume expanding {c['volume_trend']:.1f}x")
    if c.get("ema_aligned"):
        reasons.append("EMA20 > EMA50 uptrend")
    if c.get("rsi"):
        reasons.append(f"RSI {c['rsi']}")
    return reasons


def _candidate_to_pick(c: dict[str, Any], confidence: float) -> dict[str, Any]:
    return {
        "symbol": c["symbol"],
        "confidence": confidence,
        "rating": c.get("rating", "Momentum"),
        "reasons": _auto_reasons(c),
        "risk": "Momentum can reverse; use stop-loss below recent swing low.",
        "return_30d_pct": c.get("return_30d_pct"),
        "return_5d_pct": c.get("return_5d_pct"),
        "volume_trend": c.get("volume_trend"),
        "rsi": c.get("rsi"),
        "momentum_score": c.get("momentum_score"),
        "hold_period": "2-4 weeks",
        "close": c.get("close"),
    }


def build_momentum_agent():
    if not LANGGRAPH_AVAILABLE:
        return None
    workflow = StateGraph(MomentumAgentState)
    workflow.add_node("resolve_universe", node_resolve_universe)
    workflow.add_node("fetch_data", node_fetch_data)
    workflow.add_node("score_momentum", node_score_momentum)
    workflow.add_node("gemini_analyze", node_gemini_analyze)
    workflow.add_edge(START, "resolve_universe")
    workflow.add_edge("resolve_universe", "fetch_data")
    workflow.add_edge("fetch_data", "score_momentum")
    workflow.add_edge("score_momentum", "gemini_analyze")
    workflow.add_edge("gemini_analyze", END)
    return workflow.compile()


_agent = None


def get_momentum_agent():
    global _agent
    if _agent is None:
        _agent = build_momentum_agent()
    return _agent


def run_momentum_agent(
    *,
    lookback_days: int = LOOKBACK_DAYS,
    top_n: int = 15,
    max_symbols: Optional[int] = None,
) -> dict[str, Any]:
    """
    Run the 30-day momentum LangGraph agent.
    Returns picks, AI summary, full scored list, and metadata.
    """
    max_symbols = max_symbols or getattr(settings, "momentum_max_symbols", 50)
    initial: dict[str, Any] = {
        "lookback_days": lookback_days,
        "top_n": top_n,
        "max_symbols": max_symbols,
        "errors": [],
    }

    agent = get_momentum_agent()
    if agent is None:
        result = node_gemini_analyze(node_score_momentum(node_fetch_data(node_resolve_universe(initial))))
        return _format_response(result, lookback_days, max_symbols)

    result = agent.invoke(initial)
    return _format_response(result, lookback_days, max_symbols)


def _format_response(result: dict[str, Any], lookback_days: int, max_symbols: int) -> dict[str, Any]:
    return {
        "agent": "momentum_30d",
        "lookback_days": lookback_days,
        "max_symbols": max_symbols,
        "ai_summary": result.get("ai_summary") or "",
        "picks": result.get("picks") or [],
        "all_scored": result.get("scored") or [],
        "meta": result.get("meta") or {},
        "errors": result.get("errors") or [],
    }

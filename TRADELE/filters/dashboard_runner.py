"""Dashboard swing tab — early +20% / 2-week candidates with AI justification."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from TRADELE.filters.swing_definitions import TAB_DASHBOARD, filter_tooltip_dict
from TRADELE.filters.swing_helpers import check_zerodha
from TRADELE.filters.symbol_metrics import build_symbol_metrics
from TRADELE.services.llm_agent import call_llm_auto, llm_is_configured

logger = logging.getLogger(__name__)

# Enrich strongest early-setup names (keep small — Claude CLI often times out on 40 theses)
LLM_TOP_N = 15
# Rank / display horizon: 2-week upside board
HORIZON_DAYS = 14
MIN_EXPECTED_MOVE_PCT = 20.0  # conviction badge threshold (not a hard exclude)
MIN_SWING_SCORE = 55
MIN_CONFIDENCE = 50
MAX_DASHBOARD_ROWS = 20

# Weights tuned for early 2-week swings (identify BEFORE the big move)
SWING_WEIGHTS: dict[str, int] = {
    "setup_quality": 22,       # EMA / RSI / ADX forming, not late
    "volume": 15,              # participation building
    "delivery": 12,            # institutional accumulation
    "relative_strength": 10,   # outperforming Nifty, not extended
    "breakout_proximity": 12,  # coiled near breakout
    "news": 18,                # catalysts / sentiment (raised vs generic score)
    "sector_strength": 6,
    "not_extended": 5,         # penalise already-run names
}


def _clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _estimate_2w_upside_pct(m: dict[str, Any]) -> float:
    """Realistic 2-week upside estimate from ATR + recent momentum (no LLM)."""
    close = _f(m.get("ltp") or m.get("close"))
    if close <= 0:
        return 0.0
    atr = _f(m.get("atr"), close * 0.02)
    ret5 = max(_f(m.get("return_5d_pct")), 0.0)
    ret10 = max(_f(m.get("return_10d_pct")), 0.0)
    rs = max(_f(m.get("relative_strength_pct")), 0.0)
    vol = max(_f(m.get("volume_ratio"), 1.0), 1.0)

    atr_pct = (atr / close) * 100
    # ~10 trading sessions in 2 weeks of directional ATR moves
    atr_2w = atr_pct * (10 ** 0.5)
    # Momentum continuation scaled to 14 calendar days
    mom_2w = max(ret5 * (14 / 5), ret10 * (14 / 10))
    # Mild RS / volume boost (capped)
    boost = min(6.0, rs * 0.25 + max(vol - 1.0, 0.0) * 1.5)
    est = max(atr_2w, mom_2w * 0.85) + boost * 0.35
    return round(_clamp(est, 0.0, 45.0), 1)


def _expected_move_pct(trade: dict[str, Any], swing: dict[str, Any]) -> float:
    """Best available upside estimate (LLM expected move, else math 2w estimate)."""
    raw = trade.get("expected_move_pct")
    if raw is not None:
        return _f(raw)
    entry = _f(trade.get("entry_price"))
    t2 = _f(trade.get("target_2"))
    if entry > 0 and t2 > entry:
        return round((t2 - entry) / entry * 100, 1)
    return _f(swing.get("potential_pct_atr"))


def _meets_swing_conviction(trade: dict[str, Any], swing: dict[str, Any]) -> bool:
    """True when estimated 2-week upside clears the +20% conviction bar."""
    return _expected_move_pct(trade, swing) >= MIN_EXPECTED_MOVE_PCT


def compute_swing_month_score(m: dict[str, Any]) -> dict[str, Any]:
    """
    Score for early 2-week swing candidates aiming for +20% moves.
    Prefers setups that are forming — not names already up big.
    """
    close = _f(m.get("ltp") or m.get("close"))
    ret5 = _f(m.get("return_5d_pct"))
    ret10 = _f(m.get("return_10d_pct"))
    ret20 = _f(m.get("return_20d_pct"))
    vol = _f(m.get("volume_ratio"), 1.0)
    deliv = _f(m.get("delivery_pct"))
    rs = _f(m.get("relative_strength_pct"))
    rsi = _f(m.get("rsi"), 50.0)
    adx = _f(m.get("adx"), 15.0)
    ema20 = m.get("ema_20")
    ema50 = m.get("ema_50")
    ema200 = m.get("ema_200")
    high_20d = m.get("high_20d")
    breakout = bool(m.get("breakout"))

    # Setup quality: bullish structure with room to run (RSI not overbought)
    setup = 25.0
    if ema20 and ema50 and ema200 and close > float(ema20) > float(ema50) > float(ema200):
        setup = 95.0
    elif ema20 and ema50 and close > float(ema20) > float(ema50):
        setup = 80.0
    elif ema20 and close > float(ema20):
        setup = 60.0
    if 52 <= rsi <= 68:
        setup = min(100.0, setup + 8)
    elif rsi > 75:
        setup = max(20.0, setup - 25)  # already extended / late
    if adx >= 25:
        setup = min(100.0, setup + 10)
    elif adx >= 18:
        setup = min(100.0, setup + 5)

    # Volume building into the move
    volume_score = _clamp(vol / 2.5 * 100)

    # Delivery / accumulation
    delivery_score = _clamp(deliv / 55 * 100) if deliv else 40.0

    # Relative strength — positive but not already parabolic
    if rs >= 8:
        rs_score = 90.0
    elif rs >= 3:
        rs_score = 75.0
    elif rs >= 0:
        rs_score = 55.0
    else:
        rs_score = _clamp(40 + rs * 2)

    # Near breakout (coiled) scores higher than already broken + extended
    if high_20d and close:
        dist = (float(high_20d) - close) / float(high_20d) * 100
        if breakout and ret20 < 12:
            breakout_score = 95.0  # fresh breakout, not late
        elif 0 < dist <= 3:
            breakout_score = 100.0  # coiled under resistance — ideal early entry
        elif 3 < dist <= 6:
            breakout_score = 75.0
        elif breakout:
            breakout_score = 55.0
        else:
            breakout_score = _clamp(50 - dist * 3)
    else:
        breakout_score = 45.0

    # News / catalysts
    news_sent = (m.get("news_sentiment") or "").lower()
    news_raw = m.get("news_score")
    if news_sent == "positive":
        news_score = _clamp(_f(news_raw, 80))
    elif news_sent == "negative":
        news_score = _clamp(_f(news_raw, 25))
    elif news_raw is not None:
        news_score = _clamp(_f(news_raw, 50))
    else:
        news_score = 50.0  # neutral / missing

    # Sector
    sector_rank = m.get("sector_rank")
    total_sectors = int(m.get("total_sectors") or 1)
    if sector_rank and total_sectors > 1:
        sector_score = _clamp((1 - (int(sector_rank) - 1) / (total_sectors - 1)) * 100)
    else:
        sector_score = 50.0

    # Penalise already-run names (late to the party)
    if ret20 >= 25:
        not_extended = 15.0
    elif ret20 >= 18:
        not_extended = 35.0
    elif ret20 >= 12:
        not_extended = 60.0
    elif ret5 >= 10 and ret10 >= 15:
        not_extended = 40.0
    else:
        not_extended = 90.0

    components = {
        "setup_quality": round(setup, 1),
        "volume": round(volume_score, 1),
        "delivery": round(delivery_score, 1),
        "relative_strength": round(rs_score, 1),
        "breakout_proximity": round(breakout_score, 1),
        "news": round(news_score, 1),
        "sector_strength": round(sector_score, 1),
        "not_extended": round(not_extended, 1),
    }
    weight_sum = sum(SWING_WEIGHTS.values())
    total = sum(components[k] * SWING_WEIGHTS[k] for k in SWING_WEIGHTS) / weight_sum

    potential_pct = _estimate_2w_upside_pct(m)

    return {
        "swing_score": round(total, 1),
        "components": components,
        "weights": SWING_WEIGHTS,
        "potential_pct_atr": potential_pct,
    }


def _is_early_swing_candidate(m: dict[str, Any], swing: dict[str, Any]) -> bool:
    """Filter: forming setup, not already a late chase."""
    ret20 = _f(m.get("return_20d_pct"))
    rsi = _f(m.get("rsi"), 50.0)
    score = swing["swing_score"]
    if score < MIN_SWING_SCORE:
        return False
    if ret20 >= 28:  # already ran hard — skip late entries
        return False
    if rsi >= 82:
        return False
    return True


def _rule_based_ai(m: dict[str, Any], swing: dict[str, Any]) -> dict[str, Any]:
    """Fallback when Gemini is unavailable — still structured, but flagged."""
    close = _f(m.get("ltp") or m.get("close"))
    atr = _f(m.get("atr"), close * 0.02)
    entry = round(close, 2)
    stop = round(close - 1.5 * atr, 2)
    # Align targets with 2-week +20% conviction when ATR room supports it
    t1 = round(max(close + 2.5 * atr, close * 1.12), 2)
    t2 = round(max(close + 4.0 * atr, close * 1.20), 2)
    risk = entry - stop
    reward = t1 - entry
    rr = round(reward / risk, 2) if risk > 0 else None
    conf = int(_clamp(swing["swing_score"]))
    comps = swing["components"]
    expected = swing["potential_pct_atr"]
    conviction = expected >= MIN_EXPECTED_MOVE_PCT
    why = (
        f"Early 2-week setup (math score {swing['swing_score']}). "
        f"Setup {comps.get('setup_quality')}, vol {comps.get('volume')}, "
        f"delivery {comps.get('delivery')}, RS {comps.get('relative_strength')}, "
        f"breakout coil {comps.get('breakout_proximity')}, news {comps.get('news')}. "
        f"Estimated 2-week upside ~{expected}% "
        f"({'meets' if conviction else 'below'} +{MIN_EXPECTED_MOVE_PCT:.0f}% conviction bar)."
    )
    return {
        "entry_price": entry,
        "stop_loss": stop,
        "target_1": t1,
        "target_2": t2,
        "risk_reward": rr,
        "confidence": conf,
        "expected_move_pct": expected,
        "horizon_days": HORIZON_DAYS,
        "ai_remarks": why[:280],
        "justification": why,
        "conviction_points": [
            f"Swing score {swing['swing_score']}/100 from weighted metrics + news",
            f"Volume ratio {m.get('volume_ratio')} · Delivery {m.get('delivery_pct')}%",
            f"RSI {m.get('rsi')} · ADX {m.get('adx')} · Rel strength {m.get('relative_strength_pct')}%",
        ],
        "risks": [
            (
                "AI thesis unavailable for this name — levels are ATR-based only"
                if llm_is_configured()
                else "LLM not configured — levels are ATR-based only"
            ),
            "News catalyst may be thin",
        ],
        "catalysts": [],
        "llm_used": False,
    }


def _llm_swing_theses(candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Ask Gemini for a strong +20% / 2-week thesis per early-setup stock."""
    if not candidates:
        return {}

    lines = []
    for m in candidates[:LLM_TOP_N]:
        swing = m["_swing"]
        lines.append(
            f"{m['symbol']} ({m.get('company')}) | sector={m.get('sector')} | "
            f"LTP={m.get('ltp')} | swing_score={swing['swing_score']} | "
            f"components={swing['components']} | "
            f"5D={m.get('return_5d_pct')}% 10D={m.get('return_10d_pct')}% 20D={m.get('return_20d_pct')}% | "
            f"vol_ratio={m.get('volume_ratio')} deliv={m.get('delivery_pct')}% | "
            f"RSI={m.get('rsi')} ADX={m.get('adx')} ATR={m.get('atr')} | "
            f"EMA20={m.get('ema_20')} EMA50={m.get('ema_50')} EMA200={m.get('ema_200')} | "
            f"breakout={m.get('breakout')} dist_52w={m.get('dist_52w_high_pct')}% | "
            f"RS={m.get('relative_strength_pct')}% sector_rank={m.get('sector_rank')} | "
            f"news={m.get('news_sentiment')} news_score={m.get('news_score')}"
        )

    prompt = f"""You are a senior Indian NSE swing trader. Each stock below is an EARLY setup —
we want names that can deliver AT LEAST +{MIN_EXPECTED_MOVE_PCT:.0f}% in the NEXT {HORIZON_DAYS} DAYS
(about 2 weeks), identified BEFORE the big move (not chasing names that already ran).

Use the quantitative metrics AND news/sector context. Be evidence-backed and specific (cite numbers).

Stocks:
{chr(10).join(lines)}

Return ONLY a JSON array (no markdown). Rank the best early setups by realistic
{HORIZON_DAYS}-day upside %. Prefer names that can make +{MIN_EXPECTED_MOVE_PCT:.0f}%+,
but still include the strongest setups even if expected upside is under that bar.
Skip only late / overbought / weak setups. Exact NSE symbols.

[{{
  "symbol": "TICKER",
  "confidence": 55-95,
  "expected_move_pct": number (your {HORIZON_DAYS}-day upside estimate),
  "entry_price": number,
  "stop_loss": number,
  "target_1": number,
  "target_2": number,
  "risk_reward": number,
  "ai_remarks": "1-2 sentence punchy thesis",
  "justification": "4-8 sentences. Why this can move in {HORIZON_DAYS} days. Cite RSI/ADX/EMA/volume/delivery/RS/news. Explain why it is EARLY (not late).",
  "conviction_points": ["bullet with evidence", "bullet", "bullet"],
  "catalysts": ["news or sector trigger"],
  "risks": ["key risk"]
}}]"""

    from TRADELE.services.llm_agent import last_llm_error, last_llm_provider

    raw = call_llm_auto(prompt)
    if not raw:
        logger.warning(
            "Dashboard swing LLM returned empty (provider=%s err=%s)",
            last_llm_provider(),
            last_llm_error(),
        )
        return {}

    try:
        text = raw.strip()
        if "```" in text:
            text = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
        # Models often wrap JSON in prose — extract the first array
        if not text.startswith("["):
            m = re.search(r"\[[\s\S]*\]", text)
            text = m.group(0) if m else text
        data = json.loads(text)
        if not isinstance(data, list):
            logger.warning("Dashboard swing LLM JSON was not a list (%s)", type(data).__name__)
            return {}
        out: dict[str, dict[str, Any]] = {}
        provider = last_llm_provider() or "llm"
        for item in data:
            if not isinstance(item, dict):
                continue
            sym = str(item.get("symbol", "")).upper().strip()
            if not sym:
                continue
            item["llm_used"] = True
            item["llm_provider"] = provider
            item["horizon_days"] = HORIZON_DAYS
            if not item.get("justification"):
                item["justification"] = item.get("ai_remarks") or ""
            out[sym] = item
        logger.info(
            "Dashboard swing LLM theses: %s symbols via %s",
            len(out),
            provider,
        )
        return out
    except Exception as e:
        logger.warning(
            "Dashboard swing LLM parse failed: %s (provider=%s preview=%r)",
            e,
            last_llm_provider(),
            (raw or "")[:180],
        )
        return {}


def _metrics_to_dashboard_row(m: dict[str, Any], ai: dict[str, Any], swing: dict[str, Any]) -> dict[str, Any]:
    trade = ai or _rule_based_ai(m, swing)
    conf = int(trade.get("confidence") or swing["swing_score"])
    expected = _expected_move_pct(trade, swing)
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
        "score": swing["swing_score"],
        "swing_score": swing["swing_score"],
        "score_components": swing["components"],
        "score_weights": swing["weights"],
        "momentum_score": swing["swing_score"],
        "entry_price": trade.get("entry_price"),
        "stop_loss": trade.get("stop_loss"),
        "target_1": trade.get("target_1"),
        "target_2": trade.get("target_2"),
        "risk_reward": trade.get("risk_reward"),
        "confidence": conf,
        "expected_move_pct": expected,
        "conviction_met": expected >= MIN_EXPECTED_MOVE_PCT,
        "horizon_days": trade.get("horizon_days") or HORIZON_DAYS,
        "ai_remarks": trade.get("ai_remarks"),
        "justification": trade.get("justification") or trade.get("ai_remarks"),
        "conviction_points": trade.get("conviction_points") or [],
        "catalysts": trade.get("catalysts") or [],
        "risks": trade.get("risks") or [],
        "llm_used": trade.get("llm_used", False),
        "llm_provider": trade.get("llm_provider"),
        "news_sentiment": m.get("news_sentiment"),
        "news_score": m.get("news_score"),
        "delivery_pct": m.get("delivery_pct"),
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

    scored: list[dict[str, Any]] = []
    for m in metrics:
        swing = compute_swing_month_score(m)
        if not _is_early_swing_candidate(m, swing):
            continue
        m["_swing"] = swing
        scored.append(m)

    scored.sort(key=lambda x: x["_swing"]["swing_score"], reverse=True)
    top = scored[:LLM_TOP_N]
    ai_map = _llm_swing_theses(top)

    # Prefer LLM-selected names; fill with math-ranked early setups
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    llm_ordered = sorted(
        ((sym, ai) for sym, ai in ai_map.items()),
        key=lambda kv: (
            _f(kv[1].get("expected_move_pct")),
            int(kv[1].get("confidence") or 0),
        ),
        reverse=True,
    )
    metrics_by_sym = {m["symbol"]: m for m in scored}
    for sym, ai in llm_ordered:
        m = metrics_by_sym.get(sym)
        if not m:
            continue
        conf = int(ai.get("confidence") or 0)
        if conf < MIN_CONFIDENCE:
            continue
        rows.append(_metrics_to_dashboard_row(m, ai, m["_swing"]))
        seen.add(sym)

    for m in scored:
        if m["symbol"] in seen:
            continue
        ai = ai_map.get(m["symbol"], {})
        trade = ai or _rule_based_ai(m, m["_swing"])
        if int(trade.get("confidence") or m["_swing"]["swing_score"]) < MIN_CONFIDENCE:
            continue
        rows.append(_metrics_to_dashboard_row(m, ai, m["_swing"]))
        seen.add(m["symbol"])

    # Top 20 by estimated 2-week upside %
    rows.sort(
        key=lambda r: (
            _f((r.get("extra") or {}).get("expected_move_pct")),
            _f((r.get("extra") or {}).get("confidence")),
        ),
        reverse=True,
    )
    rows = rows[:MAX_DASHBOARD_ROWS]
    for i, r in enumerate(rows, 1):
        r["extra"]["rank"] = i

    from TRADELE.services.llm_agent import last_llm_error, last_llm_provider

    llm_configured = llm_is_configured()
    llm_count = sum(1 for r in rows if r["extra"].get("llm_used"))
    conviction_count = sum(1 for r in rows if r["extra"].get("conviction_met"))
    provider = last_llm_provider()
    llm_err = last_llm_error()
    note = (
        f"Top {len(rows)} by estimated {HORIZON_DAYS}-day upside % "
        f"({conviction_count} meet +{MIN_EXPECTED_MOVE_PCT:.0f}% bar"
        f"{f'; {llm_count} LLM thesis via {provider}' if llm_count and provider else (f'; {llm_count} LLM thesis' if llm_count else '')})"
        if rows
        else "No early 2-week swing setups found"
    )
    if llm_configured and llm_count == 0:
        note += f" — AI thesis fallback ({llm_err or 'no usable thesis JSON'})"
    return {
        "tab": TAB_DASHBOARD,
        "filter": filter_tooltip_dict(TAB_DASHBOARD),
        "stocks": rows,
        "meta": {
            "universe_count": len(symbols),
            "scanned": len(metrics),
            "early_setups": len(scored),
            "matched": len(rows),
            "llm_enriched": llm_count,
            "llm_configured": llm_configured,
            "llm_provider": provider,
            "llm_error": llm_err if llm_count == 0 else None,
            "horizon_days": HORIZON_DAYS,
            "target_move_pct": MIN_EXPECTED_MOVE_PCT,
            "conviction_met_count": conviction_count,
            "note": note,
            "top_score": rows[0]["extra"].get("expected_move_pct") if rows else None,
        },
    }

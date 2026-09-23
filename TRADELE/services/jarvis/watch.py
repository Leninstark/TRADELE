"""JARVIS user watchlist — up to 10 symbols, parallel 1m analyse + trade plan."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import date, timedelta
from typing import Any, Optional

from TRADELE.services.jarvis import bus
from TRADELE.services.jarvis.brain_charts import build_symbol_price_action
from TRADELE.services.jarvis.config import get_config

logger = logging.getLogger(__name__)

MAX_WATCH = 10

_watch: dict[str, Any] = {
    "symbols": [],  # ordered list[str]
    "plans": {},  # symbol -> plan
    "updated_at": None,
}


def watch_state() -> dict[str, Any]:
    return deepcopy(_watch)


def list_watch() -> list[str]:
    return list(_watch["symbols"])


def add_symbol(symbol: str) -> dict[str, Any]:
    sym = (symbol or "").strip().upper()
    if not sym or not sym.replace("&", "").replace("-", "").isalnum():
        return {"ok": False, "error": "Invalid symbol", "watch": watch_state()}
    if sym in _watch["symbols"]:
        return {"ok": True, "already": True, "watch": watch_state()}
    if len(_watch["symbols"]) >= MAX_WATCH:
        return {"ok": False, "error": f"Max {MAX_WATCH} symbols", "watch": watch_state()}
    _watch["symbols"].append(sym)
    _watch["updated_at"] = time.time()
    bus.publish("jarvis.tape", {"kind": "watch", "message": f"Added {sym} to JARVIS watch"})
    return {"ok": True, "watch": watch_state()}


def remove_symbol(symbol: str) -> dict[str, Any]:
    sym = (symbol or "").strip().upper()
    _watch["symbols"] = [s for s in _watch["symbols"] if s != sym]
    _watch["plans"].pop(sym, None)
    _watch["updated_at"] = time.time()
    return {"ok": True, "watch": watch_state()}


def clear_watch() -> dict[str, Any]:
    _watch["symbols"] = []
    _watch["plans"] = {}
    _watch["updated_at"] = time.time()
    return {"ok": True, "watch": watch_state()}


def _last_weekday() -> date:
    d = date.today() - timedelta(days=1)
    for _ in range(7):
        if d.weekday() < 5:
            return d
        d -= timedelta(days=1)
    return d


def _load_1m(symbol: str, *, live: bool = False) -> tuple[list[dict[str, Any]], str, str]:
    """Return (bars, asof_iso, source).

    live=True skips the Excel replay pack and reads today's Zerodha 1m session.
    """
    from TRADELE.services.jarvis.pack import candles_for, pack_exists, timeline_minutes

    if not live and pack_exists():
        bars = candles_for(symbol)
        if len(bars) >= 30:
            stamps = timeline_minutes()
            asof = stamps[min(45, len(stamps) - 1)] if stamps else bars[-1]["datetime"]
            upto = [b for b in bars if b["datetime"] <= asof]
            return (upto if len(upto) >= 30 else bars), asof, "excel_pack"

    # Zerodha
    from TRADELE.services.zerodha_client import KiteRateLimitError

    try:
        from TRADELE.config import settings
        from TRADELE.db.session import SessionLocal
        from TRADELE.services.zerodha_client import ZerodhaClient
        from TRADELE.services.zerodha_token_store import get_active_access_token

        session = date.today() if live else _last_weekday()
        if session.weekday() >= 5:
            session = _last_weekday()
        db = SessionLocal()
        try:
            token = get_active_access_token(db, "leninstark") or settings.kite_access_token
            if token:
                client = ZerodhaClient(access_token=token)
                raw = client.get_historical_minute(
                    symbol, "NSE", session, db=db, use_cache=not live
                )
                bars = [
                    {
                        "symbol": symbol,
                        "datetime": b.get("date"),
                        "open": float(b["open"]),
                        "high": float(b["high"]),
                        "low": float(b["low"]),
                        "close": float(b["close"]),
                        "volume": int(b.get("volume") or 0),
                    }
                    for b in (raw or [])
                ]
                min_need = 12 if live else 30
                if len(bars) >= min_need:
                    asof = str(bars[min(45, len(bars) - 1)]["datetime"])
                    return bars, asof, "zerodha"
        finally:
            db.close()
    except KiteRateLimitError:
        raise
    except Exception as e:
        logger.debug("watch zerodha %s: %s", symbol, e)

    # yfinance fallback
    try:
        import yfinance as yf

        df = yf.Ticker(f"{symbol}.NS").history(period="5d", interval="1m", auto_adjust=False)
        if df is not None and not df.empty:
            if df.index.tz is None:
                idx = df.index.tz_localize("Asia/Kolkata")
            else:
                idx = df.index.tz_convert("Asia/Kolkata")
            df = df.copy()
            df.index = idx
            day = df[df.index.date == df.index.date[-1]]
            bars = []
            for ts, row in day.iterrows():
                bars.append(
                    {
                        "symbol": symbol,
                        "datetime": ts.isoformat(),
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": int(row.get("Volume") or 0),
                    }
                )
            if len(bars) >= 30:
                asof = bars[min(45, len(bars) - 1)]["datetime"]
                return bars, asof, "yfinance"
    except Exception as e:
        logger.debug("watch yfinance %s: %s", symbol, e)

    return [], "", "none"


def _detect_patterns(closes: list[float], highs: list[float], lows: list[float], opens: list[float]) -> list[str]:
    pats: list[str] = []
    if len(closes) < 5:
        return pats
    o, h, l, c = opens[-1], highs[-1], lows[-1], closes[-1]
    body = abs(c - o)
    rng = max(h - l, 1e-9)
    upper = h - max(c, o)
    lower = min(c, o) - l
    if body / rng < 0.25 and upper > body * 1.5 and lower > body * 1.5:
        pats.append("doji")
    if c > o and lower > body * 2 and upper < body * 0.5:
        pats.append("hammer")
    if c < o and upper > body * 2 and lower < body * 0.5:
        pats.append("shooting_star")
    if len(closes) >= 3:
        if closes[-3] > opens[-3] and closes[-2] < opens[-2] and closes[-1] < opens[-1] and closes[-1] < closes[-3]:
            pats.append("bearish_engulf_seq")
        if closes[-3] < opens[-3] and closes[-2] > opens[-2] and closes[-1] > opens[-1] and closes[-1] > closes[-3]:
            pats.append("bullish_engulf_seq")
    # simple HH/HL or LH/LL
    if len(closes) >= 10:
        if closes[-1] > max(closes[-10:-1]) * 0.999:
            pats.append("breakout_high")
        if closes[-1] < min(closes[-10:-1]) * 1.001:
            pats.append("breakdown_low")
    return pats


def analyse_symbol(symbol: str, *, live: bool = False) -> dict[str, Any]:
    cfg = get_config()
    bars, asof, source = _load_1m(symbol, live=live)
    min_bars = 12 if live else 25
    if len(bars) < min_bars:
        return {
            "symbol": symbol,
            "ok": False,
            "error": "Not enough 1m bars",
            "source": source,
            "action": "skip",
        }

    closes = [float(b["close"]) for b in bars]
    opens = [float(b["open"]) for b in bars]
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    vols = [float(b.get("volume") or 0) for b in bars]

    ret15 = (closes[-1] / closes[-16] - 1) * 100
    ret5 = (closes[-1] / closes[-6] - 1) * 100
    vol_ratio = (sum(vols[-5:]) / 5) / max(sum(vols[-20:-5]) / 15, 1)
    orb_hi = max(highs[:15])
    orb_lo = min(lows[:15])
    orb_break = closes[-1] > orb_hi * 1.001
    orb_fail = closes[-1] < orb_lo * 0.999
    patterns = _detect_patterns(closes, highs, lows, opens)

    votes: list[str] = []
    if orb_break and ret15 > 0.15:
        votes.append("J-A")
    if ret15 > 0.2 and vol_ratio > 1.05:
        votes.append("J-B")
    if "hammer" in patterns or ("bullish_engulf_seq" in patterns and ret5 > 0):
        votes.append("J-REV-LONG")
    if "shooting_star" in patterns or ("bearish_engulf_seq" in patterns and ret5 < 0):
        votes.append("J-REV-SHORT")
    if abs(ret15) < 0.12 and vol_ratio < 0.95:
        votes.append("J-C")

    # Side decision
    long_score = max(0, ret15) * 4 + max(0, ret5) * 2 + (10 if orb_break else 0) + (8 if "J-REV-LONG" in votes else 0)
    short_score = max(0, -ret15) * 4 + max(0, -ret5) * 2 + (10 if orb_fail else 0) + (8 if "J-REV-SHORT" in votes else 0)
    if "breakout_high" in patterns:
        long_score += 6
    if "breakdown_low" in patterns:
        short_score += 6

    if long_score >= short_score and long_score > 5:
        side = "LONG"
        raw_edge = long_score
    elif short_score > long_score and short_score > 5:
        side = "SHORT"
        raw_edge = short_score
    else:
        side = "FLAT"
        raw_edge = max(long_score, short_score)

    score = min(99, 50 + raw_edge)
    # Probability proxy 0.35–0.92
    probability = round(min(0.92, max(0.35, 0.45 + (score - 50) / 120 + min(vol_ratio, 2) * 0.04)), 3)

    entry = closes[-1]
    atr = sum(highs[i] - lows[i] for i in range(-14, 0)) / 14
    sl_dist = max(atr * float(cfg.get("sl_atr_mult") or 1.2), entry * 0.004)
    tp_r = float(cfg.get("target_r_multiple") or 2.0)
    if side == "LONG":
        sl = entry - sl_dist
        tp = entry + sl_dist * tp_r
        trail_activate = entry + sl_dist  # 1R
        trail_step = atr * 0.8
    elif side == "SHORT":
        sl = entry + sl_dist
        tp = entry - sl_dist * tp_r
        trail_activate = entry - sl_dist
        trail_step = atr * 0.8
    else:
        sl = tp = trail_activate = trail_step = None

    # Position size from probability × risk budget
    capital = float(cfg.get("capital_rupees") or 100_000)
    risk_pct = float(cfg.get("risk_per_trade_pct") or 0.75) / 100
    risk_rupees = capital * risk_pct * probability
    qty = 0
    if side != "FLAT" and sl_dist > 0:
        qty = max(1, int(risk_rupees / sl_dist))
        max_val = float(cfg.get("max_position_value") or 100_000)
        qty = min(qty, max(1, int(max_val / entry)))

    action = "enter" if side != "FLAT" and probability >= 0.55 and score >= float(cfg.get("min_score_to_trade") or 70) else "wait"

    pick = {
        "entry": round(entry, 2) if entry else None,
        "sl": round(sl, 2) if sl else None,
        "tp": round(tp, 2) if tp else None,
        "side": side,
        "score": round(score, 1),
        "strategy": votes[0] if votes else "J-B",
        "reasons": [
            f"15m {ret15:+.2f}%",
            f"5m {ret5:+.2f}%",
            f"vol×{vol_ratio:.2f}",
            f"p={probability:.0%}",
            *(patterns[:3]),
            *(votes[:3]),
        ],
    }
    chart = build_symbol_price_action(
        symbol=symbol,
        asof=asof or str(bars[-1]["datetime"]),
        pick=pick if side != "FLAT" else None,
        bars=bars,
    )

    plan = {
        "symbol": symbol,
        "ok": True,
        "source": source,
        "asof": asof,
        "action": action,
        "side": side,
        "score": round(score, 1),
        "probability": probability,
        "entry": pick["entry"],
        "stop_loss": pick["sl"],
        "target": pick["tp"],
        "trailing": {
            "enabled": True,
            "activate_at": round(trail_activate, 2) if trail_activate else None,
            "step": round(trail_step, 2) if trail_step else None,
            "note": "Trail after ~1R profit; JARVIS can tighten",
        },
        "quantity": qty,
        "position_value": round(qty * entry, 2) if qty else 0,
        "risk_rupees": round(risk_rupees, 2),
        "patterns": patterns,
        "votes": votes,
        "trend": "up" if ret15 > 0.15 else ("down" if ret15 < -0.15 else "range"),
        "reasons": pick["reasons"],
        "chart": chart,
        "jarvis_decides": {
            "stock": symbol if action == "enter" else None,
            "entry_level": pick["entry"],
            "position_size": qty,
            "stop_loss": pick["sl"],
            "trailing_stop": pick["sl"],  # initial; trails after activate_at
            "target_aim": pick["tp"],
            "when_exit": "target | trail | time_stop | structure break",
        },
    }
    return plan


def _analyse_symbol_list(symbols: list[str], *, lane: str) -> dict[str, Any]:
    plans: dict[str, Any] = {}
    if not symbols:
        return plans
    with ThreadPoolExecutor(max_workers=min(10, len(symbols))) as pool:
        futs = {pool.submit(analyse_symbol, s): s for s in symbols}
        for fut in as_completed(futs):
            sym = futs[fut]
            try:
                plan = fut.result()
            except Exception as e:
                plan = {"symbol": sym, "ok": False, "error": str(e), "action": "skip"}
            plan["lane"] = lane
            plans[sym] = plan
    return plans


def _claude_rank(plans: dict[str, Any], *, context: str) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
    enterable = [p for p in plans.values() if p.get("ok") and p.get("action") == "enter"]
    enterable.sort(key=lambda p: (float(p.get("probability") or 0), float(p.get("score") or 0)), reverse=True)
    master = enterable[0] if enterable else None
    claude = None
    try:
        import json

        from TRADELE.services.llm_agent import call_llm_auto, last_llm_provider

        brief = [
            {
                "symbol": p.get("symbol"),
                "lane": p.get("lane"),
                "side": p.get("side"),
                "score": p.get("score"),
                "probability": p.get("probability"),
                "action": p.get("action"),
                "patterns": p.get("patterns"),
                "entry": p.get("entry"),
                "sl": p.get("stop_loss"),
                "tp": p.get("target"),
            }
            for p in plans.values()
            if p.get("ok")
        ]
        prompt = f"""You are JARVIS. {context}
Plans: {json.dumps(brief)[:4000]}
Pick at most 1–2 entries. Prefer strongest probability + clean pattern.
Return ONLY JSON:
{{"summary":"...","primary":"SYMBOL or null","side":"LONG|SHORT|null","approve":true,"why":"...","size_hint":"full|half|skip","also":[]}}
"""
        raw = call_llm_auto(prompt)
        provider = last_llm_provider() or "claude_cli"
        summary = (raw or "")[:600]
        primary = master["symbol"] if master else None
        if raw:
            try:
                text = raw.strip()
                if "```" in text:
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]
                data = json.loads(text.strip())
                summary = data.get("summary") or summary
                primary = data.get("primary") or primary
                claude = {
                    "provider": provider,
                    "summary": summary,
                    "primary": primary,
                    "side": data.get("side"),
                    "approve": bool(data.get("approve", True)),
                    "why": data.get("why"),
                    "size_hint": data.get("size_hint"),
                    "also": data.get("also") or [],
                }
            except Exception:
                claude = {"provider": provider, "summary": summary, "primary": primary, "approve": True}
        else:
            claude = {
                "provider": provider,
                "summary": "Claude unavailable — rules rank used",
                "primary": primary,
                "approve": True,
            }
    except Exception as e:
        claude = {
            "provider": "error",
            "summary": str(e),
            "approve": True,
            "primary": master["symbol"] if master else None,
        }

    if claude and claude.get("primary"):
        master = plans.get(str(claude["primary"]).upper()) or master
    return master, claude


def scan_pack_top5(*, top_n: int = 5) -> dict[str, Any]:
    """Scan full Excel pack in parallel; return top N enter candidates."""
    from TRADELE.services.jarvis.pack import list_symbols, pack_exists

    if not pack_exists():
        return {"ok": False, "error": "Excel pack missing", "pack_top": [], "plans": {}}

    symbols = list_symbols()
    plans = _analyse_symbol_list(symbols, lane="pack")
    ranked = [
        p
        for p in plans.values()
        if p.get("ok") and p.get("action") == "enter"
    ]
    ranked.sort(key=lambda p: (float(p.get("probability") or 0), float(p.get("score") or 0)), reverse=True)
    pack_top = ranked[:top_n]
    # Also keep near-misses for UI (wait but high score)
    waiters = [
        p
        for p in plans.values()
        if p.get("ok") and p.get("action") != "enter" and float(p.get("score") or 0) >= 65
    ]
    waiters.sort(key=lambda p: float(p.get("score") or 0), reverse=True)

    bus.publish(
        "jarvis.tape",
        {"kind": "pack", "message": f"Pack scan · top {len(pack_top)} entry candidates from {len(symbols)}"},
    )
    return {
        "ok": True,
        "universe": len(symbols),
        "pack_top": pack_top,
        "pack_watchlist": [p.get("symbol") for p in pack_top],
        "near_miss": waiters[:5],
        "plans": {p["symbol"]: p for p in pack_top},
        "at": time.time(),
    }


def analyse_watch_parallel() -> dict[str, Any]:
    symbols = list(_watch["symbols"])
    if not symbols:
        return {"ok": False, "error": "Add at least one symbol (max 10)", "watch": watch_state()}

    plans = _analyse_symbol_list(symbols, lane="user")
    _watch["plans"] = plans
    _watch["updated_at"] = time.time()
    master, claude = _claude_rank(
        plans,
        context="User-decided watchlist (max 10). Look for entries only on these symbols.",
    )
    bus.publish(
        "jarvis.tape",
        {
            "kind": "watch",
            "message": f"User watch · {len(symbols)} symbols · primary {(master or {}).get('symbol')}",
        },
    )
    return {
        "ok": True,
        "lane": "user",
        "symbols": symbols,
        "plans": plans,
        "ordered": [plans[s] for s in symbols if s in plans],
        "user_plans": [plans[s] for s in symbols if s in plans],
        "pack_top": [],
        "master": master,
        "claude": claude,
        "watch": watch_state(),
        "at": time.time(),
    }


def analyse_both_lanes(*, top_n: int = 5) -> dict[str, Any]:
    """
    Dual mechanism:
      1) JARVIS scans Excel pack → top 5 entry candidates
      2) User watch symbols analysed for entry
    Claude ranks across both lanes.
    """
    pack = scan_pack_top5(top_n=top_n)
    user_syms = list(_watch["symbols"])
    user_plans = _analyse_symbol_list(user_syms, lane="user") if user_syms else {}
    _watch["plans"] = user_plans
    _watch["updated_at"] = time.time()

    merged: dict[str, Any] = {}
    for p in pack.get("pack_top") or []:
        sym = p.get("symbol")
        if sym:
            merged[sym] = p
    for sym, p in user_plans.items():
        # user lane wins tag if overlap — keep both scores visible via lane
        if sym in merged:
            # prefer higher probability; tag as both
            cur = merged[sym]
            if float(p.get("probability") or 0) >= float(cur.get("probability") or 0):
                p = {**p, "lane": "both", "also_pack": True}
                merged[sym] = p
            else:
                merged[sym] = {**cur, "lane": "both", "also_user": True}
        else:
            merged[sym] = p

    if not merged and not pack.get("ok"):
        return {
            "ok": False,
            "error": pack.get("error") or "Nothing to analyse — need Excel pack and/or user symbols",
            "watch": watch_state(),
        }

    master, claude = _claude_rank(
        merged,
        context=(
            "Two lanes: (1) pack_top = JARVIS-picked candidates from Excel universe; "
            "(2) user = symbols the trader added to watch. "
            "You may pick from either lane."
        ),
    )

    bus.publish(
        "jarvis.candidates",
        {
            "longs": [p for p in (pack.get("pack_top") or []) if p.get("side") == "LONG"][:5],
            "shorts": [p for p in (pack.get("pack_top") or []) if p.get("side") == "SHORT"][:5],
            "regime": "DUAL_LANE",
        },
    )
    bus.publish(
        "jarvis.tape",
        {
            "kind": "dual",
            "message": (
                f"Dual scan · pack top {len(pack.get('pack_top') or [])} · "
                f"user {len(user_syms)} · primary {(master or {}).get('symbol')}"
            ),
        },
    )

    return {
        "ok": True,
        "lane": "both",
        "pack_top": pack.get("pack_top") or [],
        "pack_universe": pack.get("universe"),
        "near_miss": pack.get("near_miss") or [],
        "user_plans": [user_plans[s] for s in user_syms if s in user_plans],
        "ordered": [user_plans[s] for s in user_syms if s in user_plans],
        "plans": merged,
        "master": master,
        "claude": claude,
        "watch": watch_state(),
        "at": time.time(),
    }

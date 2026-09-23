"""
JARVIS — Equity Intraday LangGraph agent.

Lightweight parallel graph:
  bootstrap ──► strat_orb ──────┐
             ├► strat_momentum ─┼► merge_rank ► claude_advise ► risk_gate ► END
             ├► strat_meanrev ──┤
             └► groww_live ─────┘

Claude Code CLI powers advise/veto via call_llm_auto (LLM_PROVIDER=claude_cli).
"""
from __future__ import annotations

import json
import logging
import operator
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Annotated, Any, Optional, TypedDict

from TRADELE.db.session import SessionLocal
from TRADELE.services.jarvis import bus
from TRADELE.services.jarvis.config import LARGE_CAP, get_config
from TRADELE.services.jarvis.groww_live import fetch_groww_live
from TRADELE.services.llm_agent import call_llm_auto, last_llm_provider
from TRADELE.services.universe import get_tradeable_equity_symbols

logger = logging.getLogger(__name__)

try:
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    StateGraph = None  # type: ignore
    START = END = None  # type: ignore


class JarvisState(TypedDict, total=False):
    username: str
    config: dict[str, Any]
    symbols: list[str]
    regime: str
    strategy_hits: Annotated[list[dict[str, Any]], operator.add]
    groww: dict[str, Any]
    candidates: dict[str, Any]
    decisions: list[dict[str, Any]]
    ai_summary: str
    claude_provider: str
    errors: Annotated[list[str], operator.add]
    meta: dict[str, Any]


def _passes_universe(sym: str, cfg: dict[str, Any]) -> bool:
    s = sym.upper()
    if cfg.get("large_cap_only") and s not in LARGE_CAP:
        return False
    if (cfg.get("avoid_large_cap") or cfg.get("prefer_mid_small")) and not cfg.get("large_cap_only"):
        if s in LARGE_CAP:
            return False
    return True


def _fake_quote_score(sym: str, seed: int) -> dict[str, Any]:
    """Deterministic placeholder score until live candle scorer is wired per-symbol."""
    h = sum(ord(c) for c in sym) + seed
    score = 55 + (h % 40)
    side = "LONG" if h % 2 == 0 else "SHORT"
    atr_pct = 1.0 + (h % 50) / 20.0
    price = 100 + (h % 900)
    sl_pct = float(get_config().get("sl_pct") or 0.8)
    tp_r = float(get_config().get("target_r_multiple") or 2.0)
    if side == "LONG":
        entry = float(price)
        sl = entry * (1 - sl_pct / 100)
        tp = entry + (entry - sl) * tp_r
    else:
        entry = float(price)
        sl = entry * (1 + sl_pct / 100)
        tp = entry - (sl - entry) * tp_r
    return {
        "symbol": sym,
        "side": side,
        "score": score,
        "atr_pct": round(atr_pct, 2),
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "tp": round(tp, 2),
        "rr": tp_r,
    }


def node_bootstrap(state: JarvisState) -> dict[str, Any]:
    cfg = get_config()
    username = (state.get("username") or "leninstark").strip().lower()
    bus.publish("jarvis.tape", {"kind": "node", "message": "bootstrap · loading universe + config"})
    mid_small = bool(cfg.get("prefer_mid_small", True)) or bool(cfg.get("avoid_large_cap", True))
    try:
        if mid_small and not cfg.get("large_cap_only"):
            from TRADELE.filters.universe import load_phase1_universe

            symbols = load_phase1_universe()
        else:
            symbols = get_tradeable_equity_symbols()
    except Exception as e:
        logger.warning("JARVIS universe fallback: %s", e)
        symbols = [
            "PERSISTENT",
            "COFORGE",
            "POLYCAB",
            "DIXON",
            "AUBANK",
            "FEDERALBNK",
            "VOLTAS",
            "TRENT",
            "PIIND",
            "MFSL",
        ]
    symbols = [s for s in symbols if _passes_universe(s, cfg)]
    if not (mid_small and not cfg.get("large_cap_only")):
        cap = int(cfg.get("max_candidates_scan") or 80)
        symbols = symbols[:cap]
    # Simple regime stub — index align later
    regime = "TREND"
    bus.publish("jarvis.config", cfg)
    bus.publish("jarvis.mode", {"mode": cfg.get("mode") or "SCAN_ONLY"})
    return {
        "username": username,
        "config": cfg,
        "symbols": symbols,
        "regime": regime,
        "strategy_hits": [],
        "errors": [],
        "meta": {"started_at": time.time(), "symbol_count": len(symbols)},
    }


def _run_orb(symbols: list[str], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    if not cfg.get("enable_j_a", True):
        return []
    hits = []
    for i, sym in enumerate(symbols[:40]):
        row = _fake_quote_score(sym, seed=11)
        if row["score"] >= 68 and row["side"] == "LONG":
            hits.append({**row, "strategy": "J-A", "label": "ORB / open drive"})
    return hits[:8]


def _run_momentum(symbols: list[str], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    if not cfg.get("enable_j_b", True):
        return []
    hits = []
    for sym in symbols[:40]:
        row = _fake_quote_score(sym, seed=23)
        if row["score"] >= 70:
            hits.append({**row, "strategy": "J-B", "label": "Momentum / VWAP"})
    return hits[:8]


def _run_meanrev(symbols: list[str], cfg: dict[str, Any], regime: str) -> list[dict[str, Any]]:
    if not cfg.get("enable_j_c", True):
        return []
    if regime == "TREND":
        # Mean-rev gated off in strong trend — router abide
        return []
    hits = []
    for sym in symbols[:40]:
        row = _fake_quote_score(sym, seed=37)
        if 60 <= row["score"] <= 78:
            hits.append({**row, "strategy": "J-C", "label": "Mean reversion", "side": "SHORT" if row["side"] == "LONG" else "LONG"})
    return hits[:6]


def node_strat_orb(state: JarvisState) -> dict[str, Any]:
    bus.publish("jarvis.tape", {"kind": "node", "message": "parallel · J-A ORB analysing"})
    hits = _run_orb(state.get("symbols") or [], state.get("config") or {})
    return {"strategy_hits": hits}


def node_strat_momentum(state: JarvisState) -> dict[str, Any]:
    bus.publish("jarvis.tape", {"kind": "node", "message": "parallel · J-B momentum analysing"})
    hits = _run_momentum(state.get("symbols") or [], state.get("config") or {})
    return {"strategy_hits": hits}


def node_strat_meanrev(state: JarvisState) -> dict[str, Any]:
    bus.publish("jarvis.tape", {"kind": "node", "message": "parallel · J-C mean-rev analysing"})
    hits = _run_meanrev(state.get("symbols") or [], state.get("config") or {}, state.get("regime") or "TREND")
    return {"strategy_hits": hits}


def node_groww_live(state: JarvisState) -> dict[str, Any]:
    bus.publish("jarvis.tape", {"kind": "node", "message": "parallel · Groww live sync"})
    db = SessionLocal()
    try:
        snap = fetch_groww_live(db, state.get("username") or "leninstark")
        return {"groww": snap, "strategy_hits": []}
    except Exception as e:
        return {"groww": {"connected": False, "error": str(e)}, "errors": [f"groww: {e}"], "strategy_hits": []}
    finally:
        db.close()


def node_merge_rank(state: JarvisState) -> dict[str, Any]:
    bus.publish("jarvis.tape", {"kind": "node", "message": "merge_rank · scoring board"})
    cfg = state.get("config") or get_config()
    hits = list(state.get("strategy_hits") or [])
    # Prefer higher score; boost RS strategy tag later
    by_sym: dict[str, dict[str, Any]] = {}
    for h in hits:
        sym = h.get("symbol")
        if not sym:
            continue
        prev = by_sym.get(sym)
        if not prev or float(h.get("score") or 0) > float(prev.get("score") or 0):
            by_sym[sym] = h
    ranked = sorted(by_sym.values(), key=lambda x: float(x.get("score") or 0), reverse=True)
    allow_short = bool(cfg.get("allow_short", True))
    min_score = float(cfg.get("min_score_to_trade") or 70)
    longs = [r for r in ranked if r.get("side") == "LONG" and float(r.get("score") or 0) >= min_score]
    shorts = [
        r
        for r in ranked
        if r.get("side") == "SHORT" and allow_short and float(r.get("score") or 0) >= min_score
    ]
    top_l = int(cfg.get("top_n_long") or 5)
    top_s = int(cfg.get("top_n_short") or 5)
    candidates = {"longs": longs[:top_l], "shorts": shorts[:top_s], "regime": state.get("regime")}
    bus.publish("jarvis.candidates", candidates)
    return {"candidates": candidates}


def node_claude_advise(state: JarvisState) -> dict[str, Any]:
    cfg = state.get("config") or {}
    role = (cfg.get("claude_role") or "veto_and_explain").strip().lower()
    cands = state.get("candidates") or {}
    bus.publish("jarvis.tape", {"kind": "node", "message": f"claude_advise · role={role}"})
    if role == "off":
        return {"ai_summary": "Claude disabled", "decisions": [], "claude_provider": "off"}

    prompt = f"""You are JARVIS, TRADELE equity intraday risk advisor.
Regime: {state.get("regime")}
Top longs: {json.dumps(cands.get("longs") or [], default=str)[:1800]}
Top shorts: {json.dumps(cands.get("shorts") or [], default=str)[:1800]}
Groww connected: {(state.get("groww") or {}).get("connected")}

Return ONLY JSON:
{{
  "summary": "one short paragraph",
  "vetoes": ["SYMBOL", ...],
  "size_down": ["SYMBOL", ...],
  "approve": ["SYMBOL", ...]
}}
Veto only clearly weak / conflicting setups. Prefer approve when scores are high.
"""
    raw = call_llm_auto(prompt)
    provider = last_llm_provider() or "none"
    summary = "Claude unavailable — rules-only path."
    vetoes: set[str] = set()
    size_down: set[str] = set()
    if raw:
        try:
            text = raw.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text.strip())
            summary = data.get("summary") or summary
            vetoes = {str(x).upper() for x in (data.get("vetoes") or [])}
            size_down = {str(x).upper() for x in (data.get("size_down") or [])}
        except Exception as e:
            summary = (raw or "")[:400]
            logger.info("JARVIS Claude parse soft-fail: %s", e)

    decisions = []
    for side_key in ("longs", "shorts"):
        for row in cands.get(side_key) or []:
            sym = str(row.get("symbol") or "").upper()
            verdict = "approve"
            if role == "veto_and_explain" and sym in vetoes:
                verdict = "veto"
            elif sym in size_down:
                verdict = "size_down"
            decisions.append({**row, "verdict": verdict})

    if role == "veto_and_explain":
        # Apply vetoes to candidate board
        cands = {
            "longs": [r for r in (cands.get("longs") or []) if str(r.get("symbol")).upper() not in vetoes],
            "shorts": [r for r in (cands.get("shorts") or []) if str(r.get("symbol")).upper() not in vetoes],
            "regime": cands.get("regime"),
        }
        bus.publish("jarvis.candidates", cands)

    bus.publish(
        "jarvis.tape",
        {"kind": "claude", "message": summary[:180], "provider": provider, "vetoes": list(vetoes)},
    )
    return {
        "ai_summary": summary,
        "decisions": decisions,
        "claude_provider": provider,
        "candidates": cands,
    }


def node_risk_gate(state: JarvisState) -> dict[str, Any]:
    cfg = state.get("config") or get_config()
    mode = (cfg.get("mode") or "SCAN_ONLY").upper()
    bus.publish("jarvis.tape", {"kind": "node", "message": f"risk_gate · mode={mode}"})
    decisions = list(state.get("decisions") or [])
    # Abide: never emit LIVE orders here yet — intents only
    intents = []
    for d in decisions:
        if d.get("verdict") == "veto":
            continue
        rr = float(d.get("rr") or 0)
        if rr < float(cfg.get("min_r_multiple") or 1.5):
            continue
        intents.append(
            {
                "symbol": d.get("symbol"),
                "side": d.get("side"),
                "strategy": d.get("strategy"),
                "score": d.get("score"),
                "entry": d.get("entry"),
                "sl": d.get("sl"),
                "tp": d.get("tp"),
                "verdict": d.get("verdict"),
                "mode": mode,
                "executable": mode in ("PAPER", "APPROVE", "LIVE"),
            }
        )
    meta = dict(state.get("meta") or {})
    meta["finished_at"] = time.time()
    meta["intent_count"] = len(intents)
    meta["mode"] = mode
    result = {
        "agent": "jarvis",
        "regime": state.get("regime"),
        "ai_summary": state.get("ai_summary"),
        "claude_provider": state.get("claude_provider"),
        "candidates": state.get("candidates"),
        "intents": intents,
        "groww": state.get("groww"),
        "errors": state.get("errors") or [],
        "meta": meta,
        "config": {k: cfg.get(k) for k in ("mode", "avoid_large_cap", "allow_short", "sl_mode", "tp_mode", "min_score_to_trade")},
    }
    bus.publish("jarvis.run", result)
    bus.publish(
        "jarvis.tape",
        {"kind": "decision", "message": f"{len(intents)} intents · {mode}", "intents": len(intents)},
    )
    return {"meta": meta, "decisions": intents}


def build_jarvis_agent():
    if not LANGGRAPH_AVAILABLE:
        return None
    g = StateGraph(JarvisState)
    g.add_node("bootstrap", node_bootstrap)
    g.add_node("strat_orb", node_strat_orb)
    g.add_node("strat_momentum", node_strat_momentum)
    g.add_node("strat_meanrev", node_strat_meanrev)
    g.add_node("groww_live", node_groww_live)
    g.add_node("merge_rank", node_merge_rank)
    g.add_node("claude_advise", node_claude_advise)
    g.add_node("risk_gate", node_risk_gate)

    g.add_edge(START, "bootstrap")
    # Fan-out: parallel analysis nodes
    g.add_edge("bootstrap", "strat_orb")
    g.add_edge("bootstrap", "strat_momentum")
    g.add_edge("bootstrap", "strat_meanrev")
    g.add_edge("bootstrap", "groww_live")
    # Fan-in
    g.add_edge("strat_orb", "merge_rank")
    g.add_edge("strat_momentum", "merge_rank")
    g.add_edge("strat_meanrev", "merge_rank")
    g.add_edge("groww_live", "merge_rank")
    g.add_edge("merge_rank", "claude_advise")
    g.add_edge("claude_advise", "risk_gate")
    g.add_edge("risk_gate", END)
    return g.compile()


_agent = None


def get_jarvis_agent():
    global _agent
    if _agent is None:
        _agent = build_jarvis_agent()
    return _agent


def _run_parallel_fallback(username: str) -> dict[str, Any]:
    """If LangGraph missing, still run strategies in a thread pool."""
    state: dict[str, Any] = node_bootstrap({"username": username})
    cfg = state.get("config") or {}
    symbols = state.get("symbols") or []
    regime = state.get("regime") or "TREND"
    hits: list[dict[str, Any]] = []
    groww: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {
            pool.submit(_run_orb, symbols, cfg): "orb",
            pool.submit(_run_momentum, symbols, cfg): "mom",
            pool.submit(_run_meanrev, symbols, cfg, regime): "mr",
            pool.submit(_groww_job, username): "groww",
        }
        for fut in as_completed(futs):
            kind = futs[fut]
            try:
                res = fut.result()
                if kind == "groww":
                    groww = res
                else:
                    hits.extend(res)
            except Exception as e:
                state.setdefault("errors", []).append(f"{kind}: {e}")
    state["strategy_hits"] = hits
    state["groww"] = groww
    state.update(node_merge_rank(state))  # type: ignore
    state.update(node_claude_advise(state))  # type: ignore
    state.update(node_risk_gate(state))  # type: ignore
    return {
        "agent": "jarvis",
        "regime": state.get("regime"),
        "ai_summary": state.get("ai_summary"),
        "claude_provider": state.get("claude_provider"),
        "candidates": state.get("candidates"),
        "intents": state.get("decisions") or [],
        "groww": state.get("groww"),
        "errors": state.get("errors") or [],
        "meta": state.get("meta") or {},
        "parallel": "threadpool_fallback",
    }


def _groww_job(username: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        return fetch_groww_live(db, username)
    finally:
        db.close()


def run_jarvis_agent(*, username: str = "leninstark") -> dict[str, Any]:
    username = (username or "leninstark").strip().lower()
    agent = get_jarvis_agent()
    if agent is None:
        return _run_parallel_fallback(username)
    result = agent.invoke({"username": username, "strategy_hits": [], "errors": []})
    return {
        "agent": "jarvis",
        "regime": result.get("regime"),
        "ai_summary": result.get("ai_summary"),
        "claude_provider": result.get("claude_provider"),
        "candidates": result.get("candidates"),
        "intents": result.get("decisions") or [],
        "groww": result.get("groww"),
        "errors": result.get("errors") or [],
        "meta": result.get("meta") or {},
        "parallel": "langgraph",
        "config": (result.get("config") if isinstance(result.get("config"), dict) else None)
        or {k: get_config().get(k) for k in ("mode", "avoid_large_cap", "allow_short")},
    }

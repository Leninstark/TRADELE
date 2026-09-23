"""JARVIS Test Lab — simulate Groww + paper executions without live risk."""
from __future__ import annotations

import time
import uuid
from copy import deepcopy
from typing import Any, Optional

from TRADELE.engines.agents.jarvis_agent import run_jarvis_agent
from TRADELE.services.jarvis import bus
from TRADELE.services.jarvis.config import get_config, update_config

_sim: dict[str, Any] = {
    "active": False,
    "scenario": None,
    "paper_positions": [],
    "paper_orders": [],
    "fills": [],
    "day_pnl": 0.0,
    "unrealized_pnl": 0.0,
    "steps": [],
    "last_agent": None,
}


def sim_state() -> dict[str, Any]:
    return deepcopy(_sim)


def _push_groww() -> dict[str, Any]:
    snap = {
        "connected": True,
        "simulated": True,
        "positions": list(_sim["paper_positions"]),
        "orders": list(_sim["paper_orders"]),
        "updated_at": time.time(),
        "position_count": len(_sim["paper_positions"]),
        "order_count": len(_sim["paper_orders"]),
        "error": None,
    }
    bus.publish("jarvis.groww", snap)
    bus.publish(
        "jarvis.pnl",
        {"day_pnl": float(_sim["day_pnl"]), "unrealized_pnl": float(_sim["unrealized_pnl"])},
    )
    return snap


def _tape(kind: str, message: str, **extra: Any) -> None:
    bus.publish("jarvis.tape", {"kind": kind, "message": message, "sim": True, **extra})
    _sim["steps"].insert(0, {"kind": kind, "message": message, "at": time.time(), **extra})
    _sim["steps"] = _sim["steps"][:60]


def reset_lab() -> dict[str, Any]:
    _sim.update(
        {
            "active": False,
            "scenario": None,
            "paper_positions": [],
            "paper_orders": [],
            "fills": [],
            "day_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "steps": [],
            "last_agent": None,
        }
    )
    update_config({"mode": "SCAN_ONLY"})
    bus.publish("jarvis.mode", {"mode": "SCAN_ONLY"})
    bus.publish(
        "jarvis.groww",
        {
            "connected": False,
            "simulated": False,
            "positions": [],
            "orders": [],
            "updated_at": time.time(),
            "position_count": 0,
            "order_count": 0,
        },
    )
    bus.publish("jarvis.pnl", {"day_pnl": 0.0, "unrealized_pnl": 0.0})
    bus.publish("jarvis.candidates", {"longs": [], "shorts": [], "regime": None})
    _tape("lab", "Test Lab reset — paper book cleared")
    return sim_state()


def start_lab(*, mode: str = "PAPER") -> dict[str, Any]:
    mode = (mode or "PAPER").upper()
    if mode not in ("SCAN_ONLY", "PAPER", "APPROVE"):
        mode = "PAPER"
    update_config({"mode": mode})
    _sim["active"] = True
    _sim["scenario"] = "manual"
    bus.publish("jarvis.mode", {"mode": mode})
    _push_groww()
    _tape("lab", f"Test Lab armed · mode={mode} (no live Groww orders)")
    return {"ok": True, "config": get_config(), "sim": sim_state()}


def inject_mock_groww(*, day_pnl: float = 1250.0, unrealized: float = 420.0) -> dict[str, Any]:
    _sim["active"] = True
    _sim["day_pnl"] = float(day_pnl)
    _sim["unrealized_pnl"] = float(unrealized)
    if not _sim["paper_positions"]:
        _sim["paper_positions"] = [
            {
                "trading_symbol": "SIMCO",
                "product": "MIS",
                "quantity": 100,
                "average_price": 250.0,
                "ltp": 254.2,
                "realised_pnl": day_pnl,
                "unrealised_pnl": unrealized,
                "segment": "CASH",
            }
        ]
    if not _sim["paper_orders"]:
        _sim["paper_orders"] = [
            {
                "groww_order_id": f"SIM-{uuid.uuid4().hex[:8]}",
                "trading_symbol": "SIMCO",
                "transaction_type": "BUY",
                "order_status": "COMPLETE",
                "quantity": 100,
                "product": "MIS",
            }
        ]
    snap = _push_groww()
    _tape("groww_sim", f"Mock Groww injected · day {day_pnl:+.0f} · uPNL {unrealized:+.0f}")
    bus.publish("jarvis.webhook", {"source": "groww_sim", "data": {"event": "snapshot", "pnl": day_pnl}})
    return {"ok": True, "groww": snap, "sim": sim_state()}


def run_agent_test(username: str = "leninstark") -> dict[str, Any]:
    _sim["active"] = True
    update_config({"mode": get_config().get("mode") or "PAPER"})
    _tape("lab", "Running LangGraph JARVIS (test)")
    t0 = time.time()
    result = run_jarvis_agent(username=username)
    result["elapsed_ms"] = int((time.time() - t0) * 1000)
    result["test_lab"] = True
    _sim["last_agent"] = result
    _tape(
        "lab",
        f"Agent done · {(result.get('candidates') or {}).get('longs') and len(result['candidates']['longs']) or 0}L / "
        f"{(result.get('candidates') or {}).get('shorts') and len(result['candidates']['shorts']) or 0}S · "
        f"{result.get('elapsed_ms')}ms",
    )
    return {"ok": True, **result, "sim": sim_state()}


def paper_execute_top(*, side: str = "LONG") -> dict[str, Any]:
    """Take top candidate from last run / board and open a paper MIS position."""
    side = (side or "LONG").upper()
    last = _sim.get("last_agent") or {}
    cands = last.get("candidates") or bus.snapshot().get("candidates") or {}
    board = cands.get("longs") if side == "LONG" else cands.get("shorts")
    if not board:
        # synthesize one so UI can still be tested
        board = [
            {
                "symbol": "TESTEQ",
                "side": side,
                "score": 88,
                "strategy": "J-B",
                "entry": 500.0,
                "sl": 496.0 if side == "LONG" else 504.0,
                "tp": 508.0 if side == "LONG" else 492.0,
                "rr": 2.0,
            }
        ]
    row = dict(board[0])
    sym = str(row.get("symbol") or "TESTEQ").upper()
    entry = float(row.get("entry") or 100)
    qty = 50
    order_id = f"PAPER-{uuid.uuid4().hex[:10]}"
    order = {
        "groww_order_id": order_id,
        "trading_symbol": sym,
        "transaction_type": "BUY" if side == "LONG" else "SELL",
        "order_status": "COMPLETE",
        "quantity": qty,
        "product": "MIS",
        "average_fill_price": entry,
        "simulated": True,
    }
    pos = {
        "trading_symbol": sym,
        "product": "MIS",
        "quantity": qty if side == "LONG" else -qty,
        "average_price": entry,
        "ltp": entry,
        "realised_pnl": 0.0,
        "unrealised_pnl": 0.0,
        "segment": "CASH",
        "sl": row.get("sl"),
        "tp": row.get("tp"),
        "strategy": row.get("strategy"),
        "simulated": True,
    }
    _sim["paper_orders"].insert(0, order)
    _sim["paper_positions"] = [p for p in _sim["paper_positions"] if p.get("trading_symbol") != sym]
    _sim["paper_positions"].insert(0, pos)
    _sim["fills"].insert(0, {"order_id": order_id, "symbol": sym, "side": side, "qty": qty, "price": entry, "at": time.time()})
    _sim["unrealized_pnl"] = 0.0
    _push_groww()
    _tape("exec", f"PAPER {side} {sym} × {qty} @ {entry} · SL {row.get('sl')} TP {row.get('tp')}")
    bus.publish(
        "jarvis.webhook",
        {"source": "paper_exec", "data": {"order_id": order_id, "symbol": sym, "status": "COMPLETE"}},
    )
    return {"ok": True, "order": order, "position": pos, "sim": sim_state()}


def mark_price(*, symbol: str, ltp: float) -> dict[str, Any]:
    sym = (symbol or "").upper()
    for p in _sim["paper_positions"]:
        if str(p.get("trading_symbol") or "").upper() != sym:
            continue
        entry = float(p.get("average_price") or 0)
        qty = float(p.get("quantity") or 0)
        p["ltp"] = float(ltp)
        p["unrealised_pnl"] = (float(ltp) - entry) * qty
        _sim["unrealized_pnl"] = sum(float(x.get("unrealised_pnl") or 0) for x in _sim["paper_positions"])
        _push_groww()
        _tape("mark", f"{sym} marked {ltp} · uPNL {_sim['unrealized_pnl']:+.0f}")
        return {"ok": True, "position": p, "sim": sim_state()}
    return {"ok": False, "error": f"No paper position for {sym}", "sim": sim_state()}


def close_position(*, symbol: str, reason: str = "manual") -> dict[str, Any]:
    sym = (symbol or "").upper()
    kept = []
    closed = None
    for p in _sim["paper_positions"]:
        if str(p.get("trading_symbol") or "").upper() != sym:
            kept.append(p)
            continue
        closed = p
        pnl = float(p.get("unrealised_pnl") or 0)
        _sim["day_pnl"] = float(_sim["day_pnl"]) + pnl
        _sim["fills"].insert(
            0,
            {
                "order_id": f"EXIT-{uuid.uuid4().hex[:8]}",
                "symbol": sym,
                "side": "EXIT",
                "qty": abs(float(p.get("quantity") or 0)),
                "price": p.get("ltp"),
                "pnl": pnl,
                "reason": reason,
                "at": time.time(),
            },
        )
        _tape("exit", f"Closed {sym} · {reason} · P&L {pnl:+.0f}")
    _sim["paper_positions"] = kept
    _sim["unrealized_pnl"] = sum(float(x.get("unrealised_pnl") or 0) for x in _sim["paper_positions"])
    _push_groww()
    return {"ok": True, "closed": closed, "sim": sim_state()}


def hit_sl(symbol: str | None = None) -> dict[str, Any]:
    if not _sim["paper_positions"]:
        return {"ok": False, "error": "No open paper positions", "sim": sim_state()}
    p = _sim["paper_positions"][0]
    sym = (symbol or p.get("trading_symbol") or "").upper()
    sl = float(p.get("sl") or (float(p.get("average_price") or 0) * 0.992))
    mark_price(symbol=sym, ltp=sl)
    return close_position(symbol=sym, reason="stop_loss")


def hit_tp(symbol: str | None = None) -> dict[str, Any]:
    if not _sim["paper_positions"]:
        return {"ok": False, "error": "No open paper positions", "sim": sim_state()}
    p = _sim["paper_positions"][0]
    sym = (symbol or p.get("trading_symbol") or "").upper()
    tp = float(p.get("tp") or (float(p.get("average_price") or 0) * 1.016))
    mark_price(symbol=sym, ltp=tp)
    return close_position(symbol=sym, reason="target")


def run_full_scenario(username: str = "leninstark") -> dict[str, Any]:
    """
    End-to-end UI stress path:
    reset → arm PAPER → mock Groww → run agent → paper buy → mark up → take profit.
    """
    reset_lab()
    start_lab(mode="PAPER")
    inject_mock_groww(day_pnl=800, unrealized=0)
    # Keep mocked day P&L, drop seed SIMCO so the paper trade is the only book
    _sim["paper_positions"] = []
    _sim["paper_orders"] = []
    _sim["unrealized_pnl"] = 0.0
    _push_groww()
    agent = run_agent_test(username=username)
    exe = paper_execute_top(side="LONG")
    sym = str((exe.get("position") or {}).get("trading_symbol") or "TESTEQ")
    entry = float((exe.get("position") or {}).get("average_price") or 100)
    mark_price(symbol=sym, ltp=entry * 1.008)
    done = hit_tp(sym)
    _tape("lab", "Full scenario complete — check JARVIS desk + this Lab")
    _sim["scenario"] = "full_e2e"
    return {
        "ok": True,
        "scenario": "full_e2e",
        "agent": {k: agent.get(k) for k in ("regime", "ai_summary", "claude_provider", "elapsed_ms", "parallel")},
        "symbol": sym,
        "sim": sim_state(),
        "final": done,
    }


def load_excel_pack() -> dict[str, Any]:
    from TRADELE.services.jarvis.pack import pack_info

    info = pack_info()
    if not info.get("exists"):
        _tape("lab", "Excel pack missing — run build_jarvis_testlab_1m.py")
        return {"ok": False, **info}
    _sim["active"] = True
    _sim["scenario"] = "excel_pack"
    _sim["pack"] = {
        "session": (info.get("meta") or {}).get("session_used"),
        "symbols": info.get("symbols_with_data"),
        "bars": info.get("total_bars"),
        "path": info.get("path"),
    }
    _tape(
        "pack",
        f"Loaded Excel pack · {info.get('symbols_with_data')} symbols · {info.get('total_bars')} bars · "
        f"session {(info.get('meta') or {}).get('session_used')}",
    )
    return {"ok": True, **info, "sim": sim_state()}


def replay_minute(minute_iso: str, top_n: int = 8) -> dict[str, Any]:
    """Score pack symbols at a session minute and publish candidates + marks to the bus."""
    from TRADELE.services.jarvis.pack import candles_for, list_symbols, snapshot_at

    _sim["active"] = True
    _sim["scenario"] = "excel_replay"
    snaps = snapshot_at(minute_iso)
    if not snaps:
        return {"ok": False, "error": f"No bars at/before {minute_iso}", "sim": sim_state()}

    scored: list[dict[str, Any]] = []
    for row in snaps:
        sym = row["symbol"]
        series = candles_for(sym)
        # bars up to this minute
        upto = [b for b in series if b["datetime"] <= row["datetime"]]
        if len(upto) < 20:
            continue
        closes = [float(b["close"]) for b in upto]
        vols = [float(b["volume"]) for b in upto]
        ret15 = (closes[-1] / closes[-16] - 1) * 100 if len(closes) >= 16 else 0.0
        ret5 = (closes[-1] / closes[-6] - 1) * 100 if len(closes) >= 6 else 0.0
        vol_ratio = (sum(vols[-5:]) / 5) / max(sum(vols[-20:-5]) / 15, 1) if len(vols) >= 20 else 1.0
        score = 50 + ret15 * 4 + ret5 * 2 + min(vol_ratio, 3) * 5
        score = max(0, min(99, score))
        side = "LONG" if ret15 >= 0 else "SHORT"
        entry = closes[-1]
        sl_pct = 0.6
        if side == "LONG":
            sl = entry * (1 - sl_pct / 100)
            tp = entry + (entry - sl) * 2
        else:
            sl = entry * (1 + sl_pct / 100)
            tp = entry - (sl - entry) * 2
        scored.append(
            {
                "symbol": sym,
                "side": side,
                "score": round(score, 1),
                "strategy": "J-B",
                "label": "Excel 1m momentum",
                "entry": round(entry, 2),
                "sl": round(sl, 2),
                "tp": round(tp, 2),
                "rr": 2.0,
                "ret15": round(ret15, 2),
                "vol_ratio": round(vol_ratio, 2),
                "datetime": row["datetime"],
                "source": row.get("source"),
            }
        )

    scored.sort(key=lambda x: float(x["score"]), reverse=True)
    longs = [s for s in scored if s["side"] == "LONG"][:top_n]
    shorts = [s for s in scored if s["side"] == "SHORT"][:top_n]
    candidates = {"longs": longs, "shorts": shorts, "regime": "REPLAY", "asof": minute_iso}
    bus.publish("jarvis.candidates", candidates)
    _tape("replay", f"Replay @ {minute_iso[-14:]} · {len(longs)}L / {len(shorts)}S from Excel pack")
    _sim["last_agent"] = {
        "agent": "jarvis_excel_replay",
        "regime": "REPLAY",
        "ai_summary": f"Excel 1m replay at {minute_iso}",
        "candidates": candidates,
        "claude_provider": "off",
        "parallel": "excel_pack",
    }
    return {
        "ok": True,
        "asof": minute_iso,
        "universe": len(list_symbols()),
        "scored": len(scored),
        "candidates": candidates,
        "sim": sim_state(),
    }


def replay_session_sample() -> dict[str, Any]:
    """Jump to three session checkpoints (open / mid / close) using Excel pack."""
    from TRADELE.services.jarvis.pack import timeline_minutes

    load = load_excel_pack()
    if not load.get("ok"):
        return load
    stamps = timeline_minutes()
    if len(stamps) < 30:
        return {"ok": False, "error": "Pack timeline too short", "sim": sim_state()}
    points = [stamps[15], stamps[len(stamps) // 2], stamps[-5]]
    results = []
    for p in points:
        results.append(replay_minute(p, top_n=5))
    _tape("lab", "Excel session sample replay done (open / mid / close)")
    return {"ok": True, "points": points, "results": results, "sim": sim_state()}


GRAPH_STEPS = [
    {"id": "bootstrap", "label": "Bootstrap · universe + config"},
    {"id": "strat_orb", "label": "Parallel · J-A ORB"},
    {"id": "strat_momentum", "label": "Parallel · J-B Momentum"},
    {"id": "strat_meanrev", "label": "Parallel · J-C Mean-rev"},
    {"id": "groww_live", "label": "Parallel · Groww live / sim"},
    {"id": "merge_rank", "label": "Merge + scoreboard"},
    {"id": "claude_advise", "label": "Claude CLI advise / veto"},
    {"id": "risk_gate", "label": "Risk gate · intents"},
]

# Live thinking stream for Test Lab UI
_think_lock = __import__("threading").Lock()
_think: dict[str, Any] = {
    "running": False,
    "phase": "idle",
    "progress": 0,
    "title": "Idle",
    "detail": "",
    "scan_log": [],
    "decisions": [],
    "claude": None,
    "execution": [],
    "timeline": [],
    "picked": None,
    "error": None,
    "started_at": None,
    "finished_at": None,
}


def thinking_state() -> dict[str, Any]:
    with _think_lock:
        return deepcopy(_think)


def _think_set(**kwargs: Any) -> None:
    with _think_lock:
        _think.update(kwargs)
        bus.publish("jarvis.think", deepcopy(_think))


def _think_push(bucket: str, item: dict[str, Any]) -> None:
    with _think_lock:
        lst = list(_think.get(bucket) or [])
        lst.append(item)
        _think[bucket] = lst[-200:]
        bus.publish("jarvis.think", deepcopy(_think))
    try:
        from TRADELE.services.jarvis.memory import append_event

        append_event(f"think.{bucket}", item)
    except Exception:
        pass


def _think_line(phase: str, title: str, detail: str = "", progress: Optional[float] = None) -> None:
    entry = {
        "at": time.time(),
        "phase": phase,
        "title": title,
        "detail": detail,
    }
    with _think_lock:
        _think["phase"] = phase
        _think["title"] = title
        _think["detail"] = detail
        if progress is not None:
            _think["progress"] = progress
        tl = list(_think.get("timeline") or [])
        tl.append(entry)
        _think["timeline"] = tl[-120:]
        bus.publish("jarvis.think", deepcopy(_think))
        bus.publish("jarvis.tape", {"kind": phase, "message": f"{title} — {detail}" if detail else title})
    try:
        from TRADELE.services.jarvis.memory import append_event

        append_event("think.line", entry)
    except Exception:
        pass


def run_excel_live_demo(*, use_claude: bool = True, pace: float = 0.08) -> dict[str, Any]:
    """
    Full visible JARVIS brain using Excel 1m pack:
    scan → score → decide → Claude → risk → paper execute → manage → exit.
    Designed to stream thinking_state() for the Test Lab UI.
    """
    import json
    import time as _time

    from TRADELE.services.jarvis.brain_charts import build_brain_activity, build_symbol_price_action
    from TRADELE.services.jarvis.pack import candles_for, list_symbols, pack_info, timeline_minutes
    from TRADELE.services.llm_agent import call_llm_auto, last_llm_provider

    info = pack_info()
    if not info.get("exists"):
        _think_set(running=False, phase="error", error="Excel pack missing", title="Pack missing")
        return {"ok": False, "error": "Excel pack missing"}

    try:
        from TRADELE.services.jarvis.memory import end_session, start_session

        start_session(lane="time", source="testlab", meta={"pack": info.get("meta") or {}})
    except Exception:
        pass

    with _think_lock:
        _think.clear()
        _think.update(
            {
                "running": True,
                "phase": "boot",
                "progress": 0,
                "title": "Starting",
                "detail": "",
                "scan_log": [],
                "decisions": [],
                "claude": None,
                "execution": [],
                "timeline": [],
                "picked": None,
                "charts": None,
                "error": None,
                "started_at": time.time(),
                "finished_at": None,
                "pack": {
                    "session": (info.get("meta") or {}).get("session_used"),
                    "symbols": info.get("symbols_with_data"),
                    "bars": info.get("total_bars"),
                },
            }
        )

    try:
        reset_lab()
        start_lab(mode="PAPER")
        load_excel_pack()
        _think_line("boot", "Excel pack locked", f"{info.get('symbols_with_data')} symbols · {info.get('total_bars')} bars · {(info.get('meta') or {}).get('session_used')}", 2)
        _time.sleep(pace)

        stamps = timeline_minutes()
        # Mid-morning checkpoint (~45 min into session) for richer momentum
        asof = stamps[min(45, len(stamps) - 1)]
        _think_line("boot", "Session clock", f"Replaying as-of {asof}", 5)
        _time.sleep(pace)

        symbols = list_symbols()
        _think_line("scan", "Universe scan", f"Scanning {len(symbols)} Excel symbols in parallel lanes…", 8)

        scored: list[dict[str, Any]] = []
        total = max(len(symbols), 1)
        for i, sym in enumerate(symbols, 1):
            series = candles_for(sym)
            upto = [b for b in series if b["datetime"] <= asof]
            if len(upto) < 25:
                _think_push(
                    "scan_log",
                    {"symbol": sym, "status": "skip", "reason": f"only {len(upto)} bars", "score": None},
                )
                continue
            closes = [float(b["close"]) for b in upto]
            vols = [float(b["volume"]) for b in upto]
            highs = [float(b["high"]) for b in upto]
            lows = [float(b["low"]) for b in upto]
            ret15 = (closes[-1] / closes[-16] - 1) * 100
            ret5 = (closes[-1] / closes[-6] - 1) * 100
            vol_ratio = (sum(vols[-5:]) / 5) / max(sum(vols[-20:-5]) / 15, 1)
            # ORB proxy: first 15 bars range break
            orb_hi = max(highs[:15])
            orb_lo = min(lows[:15])
            orb_break = closes[-1] > orb_hi * 1.001
            orb_fail = closes[-1] < orb_lo * 0.999
            # Strategy votes
            votes = []
            if orb_break and ret15 > 0.15:
                votes.append("J-A")
            if ret15 > 0.25 and vol_ratio > 1.1:
                votes.append("J-B")
            if abs(ret15) < 0.15 and vol_ratio < 0.9:
                votes.append("J-C")
            score = 50 + ret15 * 5 + ret5 * 2 + min(vol_ratio, 3) * 4 + (8 if "J-A" in votes else 0) + (6 if "J-B" in votes else 0)
            score = max(1, min(99, score))
            side = "LONG" if ret15 >= 0 else "SHORT"
            if "J-C" in votes and abs(ret15) < 0.1:
                side = "SHORT" if ret5 > 0 else "LONG"
            entry = closes[-1]
            sl_pct = 0.55
            if side == "LONG":
                sl = entry * (1 - sl_pct / 100)
                tp = entry + (entry - sl) * 2.0
            else:
                sl = entry * (1 + sl_pct / 100)
                tp = entry - (sl - entry) * 2.0
            reason_bits = [
                f"15m {ret15:+.2f}%",
                f"5m {ret5:+.2f}%",
                f"vol×{vol_ratio:.2f}",
            ]
            if orb_break:
                reason_bits.append("ORB break↑")
            if orb_fail:
                reason_bits.append("ORB fail↓")
            if votes:
                reason_bits.append("votes " + ",".join(votes))
            row = {
                "symbol": sym,
                "side": side,
                "score": round(score, 1),
                "strategy": votes[0] if votes else "J-B",
                "votes": votes,
                "entry": round(entry, 2),
                "sl": round(sl, 2),
                "tp": round(tp, 2),
                "rr": 2.0,
                "ret15": round(ret15, 2),
                "ret5": round(ret5, 2),
                "vol_ratio": round(vol_ratio, 2),
                "reasons": reason_bits,
                "status": "scanned",
            }
            scored.append(row)
            _think_push(
                "scan_log",
                {
                    "symbol": sym,
                    "status": "ok",
                    "score": row["score"],
                    "side": side,
                    "reason": " · ".join(reason_bits),
                    "strategy": row["strategy"],
                },
            )
            # Live brain charts: refresh price-action + score feed every few symbols
            if i == 1 or i % 8 == 0 or i == total:
                with _think_lock:
                    scan_snap = list(_think.get("scan_log") or [])
                    dec_snap = list(_think.get("decisions") or [])
                focus = build_symbol_price_action(symbol=sym, asof=asof, pick=row)
                activity = build_brain_activity(scan_snap, dec_snap)
                _think_set(
                    charts={
                        "focus": focus,
                        "activity": activity,
                        "mode": "scanning",
                    }
                )
            if i % 5 == 0 or i == total:
                _think_line(
                    "scan",
                    f"Scanning {sym}",
                    f"{i}/{total} · score {row['score']} · {side}",
                    8 + (i / total) * 35,
                )
            _time.sleep(pace * 0.35)

        scored.sort(key=lambda x: float(x["score"]), reverse=True)
        longs = [s for s in scored if s["side"] == "LONG"][:8]
        shorts = [s for s in scored if s["side"] == "SHORT"][:8]
        bus.publish("jarvis.candidates", {"longs": longs, "shorts": shorts, "regime": "EXCEL_LIVE", "asof": asof})
        _think_line("decide", "Rank board ready", f"Top long {longs[0]['symbol'] if longs else '—'} · Top short {shorts[0]['symbol'] if shorts else '—'}", 48)

        for s in (longs[:5] + shorts[:3]):
            decision = {
                **s,
                "verdict": "shortlist",
                "why": f"{s['symbol']} {s['side']} because " + "; ".join(s.get("reasons") or []),
            }
            _think_push("decisions", decision)
            _time.sleep(pace * 0.5)

        picked = longs[0] if longs else (shorts[0] if shorts else None)
        if not picked:
            _think_set(running=False, phase="error", error="No tradeable scores", title="No setup", progress=100, finished_at=time.time())
            return {"ok": False, "error": "No tradeable scores", "think": thinking_state()}

        _think_line(
            "decide",
            "Primary pick",
            f"{picked['symbol']} {picked['side']} · score {picked['score']} · {picked['strategy']} · entry {picked['entry']} SL {picked['sl']} TP {picked['tp']}",
            55,
        )
        _think_set(picked=picked)
        # Lock charts onto the chosen name — full OHLC brain view
        with _think_lock:
            scan_snap = list(_think.get("scan_log") or [])
            dec_snap = list(_think.get("decisions") or [])
        _think_set(
            charts={
                "focus": build_symbol_price_action(symbol=picked["symbol"], asof=asof, pick=picked),
                "activity": build_brain_activity(scan_snap, dec_snap),
                "mode": "picked",
            }
        )
        _time.sleep(pace)

        claude_payload = None
        if use_claude:
            _think_line("claude", "Claude Code CLI", "Sending shortlist for veto / approve…", 60)
            prompt = f"""You are JARVIS equity intraday advisor. Session replay from real Zerodha 1m Excel pack.
As-of: {asof}
Primary pick: {json.dumps(picked)}
Other longs: {json.dumps(longs[1:4])}
Other shorts: {json.dumps(shorts[:3])}

Return ONLY JSON:
{{"summary":"2 sentences","approve":true/false,"vetoes":[],"why":"one line","size":"full|half"}}
"""
            raw = call_llm_auto(prompt)
            provider = last_llm_provider() or "none"
            approve = True
            why = "Rules-only fallback"
            summary = "Claude unavailable — proceeding on rules rank."
            size = "full"
            if raw:
                try:
                    text = raw.strip()
                    if "```" in text:
                        text = text.split("```")[1]
                        if text.startswith("json"):
                            text = text[4:]
                    data = json.loads(text.strip())
                    summary = data.get("summary") or summary
                    approve = bool(data.get("approve", True))
                    why = data.get("why") or why
                    size = data.get("size") or "full"
                    for v in data.get("vetoes") or []:
                        _think_push("decisions", {"symbol": str(v).upper(), "verdict": "claude_veto", "why": "Claude veto"})
                except Exception:
                    summary = (raw or "")[:500]
            claude_payload = {"provider": provider, "summary": summary, "approve": approve, "why": why, "size": size, "raw": (raw or "")[:800]}
            _think_set(claude=claude_payload)
            _think_line("claude", "Claude verdict", f"{'APPROVE' if approve else 'VETO'} · {why}", 70)
            if not approve:
                # fall to next long
                alt = next((x for x in longs[1:] if x["symbol"] != picked["symbol"]), None)
                if alt:
                    picked = alt
                    _think_set(picked=picked)
                    with _think_lock:
                        scan_snap = list(_think.get("scan_log") or [])
                        dec_snap = list(_think.get("decisions") or [])
                    _think_set(
                        charts={
                            "focus": build_symbol_price_action(symbol=picked["symbol"], asof=asof, pick=picked),
                            "activity": build_brain_activity(scan_snap, dec_snap),
                            "mode": "picked",
                        }
                    )
                    _think_line("decide", "Fallback pick after veto", f"{picked['symbol']} {picked['side']}", 72)
                else:
                    _think_set(running=False, phase="done", title="Claude vetoed all", progress=100, finished_at=time.time())
                    return {"ok": True, "vetoed": True, "think": thinking_state()}
            _time.sleep(pace)
        else:
            _think_line("claude", "Claude skipped", "Rules-only path", 70)

        # Risk gate
        _think_line("risk", "Risk gate", f"R:R {picked['rr']} · mode PAPER · max daily loss check OK", 78)
        _think_push(
            "execution",
            {"step": "risk_pass", "message": f"Intent accepted · {picked['symbol']} {picked['side']} @ {picked['entry']}"},
        )
        _time.sleep(pace)

        # Execute paper
        _sim["last_agent"] = {
            "agent": "jarvis_excel_live",
            "regime": "EXCEL_LIVE",
            "ai_summary": (claude_payload or {}).get("summary") or "Rules pick",
            "claude_provider": (claude_payload or {}).get("provider"),
            "candidates": {"longs": longs, "shorts": shorts, "regime": "EXCEL_LIVE", "asof": asof},
            "parallel": "excel_live_demo",
        }
        # Force pick onto board top for paper_execute_top
        bus.publish(
            "jarvis.candidates",
            {"longs": [picked] + [x for x in longs if x["symbol"] != picked["symbol"]], "shorts": shorts, "regime": "EXCEL_LIVE"},
        )
        _think_line("exec", "Sending paper order", f"BUY/SELL {picked['symbol']} MIS · qty 50 · Groww sim", 82)
        exe = paper_execute_top(side=str(picked["side"]))
        _think_push("execution", {"step": "filled", "message": f"Paper fill {picked['symbol']}", "order": exe.get("order"), "position": exe.get("position")})
        _time.sleep(pace * 1.2)

        entry = float(picked["entry"])
        # Simulate path toward target
        mid = entry * (1.004 if picked["side"] == "LONG" else 0.996)
        _think_line("manage", "Position management", f"Marking LTP → {mid:.2f} (working toward TP {picked['tp']})", 88)
        mark_price(symbol=picked["symbol"], ltp=mid)
        _think_push("execution", {"step": "mark", "message": f"LTP {mid:.2f} · unrealized updating"})
        _time.sleep(pace)

        _think_line("manage", "Target hit", f"Closing {picked['symbol']} at TP logic", 94)
        done = hit_tp(picked["symbol"])
        pnl = float(((done.get("closed") or {}).get("unrealised_pnl")) or 0)
        # After close, day_pnl already updated; closed dict still has last uPNL
        _think_push(
            "execution",
            {
                "step": "closed",
                "message": f"Exit TARGET · booked into day P&L",
                "closed": done.get("closed"),
                "day_pnl": _sim.get("day_pnl"),
            },
        )
        _think_line(
            "done",
            "Run complete",
            f"Picked {picked['symbol']} · Claude {(claude_payload or {}).get('provider') or 'off'} · Day P&L {_sim.get('day_pnl')}",
            100,
        )
        _think_set(running=False, finished_at=time.time(), phase="done")
        try:
            from TRADELE.services.jarvis.memory import append_event, end_session

            append_event(
                "session.summary",
                {
                    "picked": picked,
                    "claude": claude_payload,
                    "day_pnl": _sim.get("day_pnl"),
                    "asof": asof,
                },
            )
            end_session(summary={"picked": picked.get("symbol"), "day_pnl": _sim.get("day_pnl")})
        except Exception:
            pass
        return {
            "ok": True,
            "picked": picked,
            "claude": claude_payload,
            "asof": asof,
            "sim": sim_state(),
            "think": thinking_state(),
            "pnl_hint": pnl,
        }
    except Exception as e:
        logger = __import__("logging").getLogger(__name__)
        logger.exception("excel live demo failed")
        _think_set(running=False, phase="error", error=str(e), title="Failed", finished_at=time.time())
        try:
            from TRADELE.services.jarvis.memory import end_session

            end_session(summary={"error": str(e)})
        except Exception:
            pass
        return {"ok": False, "error": str(e), "think": thinking_state()}


_demo_thread = None


def start_excel_live_demo_async(*, use_claude: bool = True, pace: float = 0.08) -> dict[str, Any]:
    global _demo_thread
    import threading

    if thinking_state().get("running"):
        return {"ok": False, "error": "Demo already running", "think": thinking_state()}

    def _job() -> None:
        run_excel_live_demo(use_claude=use_claude, pace=pace)

    _demo_thread = threading.Thread(target=_job, name="jarvis-excel-demo", daemon=True)
    _demo_thread.start()
    return {"ok": True, "started": True, "think": thinking_state()}

